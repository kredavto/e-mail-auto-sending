from app.core.exceptions import AppError


class EmailDeliveryError(AppError):
    status_code = 502


class DeliveryDeferred(AppError):
    """Capacity is temporarily exhausted; the scheduler should try later."""

    def __init__(self, message: str, retry_after: int = 3600) -> None:
        super().__init__(message)
        self.retry_after = retry_after
