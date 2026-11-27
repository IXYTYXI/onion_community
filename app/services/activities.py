"""Shared AI activity directory and private image cache (covers + archive photos)."""
import hashlib
import re
from datetime import UTC, date, datetime, time as dt_time, timedelta
from zoneinfo import ZoneInfo

from app.schemas.activities import ActivityDirectory, ActivityItem, ActivityLink, ActivityPhoto
from app.services.cached_snapshot import CachedSnapshotService
from app.services.cases import safe_link
from app.services.officers import text_value
from app.services.private_media import PrivateImageCache

SHANGHAI = ZoneInfo("Asia/Shanghai")
ACTIVITY_FIELDS = [
    "活动主题",
    "活动日期",
    "时间",
    "活动对象",
    "讲师",
    "负责人",
    "地点",
    "报名链接",
    "日程链接",
    "文档资料",
    "课程回放",
    "活动照片",
]
TIME_RANGE_RE = re.compile(
    r"(\d{1,2})[:：](\d{2})(?:\s*(?:[~～\-–—至到]+)\s*(\d{1,2})[:：](\d{2}))?"
)
ALLOWED_IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp", "image/gif", "image/mpo"}


def parse_activity_date(raw) -> date | None:
    if isinstance(raw, dict) and "value" in raw:
        raw = raw["value"]
    if isinstance(raw, list) and raw:
        raw = raw[0]
    if isinstance(raw, (int, float)) and raw > 0:
        seconds = raw / 1000 if raw > 10_000_000_000 else raw
        return datetime.fromtimestamp(seconds, SHANGHAI).date()
    text = text_value(raw)
    if not text:
        return None
    m = re.search(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def parse_schedule(raw_date, raw_time) -> tuple[str, str, datetime | None, datetime | None]:
    day = parse_activity_date(raw_date)
    time_label = text_value(raw_time)
    if day is None:
        return "", time_label, None, None
    date_label = day.isoformat()
    match = TIME_RANGE_RE.search(time_label)
    if match:
        sh, sm = int(match.group(1)), int(match.group(2))
        if sh <= 23 and sm <= 59:
            starts_at = datetime.combine(day, dt_time(sh, sm), tzinfo=SHANGHAI)
            if match.group(3) is not None and match.group(4) is not None:
                eh, em = int(match.group(3)), int(match.group(4))
                if eh <= 23 and em <= 59:
                    ends_at = datetime.combine(day, dt_time(eh, em), tzinfo=SHANGHAI)
                    if ends_at <= starts_at:
                        ends_at += timedelta(days=1)
                    return date_label, time_label, starts_at, ends_at
            return date_label, time_label, starts_at, starts_at + timedelta(minutes=90)
    starts_at = datetime.combine(day, dt_time(9, 0), tzinfo=SHANGHAI)
    ends_at = datetime.combine(day, dt_time(23, 59, 59), tzinfo=SHANGHAI)
    return date_label, time_label, starts_at, ends_at


def parse_links(value, default_title: str) -> list[ActivityLink]:
    if value is None:
        return []
    if isinstance(value, dict):
        if "value" in value and isinstance(value["value"], list):
            return parse_links(value["value"], default_title)
        url = safe_link(value)
        if url:
            label = text_value(value.get("text")) or default_title
            if label == url:
                label = default_title
            return [ActivityLink(title=label, url=url)]
        return []
    if isinstance(value, list):
        results: list[ActivityLink] = []
        seen: set[str] = set()
        for entry in value:
            for link in parse_links(entry, default_title):
                if link.url not in seen:
                    seen.add(link.url)
                    results.append(link)
        return results
    if isinstance(value, str):
        results = []
        seen = set()
        for line in value.splitlines():
            part = line.strip()
            if not part:
                continue
            if "|" in part:
                left, right = part.split("|", 1)
                url = safe_link(right.strip())
                label = left.strip() or default_title
            else:
                md = re.fullmatch(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", part)
                if md:
                    label = md.group(1).strip() or default_title
                    url = safe_link(md.group(2))
                else:
                    url = safe_link(part)
                    label = default_title
            if url and url not in seen:
                seen.add(url)
                results.append(ActivityLink(title=label if label != url else default_title, url=url))
        return results
    return []


def _extract_attachments(key_prefix: str, raw_attachments, media: dict) -> list[ActivityPhoto]:
    photos: list[ActivityPhoto] = []
    if not isinstance(raw_attachments, list):
        return photos
    seen = set()
    for attachment in raw_attachments:
        if not isinstance(attachment, dict):
            continue
        token = attachment.get("file_token")
        mime = attachment.get("type", "")
        if not isinstance(token, str) or not token or token in seen:
            continue
        if mime and mime not in ALLOWED_IMAGE_MIMES:
            continue
        seen.add(token)
        image_id = hashlib.sha256((key_prefix + "|" + token).encode()).hexdigest()
        media[image_id] = {"file_token": token, "url": attachment.get("url") or ""}
        photos.append(
            ActivityPhoto(
                id=image_id,
                name=text_value(attachment.get("name")),
                url="/api/v1/activities/media/" + image_id,
            )
        )
    return photos


class ActivityService(CachedSnapshotService, PrivateImageCache):
    snapshot_schema = ActivityDirectory
    image_size = (1600, 1600)

    def __init__(self, store, source, settings):
        self.store, self.source, self.settings = store, source, settings
        identity = "|".join([
            settings.feishu_app_id,
            settings.feishu_bitable_app_token.get_secret_value(),
            settings.activities_table_id,
            settings.activities_view_id,
        ])
        self.key = "activities:v1:" + hashlib.sha256(identity.encode()).hexdigest()[:24]
        self.root = settings.media_root / "activities"
        self.cache_seconds = settings.activities_cache_seconds
        self.stale_seconds = settings.activities_stale_seconds

    @staticmethod
    def contains_image(snapshot, image_id: str) -> bool:
        for item in getattr(snapshot, "items", []):
            if item.cover_image and item.cover_image.rsplit("/", 1)[-1] == image_id:
                return True
            if any(photo.id == image_id for photo in item.photos):
                return True
        return False

    async def force_refresh(self) -> ActivityDirectory:
        await self.store.delete(self.key + ":fresh")
        await self.store.delete(self.key + ":cooldown")
        return await self.read()

    def normalize(self, records):
        items: list[ActivityItem] = []
        seen: set[str] = set()
        media: dict[str, dict[str, str]] = {}
        for record in records:
            record_id = record["record_id"]
            if record_id in seen:
                raise ValueError("Duplicate activity record")
            seen.add(record_id)
            fields = record.get("fields", {})
            title = text_value(fields.get("活动主题"))
            if not title:
                continue
            date_label, time_label, starts_at, ends_at = parse_schedule(
                fields.get("活动日期"), fields.get("时间")
            )
            covers = _extract_attachments(self.key, fields.get("活动封面"), media)
            photos = _extract_attachments(self.key, fields.get("活动照片"), media)
            signup_links = parse_links(fields.get("报名链接"), "报名链接")
            calendar_links = parse_links(fields.get("日程链接"), "日程链接")
            items.append(
                ActivityItem(
                    id=record_id,
                    title=title,
                    summary=text_value(fields.get("活动简介")),
                    speaker=text_value(fields.get("讲师")),
                    organizer=text_value(fields.get("负责人")),
                    audience=text_value(fields.get("活动对象")),
                    location=text_value(fields.get("地点")),
                    date_label=date_label,
                    time_label=time_label,
                    starts_at=starts_at,
                    ends_at=ends_at,
                    signup_url=signup_links[0].url if signup_links else safe_link(fields.get("报名链接")),
                    calendar_url=calendar_links[0].url if calendar_links else safe_link(fields.get("日程链接")),
                    documents=parse_links(fields.get("文档资料"), "文档资料"),
                    replays=parse_links(fields.get("课程回放"), "课程回放"),
                    cover_image=covers[0].url if covers else None,
                    photos=photos,
                )
            )
        return ActivityDirectory(items=items, updated_at=datetime.now(UTC)), media
