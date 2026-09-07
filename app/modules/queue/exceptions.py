from app.core.exceptions import AppError


class QueueUnavailableError(AppError):
    status_code = 503
