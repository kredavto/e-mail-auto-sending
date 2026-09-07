"""Immutable tenant audit trail and audit decorator."""

from app.modules.audit.service import audited

__all__ = ["audited"]
