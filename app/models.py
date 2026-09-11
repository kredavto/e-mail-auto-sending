"""Registers all persisted models on the shared SQLAlchemy metadata."""

from app.modules.ab_testing.models import ABTest, ABTestAssignment, ABTestVariant
from app.modules.analytics.models import AnalyticsReport, DailyMetric
from app.modules.assistant.models import AssistantRun
from app.modules.audit.models import AuditExport, AuditLog, SecurityAuditEvent
from app.modules.auth.models import AuthSession
from app.modules.billing.models import Invoice, PaymentEvent, Subscription, UsageLog
from app.modules.bitrix24.models import BitrixSyncLog
from app.modules.blacklists.models import BlacklistAlert, BlacklistCheck, BlacklistSubscription
from app.modules.campaigns.models import Campaign, CampaignContact
from app.modules.contacts.models import Contact, Segment
from app.modules.domains.models import DomainVerification, SendingDomain
from app.modules.email_validation.models import EmailValidationResult
from app.modules.enrichment.models import EnrichmentResult
from app.modules.file_upload.models import UploadedFile
from app.modules.linkedin.models import LinkedInExport, LinkedInProfile
from app.modules.notifications.models import (
    EnterpriseEventOutbox,
    Notification,
    NotificationDelivery,
    NotificationPreference,
    WebPushSubscription,
)
from app.modules.omnichannel.models import OmnichannelEvent
from app.modules.portfolio.models import PortfolioCase
from app.modules.products.models import Product
from app.modules.queue.models import FailedTask
from app.modules.sender.models import EmailMessage
from app.modules.sequences.models import Sequence, SequenceStep
from app.modules.signatures.models import Signature
from app.modules.templates.models import Template, TemplateVersion
from app.modules.tenchat.models import TenchatMessage, TenchatProfile
from app.modules.tracking.models import TrackingEvent
from app.modules.users.models import User, Workspace, WorkspaceInvitation, WorkspaceMember
from app.modules.warmup.models import WarmupPlan
from app.modules.webhooks.models import Webhook, WebhookDelivery, WebhookOutbox

__all__ = [
    "AssistantRun",
    "AuthSession",
    "AuditExport",
    "AuditLog",
    "SecurityAuditEvent",
    "ABTest",
    "ABTestAssignment",
    "ABTestVariant",
    "AnalyticsReport",
    "BitrixSyncLog",
    "Campaign",
    "CampaignContact",
    "BlacklistAlert",
    "BlacklistCheck",
    "BlacklistSubscription",
    "Contact",
    "DailyMetric",
    "DomainVerification",
    "EmailMessage",
    "EmailValidationResult",
    "EnrichmentResult",
    "EnterpriseEventOutbox",
    "FailedTask",
    "LinkedInExport",
    "LinkedInProfile",
    "Invoice",
    "Notification",
    "NotificationDelivery",
    "NotificationPreference",
    "OmnichannelEvent",
    "PortfolioCase",
    "PaymentEvent",
    "Product",
    "Segment",
    "Sequence",
    "SequenceStep",
    "Signature",
    "Subscription",
    "SendingDomain",
    "Template",
    "TemplateVersion",
    "TenchatMessage",
    "TenchatProfile",
    "TrackingEvent",
    "UploadedFile",
    "UsageLog",
    "User",
    "Workspace",
    "WorkspaceInvitation",
    "WorkspaceMember",
    "WarmupPlan",
    "Webhook",
    "WebhookDelivery",
    "WebhookOutbox",
    "WebPushSubscription",
]
