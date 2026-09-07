.PHONY: up down test test-phase3-coverage test-phase4 test-phase4-coverage lint migrate frontend
up:
	docker compose up --build
down:
	docker compose down
test:
	pytest --cov=app.modules.auth.service --cov=app.modules.contacts.service --cov=app.modules.sender.service --cov=app.modules.scheduler.service --cov=app.core.security --cov-report=term-missing --cov-fail-under=80
test-phase3-coverage:
	pytest tests/test_phase3_services.py tests/test_phase3_coverage.py \
		--cov=app.modules.ab_testing.service \
		--cov=app.modules.email_validation.service \
		--cov=app.modules.enrichment.service \
		--cov=app.modules.analytics.service \
		--cov=app.modules.domains.service \
		--cov=app.modules.warmup.service \
		--cov=app.modules.blacklists.service \
		--cov=app.modules.quality.service \
		--cov-report=term-missing --cov-fail-under=80
test-phase4:
	pytest tests/test_phase4_enterprise.py tests/test_phase4_regressions.py tests/test_phase4_service_coverage.py
test-phase4-coverage:
	pytest tests/test_phase4_enterprise.py tests/test_phase4_regressions.py tests/test_phase4_service_coverage.py \
		--cov=app.modules.notifications.service \
		--cov=app.modules.audit.service \
		--cov=app.modules.webhooks.service \
		--cov=app.modules.billing.service \
		--cov=app.modules.billing.providers \
		--cov-report=term-missing --cov-fail-under=80
lint:
	ruff check app tests && black --check app tests && mypy app
migrate:
	alembic upgrade head
frontend:
	cd frontend && npm run dev
