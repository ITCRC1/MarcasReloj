# Operacion

Como levantar, mantener y respaldar el sistema. Corresponde a la seccion 18 de la
especificacion.

---

## 1. Puesta en marcha en una maquina nueva

```powershell
# Desde la raiz del repositorio
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r servidor\requirements.txt

cd servidor
Copy-Item .env.example .env      # y complete DJANGO_SECRET_KEY
..\.venv\Scripts\python.exe manage.py migrate
..\.venv\Scripts\python.exe manage.py crear_roles
..\.venv\Scripts\python.exe manage.py createsuperuser
..\.venv\Scripts\python.exe manage.py collectstatic --noinput
```

Para generar una `DJANGO_SECRET_KEY`:

```powershell
..\.venv\Scripts\python.exe -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### Datos de prueba

```powershell
..\.venv\Scripts\python.exe manage.py datos_demo
```

Crea sucursal, usuarios de los cuatro roles (clave `asistencia2026`), horarios,
feriados, seis empleados, marcas de varias semanas y tres periodos, uno cerrado.
Imprime las claves de API al terminar. **No usar en produccion.**

Para empezar de cero: `manage.py datos_demo --borrar`.

---

## 2. Levantar el servidor

Desarrollo:

```powershell
cd servidor
..\.venv\Scripts\python.exe manage.py runserver
```

Produccion local en Windows, con waitress:

```powershell
cd servidor
..\.venv\Scripts\waitress-serve.exe --listen=0.0.0.0:8000 config.wsgi:application
```

Se accede desde la red en `http://IP-DEL-SERVIDOR:8000`. Agregue esa IP a
`DJANGO_ALLOWED_HOSTS` en `servidor/.env`.

### Como servicio de Windows, con NSSM

```powershell
nssm install AsistenciaServidor "C:\ruta\MarcasReloj\.venv\Scripts\waitress-serve.exe"
nssm set AsistenciaServidor AppParameters "--listen=0.0.0.0:8000 config.wsgi:application"
nssm set AsistenciaServidor AppDirectory "C:\ruta\MarcasReloj\servidor"
nssm set AsistenciaServidor Start SERVICE_AUTO_START
nssm set AsistenciaServidor AppExit Default Restart
nssm start AsistenciaServidor
```

---

## 3. El agente

Corre en la PC donde esta SmartPSS Lite.

```powershell
cd agente
..\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env      # y complete los datos de MySQL y la API_KEY
..\.venv\Scripts\python.exe agente.py --probar
```

`--probar` revisa las tres cosas que pueden fallar y las reporta todas: que el
servidor responda, que la base de SmartPSS sea legible (y que las unidades de
`AttendanceUtcTime` sean las esperadas) y que la clave del agente sirva.

### La clave del agente

Se genera desde el admin de Django: **Sucursales → seleccionar → Generar clave de
API nueva**. Se muestra una sola vez; el sistema guarda solo su hash.

### Usuario de solo lectura en MySQL

```sql
CREATE USER 'agente_asistencia'@'localhost' IDENTIFIED BY 'una-clave-larga';
GRANT SELECT ON base_smartpss.tabla_asistencia TO 'agente_asistencia'@'localhost';
```

Nunca se le da otro permiso. El sistema jamas escribe en la base de SmartPSS.

### Como servicio de Windows

```powershell
nssm install AsistenciaAgente "C:\ruta\MarcasReloj\.venv\Scripts\python.exe"
nssm set AsistenciaAgente AppParameters "agente.py"
nssm set AsistenciaAgente AppDirectory "C:\ruta\MarcasReloj\agente"
nssm set AsistenciaAgente Start SERVICE_AUTO_START
nssm set AsistenciaAgente AppExit Default Restart
nssm start AsistenciaAgente
```

El agente escribe en `agente/agente.log`, con rotacion de 5 archivos de 2 MB.

---

## 4. Tarea diaria de recalculo

Es obligatoria. Un empleado sin marcas no dispara ningun evento, asi que sin esta
tarea nunca apareceria como `AUSENTE`.

