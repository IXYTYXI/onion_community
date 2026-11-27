"""Application identity writer. Never borrows a developer's CLI login."""

import asyncio
from urllib.parse import quote

from app.core.error_codes import ErrorCode
from app.core.errors import AppError
from app.integrations.feishu_directory import FeishuDirectorySource


class BitablePermissionError(AppError):
    def __init__(self, upstream_code):
        super().__init__(ErrorCode.UPSTREAM_ERROR)
        self.upstream_code = upstream_code


class BitableLinkError(AppError):
    def __init__(self, upstream_code):
        super().__init__(ErrorCode.UPSTREAM_ERROR)
        self.upstream_code = upstream_code


class BitableWriter(FeishuDirectorySource):
    @staticmethod
    def payload(response):
        try:
            return FeishuDirectorySource.payload(response)
        except AppError:
            try:
                data = response.json()
            except ValueError:
                data = {}
            code = data.get("code") if isinstance(data, dict) else None
            if response.status_code == 403 or code == 91403:
                raise BitablePermissionError(code or response.status_code) from None
            if code in {1254015, 1254043, 1254045}:
                raise BitableLinkError(code) from None
            raise

    def __init__(self, *args, base_token=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.base_token = self.settings.feishu_bitable_app_token if base_token is None else base_token
        self.token_key += ":bitable-writer"

    async def token(self):
        async with self._token_lock:
            cached = await self.store.get(self.token_key)
            if cached:
                return cached
            s = self.settings
            response = await self.client.post(
                "https://accounts.feishu.cn/oauth/v3/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": s.feishu_app_id,
                    "client_secret": s.feishu_app_secret.get_secret_value(),
                    "scope": "bitable:app",
                },
            )
            data = self.payload(response)
            token, expires = data.get("access_token"), data.get("expires_in")
            if not isinstance(token, str) or not isinstance(expires, int):
                raise AppError(ErrorCode.UPSTREAM_ERROR)
            await self.store.set(self.token_key, token, ttl=max(1, expires - 120))
            return token

    async def records(self):
        # Synchronization must see hidden/filtered rows too; a view is presentation only.
        return await self.all_records()

    async def all_records(self, *, record_filter=None):
        base = quote(self.base_token.get_secret_value(), safe="")
        path = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{base}/tables/{self.table_id}/records/search"
        rows, page, seen = [], None, set()
        body = {"field_names": self.fields}
        if record_filter is not None:
            body["filter"] = record_filter
        for _ in range(200):
            params = {"page_size": 500}
            if page:
                params["page_token"] = page
            response = await self.client.post(
                path,
                params=params,
                json=body,
                headers={"Authorization": "Bearer " + await self.token()},
                timeout=40,
            )
            data = self.payload(response)["data"]
            rows.extend(data["items"])
            if not data.get("has_more"):
                return rows
            page = data.get("page_token")
            if not page or page in seen:
                raise ValueError("Invalid Feishu pagination")
            seen.add(page)
        raise ValueError("Feishu pagination limit exceeded")

    async def create_once(self, fields, client_token):
        """Create one record with Feishu's UUID idempotency parameter."""
        base = quote(self.base_token.get_secret_value(), safe="")
        table = quote(self.table_id, safe="")
        response = await self.client.post(
            f"https://open.feishu.cn/open-apis/bitable/v1/apps/{base}/tables/{table}/records",
            headers={"Authorization": "Bearer " + await self.token()},
            params={"client_token": client_token},
            json={"fields": fields},
            timeout=40,
        )
        return self.payload(response)["data"]["record"]

    async def write(self, records, *, update=False):
        if not records:
            return []
        base = quote(self.base_token.get_secret_value(), safe="")
        action = "batch_update" if update else "batch_create"
        response = await self.client.post(
            f"https://open.feishu.cn/open-apis/bitable/v1/apps/{base}/tables/{self.table_id}/records/{action}",
            headers={"Authorization": "Bearer " + await self.token()},
            json={"records": records},
            timeout=40,
        )
        data = self.payload(response)["data"]["records"]
        if len(data) != len(records):
            raise ValueError("Incomplete Feishu batch acknowledgement")
        await asyncio.sleep(0.3)
        return data
