from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.core.exceptions import install_exception_handlers
from app.core.middleware import (
    AuditContextMiddleware,
    LoginRateLimitMiddleware,
    SecurityHeadersMiddleware,
)
from app.modules.ab_testing.router import router as ab_testing_router
from app.modules.analytics.router import router as analytics_router
from app.modules.audit.router import router as audit_router
from app.modules.auth.router import router as auth_router
from app.modules.billing.router import router as billing_router
from app.modules.bitrix24.router import router as bitrix_router
from app.modules.blacklists.router import router as blacklists_router
from app.modules.campaigns.router import router as campaigns_router
from app.modules.contacts.router import router as contacts_router
from app.modules.domains.router import router as domains_router
from app.modules.editor.router import router as editor_router
from app.modules.email_validation.router import router as email_validation_router
from app.modules.enrichment.router import router as enrichment_router
from app.modules.file_upload.router import router as files_router
from app.modules.hunter.router import router as hunter_router
from app.modules.linkedin.router import router as linkedin_router
from app.modules.notifications.router import router as notifications_router
from app.modules.omnichannel.router import router as omnichannel_router
from app.modules.portfolio.router import router as portfolio_router
from app.modules.products.router import router as products_router
from app.modules.quality.router import router as quality_router
from app.modules.queue.router import router as queue_router
from app.modules.scheduler.router import router as scheduler_router
from app.modules.sender.router import router as sender_router
from app.modules.sequences.router import router as sequences_router
from app.modules.ses.router import router as ses_router
from app.modules.signatures.router import router as signatures_router
from app.modules.templates.router import router as templates_router
from app.modules.tenchat.router import router as tenchat_router
from app.modules.tracking.router import router as tracking_router
from app.modules.users.router import profile_router
from app.modules.users.router import router as users_router
from app.modules.warmup.router import router as warmup_router
from app.modules.webhooks.router import router as webhooks_router


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Workspace-ID"],
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(LoginRateLimitMiddleware)
    app.add_middleware(AuditContextMiddleware)
    install_exception_handlers(app)
    for router in (
        auth_router,
        users_router,
        profile_router,
        contacts_router,
        files_router,
        products_router,
        templates_router,
        editor_router,
        signatures_router,
        portfolio_router,
        sequences_router,
        campaigns_router,
        sender_router,
        scheduler_router,
        tracking_router,
        queue_router,
        ses_router,
        bitrix_router,
        hunter_router,
        linkedin_router,
        tenchat_router,
        omnichannel_router,
        ab_testing_router,
        email_validation_router,
        enrichment_router,
        analytics_router,
        domains_router,
        warmup_router,
        blacklists_router,
        quality_router,
        notifications_router,
        audit_router,
        webhooks_router,
        billing_router,
    ):
        app.include_router(router, prefix="/api/v1")

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