```powershell
$accion = New-ScheduledTaskAction `
  -Execute "C:\ruta\MarcasReloj\.venv\Scripts\python.exe" `
  -Argument "manage.py recalcular --ayer" `
  -WorkingDirectory "C:\ruta\MarcasReloj\servidor"
$disparador = New-ScheduledTaskTrigger -Daily -At 00:30
Register-ScheduledTask -TaskName "AsistenciaRecalculoDiario" `
  -Action $accion -Trigger $disparador -RunLevel Highest
```

Recalculos manuales:

```powershell
manage.py recalcular --desde 2026-09-01 --hasta 2026-09-15
manage.py recalcular --desde 2026-09-01 --hasta 2026-09-15 --empleado E-0042
```

Los dias que pertenecen a un periodo cerrado nunca se recalculan, aunque el comando
los incluya en el rango.

---

## 5. Respaldos

```powershell
$fecha = Get-Date -Format "yyyy-MM-dd"
mysqldump -u respaldo -p asistencia   | Out-File "D:\respaldos\asistencia-$fecha.sql"  -Encoding utf8
mysqldump -u respaldo -p base_smartpss | Out-File "D:\respaldos\smartpss-$fecha.sql"   -Encoding utf8
Get-ChildItem D:\respaldos\*.sql | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } | Remove-Item
```

Con SQLite basta copiar `servidor/asistencia.sqlite3` con el servicio detenido.

**La copia debe salir de esa PC.** Un respaldo en el mismo disco no es un respaldo.

---

## 6. La PC de SmartPSS

- Suspension desactivada (`powercfg /change standby-timeout-ac 0`).
- SmartPSS Lite con inicio automatico.
- De preferencia conectada a una UPS.
- Acceso remoto opcional con Tailscale, sin abrir puertos en el router.

---

## 7. Que revisar cada dia

El tablero lo muestra todo de un vistazo:

1. **Agentes en rojo.** Si uno no sincroniza hace mas de 15 minutos, faltan marcas.
2. **Dias inconsistentes.** Alguien olvido marcar; hay que corregirlo antes del cierre.
3. **Marcas manuales por aprobar.** Las creadas por supervisores esperan a RRHH.
4. **Marcas sin empleado asignado.** Un `PersonID` que nadie reclamo.
5. **Empleados activos sin PersonID.** Acumulan ausencias en silencio.
6. **Marcas recibidas despues de un cierre.** Esos dias ya se pagaron; se corrigen
   con un ajuste en el periodo abierto.

---

## 8. Cerrar una quincena

1. Periodos → abrir el periodo → **Pasar a revision**. Desde ahi los supervisores
   ya no pueden crear marcas manuales.
2. Resolver lo que aparezca en **Pendientes**.
3. **Recalcular y validar**. Muestra las cinco condiciones de cierre.
4. **Cerrar periodo**. Pide confirmacion, porque no se reabre.
5. Entregar a planillas: `GET /api/v1/periodos/{id}/resumen`, o el Excel o el CSV
   del resumen.

Lo que aparezca despues del cierre se registra como **Ajuste** en el periodo abierto
siguiente, con su fecha original y su motivo.

---

## 9. Migrar a Railway

1. Desplegar `servidor/` desde GitHub. Railway inyecta `DATABASE_URL` de PostgreSQL.
2. Comando de arranque: `gunicorn config.wsgi --bind 0.0.0.0:$PORT`.
3. Usar `requirements-railway.txt`, que agrega PostgreSQL y gunicorn sobre el
   `requirements.txt` de siempre. Gunicorn no esta en el principal a proposito:
   en Windows instala pero no arranca, porque necesita `fcntl`, que es de Unix.
4. Poner `DJANGO_HTTPS=true` en las variables de entorno: Railway termina TLS,
   asi que ahi si corresponden las cookies seguras y HSTS.
5. Las migraciones se corren en cada despliegue.
6. La tarea diaria se configura como tarea programada del servicio.
7. En el agente solo cambian `API_URL` y `API_KEY`.
8. Los datos se migran con `manage.py dumpdata` y `manage.py loaddata`.
