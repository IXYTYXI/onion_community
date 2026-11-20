import secrets

from fastapi import APIRouter, Request

from app.api.dependencies import CurrentUser
from app.core.error_codes import ErrorCode
from app.core.errors import AppError
from app.schemas.common import success

router = APIRouter(prefix="/api/v1", tags=["站点统计与设置"])


@router.get("/visitors")
@router.post("/visitors")
async def visitors(request: Request, user: CurrentUser):
    data = await request.app.state.site.visitors(user, active=request.method == "POST")
    return success(request, data)


@router.post("/site-settings/webhook")
async def refresh(request: Request):
    token = request.app.state.settings.site_switch_webhook_token.get_secret_value()
    provided = request.headers.get("authorization", "")
    if not token or not secrets.compare_digest(provided.encode(), ("Bearer " + token).encode()):
        raise AppError(ErrorCode.UNAUTHORIZED)
    await request.app.state.site.refresh()
    return success(request, {"updated": True})
