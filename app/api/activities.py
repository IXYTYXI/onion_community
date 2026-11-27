import hmac

from fastapi import APIRouter, Request
from starlette.responses import FileResponse

from app.api.dependencies import CurrentUser, check_source_tenant
from app.api.error_docs import error_responses
from app.core.error_codes import ErrorCode
from app.core.errors import AppError
from app.schemas.activities import ActivityDirectory
from app.schemas.common import Envelope, success

router = APIRouter(prefix="/api/v1/activities", tags=["AI 活动"], responses=error_responses())


@router.get("", response_model=Envelope[ActivityDirectory])
async def directory(request: Request, user: CurrentUser):
    check_source_tenant(request, user, "activities")
    return success(request, await request.app.state.activities.read())


@router.get(
    "/media/{image_id}",
    response_class=FileResponse,
    responses={200: {"content": {"image/webp": {"schema": {"type": "string", "format": "binary"}}}}},
)
async def photo(image_id: str, request: Request, user: CurrentUser):
    check_source_tenant(request, user, "activities")
    path = await request.app.state.activities.image(image_id)
    return FileResponse(path, media_type="image/webp")


@router.post("/webhook")
async def refresh_webhook(request: Request):
    configured = request.app.state.settings.activities_webhook_token.get_secret_value()
    provided = request.headers.get("authorization", "").removeprefix("Bearer ")
    if not configured or not hmac.compare_digest(provided, configured):
        raise AppError(ErrorCode.UNAUTHORIZED)
    result = await request.app.state.activities.force_refresh()
    return success(request, {"updated": True, "count": len(result.items), "stale": result.stale})
