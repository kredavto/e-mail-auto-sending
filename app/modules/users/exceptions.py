from app.core.exceptions import ConflictError


class WorkspaceSlugExistsError(ConflictError):
    pass
