# ── Docker de desarrollo (PostgreSQL + Redis) ─────────────────────────────────
dev-up:
	docker compose -f docker-compose.dev.yml up -d

dev-down:
	docker compose -f docker-compose.dev.yml down

dev-logs:
	docker compose -f docker-compose.dev.yml logs -f

# ── n8n (deshabilitado) ───────────────────────────────────────────────────────
# n8n-export:
# 	bash docker/n8n-export.sh

# ── Django local ──────────────────────────────────────────────────────────────
install:
	pip install -r requirements-dev.txt
	python manage.py tailwind install

dev:
	python manage.py migrate
	python manage.py tailwind start &
	python manage.py runserver

tailwind:
	python manage.py tailwind start

migrate:
	python manage.py migrate

migrations:
	python manage.py makemigrations

shell:
	python manage.py shell

superuser:
	python manage.py createsuperuser

collect:
	python manage.py collectstatic --noinput

# ── Producción ────────────────────────────────────────────────────────────────
deploy:
	bash deploy.sh

nginx:
	bash nginx-deploy.sh

logs:
	docker compose logs -f django

down:
	docker compose down

.PHONY: dev-up dev-down dev-logs install dev tailwind migrate migrations shell superuser collect deploy nginx logs down
