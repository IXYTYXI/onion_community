import { imageUrl, safeUrl } from './urls.js';

export function parseTimestamp(value) {
  if (!value) return null;
  const ms = Date.parse(value);
  return Number.isFinite(ms) ? ms : null;
}

export function activityImageUrl(url) {
  return /^\/api\/v1\/activities\/media\/[a-f0-9]{64}$/.test(url || '') ? url : imageUrl(url);
}

export function normalizeActivity(item) {
  const startsMs = parseTimestamp(item.starts_at);
  const endsMs = parseTimestamp(item.ends_at);
  return {
    ...item,
    startsMs,
    endsMs,
    signupUrl: safeUrl(item.signup_url),
    calendarUrl: safeUrl(item.calendar_url),
    coverUrl: activityImageUrl(item.cover_image),
    documents: Array.isArray(item.documents)
      ? item.documents
          .map((doc) => ({ title: doc?.title || '文档资料', url: safeUrl(doc?.url) }))
          .filter((doc) => doc.url)
      : [],
    replays: Array.isArray(item.replays)
      ? item.replays
          .map((rep) => ({ title: rep?.title || '课程回放', url: safeUrl(rep?.url) }))
          .filter((rep) => rep.url)
      : [],
    photos: Array.isArray(item.photos)
      ? item.photos
          .map((photo) => ({
            id: photo?.id || '',
            name: photo?.name || '活动现场照片',
            url: activityImageUrl(photo?.url),
          }))
          .filter((photo) => photo.id && photo.url)
      : [],
  };
}

/**
 * Partition all activities at a given `nowMs` into:
 * - featured: nearest not-yet-ended activity (Part 1, unlocks signup & calendar buttons)
 * - upcoming: remaining future activities sorted nearest-first (Part 2, preview only)
 * - ended: finished activities sorted newest-first (Part 3, archive & photo gallery)
 */
export function partitionActivities(items, nowMs = Date.now()) {
  const normalized = (Array.isArray(items) ? items : []).map(normalizeActivity);
  const activeOrUpcoming = [];
  const ended = [];

  for (const item of normalized) {
    const hasArchiveOnly = item.endsMs === null && (item.photos.length > 0 || item.replays.length > 0);
    if (hasArchiveOnly || (item.endsMs !== null && nowMs >= item.endsMs)) {
      ended.push(item);
    } else {
      activeOrUpcoming.push(item);
    }
  }

  activeOrUpcoming.sort((a, b) => {
    const sa = a.startsMs ?? Number.MAX_SAFE_INTEGER;
    const sb = b.startsMs ?? Number.MAX_SAFE_INTEGER;
    if (sa !== sb) return sa - sb;
    return String(a.id).localeCompare(String(b.id));
  });

  ended.sort((a, b) => {
    const ea = a.startsMs ?? a.endsMs ?? -1;
    const eb = b.startsMs ?? b.endsMs ?? -1;
    if (eb !== ea) return eb - ea;
    return String(a.id).localeCompare(String(b.id));
  });

  const featured = activeOrUpcoming[0] || null;
  const upcoming = activeOrUpcoming.slice(1);
  return { featured, upcoming, ended };
}

export function featuredStatus(item, nowMs = Date.now()) {
  if (!item) return { code: 'empty', badge: '暂无近期活动', hint: '近期新活动筹备中，欢迎先浏览下方往期活动回顾与资料。' };
  if (item.startsMs !== null && nowMs >= item.startsMs && (item.endsMs === null || nowMs < item.endsMs)) {
    return {
      code: 'ongoing',
      badge: '进行中',
      hint: '活动正在进行中，可加入日程或查看现场相关资料。',
    };
  }
  return {
    code: 'upcoming',
    badge: '报名开放中',
    hint: '提交飞书报名表后将自动邀请入群，点击日程链接可自助加入日历提醒。',
  };
}

export function nextTransitionDelay(items, nowMs = Date.now()) {
  let nearest = Infinity;
  for (const raw of Array.isArray(items) ? items : []) {
    for (const field of [raw.starts_at, raw.ends_at, raw.startsMs, raw.endsMs]) {
      const ts = typeof field === 'number' ? field : parseTimestamp(field);
      if (ts !== null && ts > nowMs && ts - nowMs < nearest) {
        nearest = ts - nowMs;
      }
    }
  }
  if (!Number.isFinite(nearest)) return null;
  // Cap single setTimeout to 1 hour to avoid 32-bit timer overflow; re-evaluates on fire.
  return Math.min(Math.max(nearest + 250, 250), 3_600_000);
}

export function formatScheduleLabel(item) {
  if (!item) return '时间待定';
  const parts = [item.date_label, item.time_label].filter(Boolean);
  return parts.length ? parts.join(' ') : '时间待定';
}
