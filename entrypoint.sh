#!/bin/sh

echo 'Esperando a que PostgreSQL esté disponible...'
until python -c "
import psycopg2, os, sys
try:
    psycopg2.connect(
        dbname=os.environ['POSTGRES_DB'],
        user=os.environ['POSTGRES_USER'],
        password=os.environ['POSTGRES_PASSWORD'],
        host=os.environ.get('POSTGRES_HOST', 'postgres'),
        port=os.environ.get('POSTGRES_PORT', '5432'),
    )
    sys.exit(0)
except Exception:
    sys.exit(1)
"; do
  echo '  PostgreSQL no disponible, reintentando en 2s...'
  sleep 2
done
echo 'PostgreSQL está listo.'

echo 'Recopilando archivos estáticos...'
python manage.py collectstatic --noinput
chmod -R o+rX /app/staticfiles

echo 'Ejecutando migraciones...'
python manage.py migrate

echo 'Iniciando Gunicorn...'
exec gunicorn core.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 3 \
    --access-logfile - \
    --error-logfile -
