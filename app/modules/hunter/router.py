from fastapi import APIRouter, Depends

from app.core.dependencies import TenantContext, get_tenant_context
from app.modules.hunter.client import HunterClient
from app.modules.hunter.schemas import DomainSearchRequest, FindEmailRequest, VerifyEmailRequest
from app.modules.hunter.service import HunterService

router = APIRouter(prefix="/hunter", tags=["hunter"])


@router.post("/find-email")
async def find_email(
    data: FindEmailRequest, _tenant: TenantContext = Depends(get_tenant_context)
) -> dict[str, object]:
    result = await HunterService().find_confident_email(
        data.domain, data.first_name, data.last_name
    )
    return {"found": result is not None, "result": result}


@router.post("/verify")
async def verify(
    data: VerifyEmailRequest, _tenant: TenantContext = Depends(get_tenant_context)
) -> dict[str, object]:
    return await HunterService().verify(str(data.email))


@router.post("/domain-search")
async def domain_search(
    data: DomainSearchRequest, _tenant: TenantContext = Depends(get_tenant_context)
) -> dict[str, object]:
    return {"emails": await HunterClient().domain_search(data.domain)}


@router.get("/account")
async def account(_tenant: TenantContext = Depends(get_tenant_context)) -> dict[str, object]:
    return await HunterClient().account_info()
