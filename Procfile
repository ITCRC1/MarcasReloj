web: cd servidor && python manage.py migrate --noinput && python manage.py crear_admin && gunicorn config.wsgi --bind 0.0.0.0:$PORT --workers 2 --timeout 120
