from fastapi import APIRouter, Request
from starlette.responses import FileResponse

from app.api.dependencies import CurrentUser, check_source_tenant
from app.api.error_docs import error_responses
from app.schemas.cases import CaseDirectory, CaseEngagement, EngagementAction, EngagementDirectory, EngagementInput
from app.schemas.common import Envelope, success

router = APIRouter(prefix='/api/v1/cases', tags=['AI 案例'], responses=error_responses())



@router.get('', response_model=Envelope[CaseDirectory])
async def directory(request: Request, user: CurrentUser):
    check_source_tenant(request, user, "cases")
    return success(request, await request.app.state.cases.read())


@router.get('/media/{image_id}', response_class=FileResponse,
            responses={200: {'content': {'image/webp': {'schema': {'type': 'string', 'format': 'binary'}}}}})
async def cover(image_id: str, request: Request, user: CurrentUser):
    check_source_tenant(request, user, "cases")
    return FileResponse(await request.app.state.cases.image(image_id), media_type='image/webp')


@router.get('/engagement', response_model=Envelope[EngagementDirectory])
async def engagement(request: Request, user: CurrentUser, personal: EngagementAction | None = None):
    check_source_tenant(request, user, "cases")
    service = request.app.state.case_engagement
    return success(request, await service.directory(request.app.state.cases, user, personal))


@router.put('/{case_id}/engagement/{action}', response_model=Envelope[CaseEngagement])
async def set_engagement(case_id: str, action: EngagementAction, body: EngagementInput,
                         request: Request, user: CurrentUser):
    check_source_tenant(request, user, "cases")
    service = request.app.state.case_engagement
    return success(request, await service.set_active(request.app.state.cases, user, case_id, action, body.active))
