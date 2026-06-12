# ── Docker de desarrollo (PostgreSQL + Redis) ─────────────────────────────────
dev-up:
	docker compose -f docker-compose.dev.yml up -d

dev-down:
	docker compose -f docker-compose.dev.yml down

dev-logs:
	docker compose -f docker-compose.dev.yml logs -f

# ── n8n ───────────────────────────────────────────────────────────────────────
# Exporta los workflows de n8n dev al repo (para commitear).
n8n-export:
	bash docker/n8n-export.sh

# Importa los workflows del repo al n8n levantado (prod). No es automático.
n8n-import:
	bash docker/n8n-import.sh

# ── Django local ──────────────────────────────────────────────────────────────
install:
	pip install -r requirements-dev.txt
	python manage.py tailwind install

dev:
	python manage.py migrate
	python manage.py tailwind start &
	python manage.py runserver 0.0.0.0:8020

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

seed-dev:
	python manage.py seed_dev_workdays --clear

collect:
	python manage.py collectstatic --noinput

# ── Agente Windows ───────────────────────────────────────────────────────────
agent-install:
	pip install -r agent/requirements-agent.txt

agent-logo:
	python -c "from PIL import Image; img = Image.open('static/img/logo RL.png').convert('RGBA'); bg = Image.new('RGB', img.size, (255, 255, 255)); bg.paste(img, mask=img.split()[3]); bg.save('agent/logo.bmp')"

agent-build: agent-logo
	cd agent && pyinstaller redline_agent.spec
	"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" agent\installer.iss

# ── Producción ────────────────────────────────────────────────────────────────
deploy:
	bash deploy.sh

nginx:
	bash nginx-deploy.sh

logs:
	docker compose logs -f django

down:
	docker compose down

.PHONY: dev-up dev-down dev-logs n8n-export n8n-import install dev tailwind migrate migrations shell superuser collect deploy nginx logs down agent-install agent-logo agent-build
