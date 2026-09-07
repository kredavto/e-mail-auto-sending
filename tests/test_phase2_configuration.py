import app.models  # noqa: F401
from app.celery_app import celery_app
from app.database import Base


def test_phase2_celery_tasks_and_schedules_are_registered() -> None:
    includes = set(celery_app.conf.include)
    for module in (
        "app.modules.ses.tasks",
        "app.modules.bitrix24.tasks",
        "app.modules.hunter.tasks",
        "app.modules.linkedin.tasks",
        "app.modules.tenchat.tasks",
        "app.modules.omnichannel.tasks",
    ):
        assert module in includes
    assert "check-bitrix-replies" in celery_app.conf.beat_schedule
    assert "check-tenchat-replies" in celery_app.conf.beat_schedule
    assert celery_app.conf.task_routes["app.modules.bitrix24.tasks.*"] == {"queue": "bitrix"}


def test_phase2_models_are_registered_on_shared_metadata() -> None:
    expected = {
        "bitrix_sync_logs",
        "linkedin_profiles",
        "linkedin_exports",
        "tenchat_profiles",
        "tenchat_messages",
        "omnichannel_events",
    }
    assert expected <= set(Base.metadata.tables)
