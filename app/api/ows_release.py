"""Public release presentation, updated by the publisher's authenticated hook."""
import asyncio
import hmac
import json

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, ValidationError
from starlette.responses import Response, StreamingResponse

from app.core.error_codes import ErrorCode
from app.core.errors import AppError
from app.schemas.common import success

RELEASE_URL = "https://ai.lab.yc345.tv/files/d/ows-release.json"
INSTALL_URL = "https://ai.lab.yc345.tv/files/d/ows-install.md"
RELEASE_KEY = "ows:release:current"
PUBLIC_FILES = {
    "ows-install.md": (INSTALL_URL, "text/markdown; charset=utf-8"),
    "ows-release.json": (RELEASE_URL, "application/json"),
}
router = APIRouter(prefix="/api/v1/ows-release", tags=["OWS 接入"])


class Change(BaseModel):
    category: str = Field(min_length=1, max_length=24)
    text: str = Field(min_length=1, max_length=500)


class ReleaseNote(BaseModel):
    version: str = Field(min_length=1, max_length=40)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    title: str = Field(min_length=1, max_length=120)
    changes: list[Change] = Field(max_length=30)


class ReleaseView(BaseModel):
    schema_version: int
    release_id: str = Field(min_length=1, max_length=120)
    cli_version: str = Field(min_length=1, max_length=40)
    python: str = Field(min_length=1, max_length=40)
    platforms: list[str] = Field(max_length=8)
    skills: list[str] = Field(max_length=12)
    release_notes: list[ReleaseNote] = Field(min_length=1, max_length=30)


async def fetch_release(request: Request) -> ReleaseView:
    try:
        response = await request.app.state.release_http.get(
            RELEASE_URL, headers={"Cache-Control": "no-cache", "Accept": "application/json"},
        )
        if response.status_code != 200 or len(response.content) > 128_000:
            raise AppError(ErrorCode.UPSTREAM_ERROR)
        release = ReleaseView.model_validate(response.json())
        if release.schema_version != 1 or release.release_notes[0].version != release.cli_version:
            raise ValueError("unsupported release manifest")
        return release
    except (httpx.HTTPError, ValueError, ValidationError, TypeError) as exc:
        raise AppError(ErrorCode.UPSTREAM_ERROR) from exc


async def saved_release(request: Request) -> ReleaseView:
    raw = await request.app.state.store.get(RELEASE_KEY)
    if raw is None:
        # Seed a new installation once. Subsequent changes come from the hook.
        release = await fetch_release(request)
        await request.app.state.store.set(RELEASE_KEY, release.model_dump_json())
        return release
    return ReleaseView.model_validate_json(raw)


@router.get("")
async def current(request: Request):
    release = await saved_release(request)
    response = success(request, release)
    return response


@router.get("/files/{filename}")
async def published_file(filename: str, request: Request):
    if filename not in PUBLIC_FILES:
        raise AppError(ErrorCode.NOT_FOUND)
    url, media_type = PUBLIC_FILES[filename]
    try:
        upstream = await request.app.state.release_http.get(
            url, headers={"Cache-Control": "no-cache"},
        )
        if upstream.status_code != 200 or len(upstream.content) > 128_000:
            raise AppError(ErrorCode.UPSTREAM_ERROR)
    except httpx.HTTPError as exc:
        raise AppError(ErrorCode.UPSTREAM_ERROR) from exc
    return Response(upstream.content, media_type=media_type, headers={"Cache-Control": "no-store"})


@router.post("/webhook")
async def published(request: Request):
    configured = request.app.state.settings.ows_release_webhook_token.get_secret_value()
    provided = request.headers.get("authorization", "").removeprefix("Bearer ")
    if not configured or not hmac.compare_digest(provided, configured):
        raise AppError(ErrorCode.UNAUTHORIZED)
    release = await fetch_release(request)
    await request.app.state.store.set(RELEASE_KEY, release.model_dump_json())
    return success(request, {"release_id": release.release_id, "updated": True})


@router.get("/events")
async def events(request: Request):
    async def stream():
        last = None
        while not await request.is_disconnected():
            raw = await request.app.state.store.get(RELEASE_KEY)
            if raw and raw != last:
                last = raw
                release_id = json.loads(raw)["release_id"]
                yield f"event: release\ndata: {json.dumps({'release_id': release_id})}\n\n"
            else:
                yield ": keepalive\n\n"
            await asyncio.sleep(3)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-store", "X-Accel-Buffering": "no",
    })
