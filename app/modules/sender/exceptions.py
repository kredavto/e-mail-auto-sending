from app.core.exceptions import AppError


class EmailDeliveryError(AppError):
    status_code = 502
