# Desplegar en Railway

El servidor en la nube y **MySQL en la nube**, de modo que SmartPSS Lite escriba
directo ahi desde la oficina. Una sola base, sin instalar nada localmente.

```
[Reloj Dahua] → [SmartPSS Lite]  (en la oficina)
                       │
                       │ escribe por internet al endpoint publico de Railway
                       ▼
              ┌─────────────────────────────┐
              │  RAILWAY                    │
              │                             │
              │  MySQL  ← SmartPSS escribe  │
              │    ▲                        │
              │    │ lee                    │
              │  Django (web, API, calculo) │
              └─────────────────────────────┘
                       │
                       ▼
          Supervisores y RRHH desde cualquier lado
```

---

## Antes de decidir, tres cosas que hay que saber

**1. MySQL, no PostgreSQL.** Railway ofrece los dos y sugiere PostgreSQL. Aqui hace
falta **MySQL**, porque SmartPSS Lite solo sabe escribir en MySQL y la gracia de
este montaje es que ambos compartan una sola base.

**2. Si se cae el internet de la oficina, SmartPSS no puede escribir.** Las marcas
quedan en el reloj y en SmartPSS, pero no llegan a la base hasta que vuelva la
conexion. Con la base local esto no pasaba. Si los cortes son frecuentes, conviene
el montaje local con el agente, que si aguanta caidas sin perder marcas.

**3. La base queda expuesta a internet.** Railway publica un endpoint TCP publico
para que SmartPSS lo alcance, y cualquiera con las credenciales puede conectarse.
Use una clave larga y generada al azar, y no la reutilice.

Tambien: los datos de asistencia son informacion personal de los empleados y van a
estar fuera de la empresa. Es una decision del negocio, no tecnica.

---

## Paso 1. Subir el codigo a GitHub

```powershell
git add .
git commit -m "Sistema de asistencia"
git push -u origin main
```

---

## Paso 2. Crear el proyecto y la base

1. En <https://railway.app>, **New Project → Deploy from GitHub repo** y elija
   `MarcasReloj`.
2. En el servicio que se crea: **Settings → Root Directory** = `servidor`.
   El proyecto Django no esta en la raiz del repositorio.
3. **New → Database → Add MySQL.** Insista en MySQL; el PostgreSQL que sugiere
   por defecto no sirve para SmartPSS.

---

## Paso 3. Variables del servicio web

En el servicio de Django, **Variables**:

| Variable | Valor |
|---|---|
| `DATABASE_URL` | `${{MySQL.MYSQL_URL}}` (referencia al servicio MySQL) |
| `DJANGO_SECRET_KEY` | una clave larga al azar (ver abajo) |
| `DJANGO_DEBUG` | `false` |
| `DJANGO_HTTPS` | `true` |

Para generar la clave:

```powershell
.venv\Scripts\python.exe -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

`DJANGO_ALLOWED_HOSTS` no hace falta: el dominio de Railway se agrega solo desde
`RAILWAY_PUBLIC_DOMAIN`.

`DJANGO_HTTPS=true` activa cookies seguras y HSTS, que ahi si corresponden porque
Railway termina TLS.

---

## Paso 4. Exponer MySQL para que SmartPSS lo alcance

En el servicio **MySQL → Settings → Networking → Public Networking**, genere el
dominio TCP publico. Queda algo como:

```
centerbeam.proxy.rlwy.net:41234
```

Ese host y ese puerto son los que van en SmartPSS. El `MYSQL_URL` interno
(`mysql.railway.internal`) **no sirve** para SmartPSS: solo funciona dentro de
Railway.

En la pestana **Variables** del servicio MySQL estan `MYSQLUSER`, `MYSQLPASSWORD`
y `MYSQLDATABASE`.

---

## Paso 5. Llenar la pantalla de SmartPSS

**SmartPSS Lite → Config → Base de Datos de Asistencia (Externa)**:

| Campo de SmartPSS | De donde sale |
|---|---|
| IP Servidor | El host del dominio publico, sin el puerto |
| Puerto servidor | El puerto del dominio publico (no es 3306) |
| Nombre de la base de datos | `MYSQLDATABASE`, normalmente `railway` |
| Nombre Usuario | `MYSQLUSER`, normalmente `root` |
| Contrasena usuario | `MYSQLPASSWORD` |

Luego:

1. **Prueba de conexion.**
2. **Encienda el interruptor "Habilitar Base de Datos".** Sin esto no escribe nada.
3. Guarde y **marque una vez en el reloj**: SmartPSS crea la tabla al escribir la
   primera marca, no al guardar.

---

## Paso 6. Preparar los datos

Desde la consola de Railway (**servicio Django → pestana de terminal**) o con la
CLI (`railway run`):

```bash
python manage.py createsuperuser
python manage.py crear_sucursal --nombre "Oficina Central" --codigo-agente oficina-central
python manage.py leer_smartpss --explorar
```

El ultimo encuentra la tabla que creo SmartPSS. Copie el `SMARTPSS_TABLA=...` que
imprime a las Variables del servicio.

Luego cree los horarios y los feriados en la interfaz web, y cargue los empleados
con `importar_empleados`. El detalle esta en
[conectar-smartpss.md](conectar-smartpss.md), pasos 6 a 9.

---

## Paso 7. Las dos tareas programadas

Railway las corre como **Cron Schedule** en un servicio aparte, apuntando al mismo
repositorio y con las mismas variables:

| Que | Comando | Cuando |
|---|---|---|
| Importar las marcas | `python manage.py leer_smartpss` | `* * * * *` (cada minuto) |
| Recalcular el dia anterior | `python manage.py recalcular --ayer` | `30 6 * * *` |

La segunda va a las **06:30 UTC**, que son las 00:30 en Costa Rica. Railway
programa en UTC.

La tarea de recalculo no es opcional: un empleado sin marcas no dispara ningun
evento, asi que sin ella nunca apareceria como `AUSENTE`.

---

## Paso 8. Comprobar

```
https://su-dominio.up.railway.app/api/v1/salud
```

Debe responder `{"estado": "ok", ...}`. Es la misma ruta que Railway usa como
healthcheck.

---

## Respaldos

Railway respalda su MySQL, pero conviene tener copia propia:

```powershell
mysqldump -h centerbeam.proxy.rlwy.net -P 41234 -u root -p railway > respaldo.sql
```

Una tarea programada de Windows que lo corra a diario, con 30 dias de retencion y
la copia fuera de esa PC.

---

## Costo

Railway cobra por uso, con un minimo mensual. El servicio web y MySQL de este
tamano caen en el tramo bajo, pero **no es gratis**. Revise el plan antes de
comprometerse.

---

## Volver al montaje local

Si en algun momento conviene traerse todo a la oficina:

1. `python manage.py dumpdata > datos.json` desde Railway.
2. Montar MySQL local, poner el `DATABASE_URL` local en `servidor/.env`.
3. `manage.py migrate` y `manage.py loaddata datos.json`.
4. Repuntar SmartPSS a la base local.

El codigo no cambia.
