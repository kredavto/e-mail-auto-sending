from app.core.exceptions import ConflictError


class ProductSlugExistsError(ConflictError):
    pass
