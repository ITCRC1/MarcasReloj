# Sistema de Asistencia

Lee las marcas del reloj Dahua que SmartPSS Lite guarda en MySQL, las convierte en tiempo
laborado por empleado y por dia segun su horario, permite correcciones controladas con
bitacora y entrega los resultados a planillas por API, vistas SQL o archivos.

**El sistema entrega tiempo. Planillas lo convierte en dinero.**

| Documento | Que contiene |
|---|---|
| [docs/especificacion-sistema-asistencia.md](docs/especificacion-sistema-asistencia.md) | La especificacion completa |
| [docs/conectar-smartpss.md](docs/conectar-smartpss.md) | **Pasar de los datos de demostracion a los reales** |
| [docs/decisiones-abiertas.md](docs/decisiones-abiertas.md) | Lo que falta confirmar con RRHH |
| [docs/operacion.md](docs/operacion.md) | Instalar, levantar, respaldar, cerrar una quincena |

---

## Arrancar en cinco minutos

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r servidor\requirements.txt

cd servidor
..\.venv\Scripts\python.exe manage.py migrate
..\.venv\Scripts\python.exe manage.py crear_roles
..\.venv\Scripts\python.exe manage.py datos_demo
..\.venv\Scripts\python.exe manage.py runserver
```

Abrir <http://127.0.0.1:8000>. Usuarios de prueba, todos con la clave `asistencia2026`:

| Usuario | Rol | Que puede hacer |
|---|---|---|
| `admin` | Administrador | Todo, mas el admin de Django y las claves de API |
| `rrhh` | RRHH | Aprobar, anular, aceptar advertencias, cerrar periodos |
| `supervisor` | Supervisor | Solo su departamento; sus marcas manuales quedan pendientes |
| `consulta` | Consulta | Solo lectura |

`datos_demo` imprime al terminar las claves de API del agente y de planillas.

**Los datos de demostracion son ficticios.** Para conectar con el reloj de verdad,
siga [docs/conectar-smartpss.md](docs/conectar-smartpss.md).

### Comandos

| Comando | Para que |
|---|---|
| `manage.py leer_smartpss --explorar` | Encuentra la tabla que creo SmartPSS en esta base |
| `manage.py leer_smartpss` | Importa las marcas nuevas y calcula los dias |
| `manage.py leer_smartpss --continuo` | Lo mismo, cada minuto, para dejarlo como servicio |
| `manage.py empezar_de_cero` | Borra los datos de operacion, conserva los usuarios |
| `manage.py crear_sucursal` | Crea una sucursal y muestra su clave de API |
| `manage.py importar_empleados` | Carga la lista real desde un CSV, con `--simular` |
| `manage.py recalcular` | Recalculo masivo o de ayer (`--ayer`, para la tarea diaria) |
| `manage.py crear_roles` | Crea los cuatro grupos de la seccion 10 |
| `manage.py datos_demo` | Carga datos ficticios para ver el sistema funcionando |

---

## Que hay construido

| Fase | Entregables | Estado |
|---|---|---|
| 1. Marcas | Agente, ingesta, modelos de marcas y empleados, mapeo de `PersonID` | listo |
| 2. Motor | Horarios, feriados, justificaciones, `calculo.py`, recalculo, tarea diaria | listo |
| 3. Correcciones | Pantalla del dia, marcas manuales, anulacion, aprobaciones, bitacora, roles | listo |
| 4. Periodos y reportes | Periodos, validaciones de cierre, ajustes, Excel y PDF | listo |
| 5. API | Endpoints de la seccion 13, claves de API, vistas SQL y CSV | listo |
| 6. Produccion | Servicios de Windows, respaldos, documentacion de operacion | documentado, sin instalar |

Las seis fases de la especificacion estan construidas. Lo unico que queda por hacer
es instalar los servicios de Windows en la maquina definitiva, que es trabajo de
maquina y no de codigo: esta paso a paso en [docs/operacion.md](docs/operacion.md).

---

## Estructura

```
MarcasReloj/
├── docs/                    especificacion, decisiones abiertas, operacion
├── agente/                  corre en la PC de SmartPSS
│   ├── agente.py            ciclo principal
│   ├── lector_smartpss.py   consulta a MySQL, solo SELECT
│   ├── cliente_api.py       envio con reintentos
│   ├── estado.py            estado.json, escritura atomica
│   └── test_agente.py
└── servidor/
    ├── config/              settings, urls, wsgi
    ├── apps/
    │   ├── core/            Sucursal, Departamento, Empleado, roles, tablero
    │   ├── horarios/        Horario, BloqueHorario, Asignacion, Feriado, Justificacion
    │   ├── marcas/          MarcaReloj, MarcaManual, ingesta, pantalla del dia
    │   ├── motor/           calculo.py (puro), servicio de recalculo, ResultadoDiario
    │   ├── periodos/        Periodo, Ajuste, validaciones de cierre
    │   ├── reportes/        pantalla, Excel, PDF, CSV
    │   └── api/             Django Ninja, ClienteAPI
    ├── templates/           Django + Bootstrap 5 + HTMX
    ├── static/              Bootstrap y HTMX locales, sin CDN
    └── tests/
```

---

## El motor de calculo

`servidor/apps/motor/calculo.py` es un modulo puro: no importa Django, no hace I/O y
no toca la base de datos. Recibe dataclasses y devuelve dataclasses. Implementa la
seccion 7 de la especificacion, incluidos los 18 casos de referencia de la 7.7.

El puente con la base vive aparte, en `apps/motor/servicio.py`, que arma el contexto
del dia, llama al motor y guarda el `ResultadoDiario`.

---

## Pruebas

```powershell
cd servidor
..\.venv\Scripts\python.exe -m pytest      # 120 pruebas
cd ..\agente
..\.venv\Scripts\python.exe -m pytest      # 8 pruebas
```

Cubren los 18 casos de referencia, las invariantes sobre miles de combinaciones de
marcas generadas, la ingesta y sus duplicados, el recalculo y los periodos cerrados,
el flujo completo de correccion con dos usuarios, los permisos de cada rol, la API,
las vistas SQL contrastadas contra el servicio de Python, todas las pantallas y las
exportaciones a Excel, CSV y PDF.

Con cobertura:

```powershell
cd servidor
..\.venv\Scripts\python.exe -m coverage run -m pytest
..\.venv\Scripts\python.exe -m coverage report -m --include="apps/*"
```

---

## API para planillas

Documentacion interactiva en <http://127.0.0.1:8000/api/docs>.
Autenticacion con el encabezado `X-API-Key`.

| Metodo | Ruta | Uso |
|---|---|---|
| GET | `/api/v1/salud` | Verificacion de estado, sin autenticacion |
| GET | `/api/v1/empleados` | Empleados con su codigo de planilla |
| GET | `/api/v1/periodos` | Periodos y su estado |
| GET | `/api/v1/periodos/{id}/resumen` | Totales por empleado (el principal) |
| GET | `/api/v1/periodos/{id}/detalle?empleado=E-0042` | Resultado diario |
| GET | `/api/v1/periodos/{id}/ajustes` | Ajustes del periodo |
| POST | `/api/v1/ingesta/marcas` | Uso exclusivo de los agentes |

Las claves de los agentes y las de planillas son distintas y no se cruzan: un agente
solo escribe en la ingesta, un cliente solo lee.

Reglas para quien consume: procesar solo periodos `cerrado`, identificar empleados
por `codigo_empleado` y nunca por nombre, y tratar todo valor de tiempo como minutos
enteros.

### Si planillas prefiere leer la base directamente

Hay dos vistas SQL, creadas por migracion, que entregan lo mismo que la API:

```sql
SELECT * FROM v_resumen_periodo WHERE periodo_id = 1;
SELECT * FROM v_detalle_diario  WHERE codigo_empleado = 'E-0042';
```

Se consultan con un usuario de solo lectura. Una prueba las contrasta contra el
servicio de Python para que las dos vias no se separen con el tiempo.

---

## Reglas para quien implemente

Estan completas en el anexo de la especificacion. Las que mas se olvidan:

1. Nunca escribir, modificar ni borrar datos en la base de SmartPSS.
2. `apps/motor/calculo.py` no importa Django ni hace I/O.
3. El tiempo se maneja en minutos enteros. Nunca horas decimales ni `float`.
4. Todos los `datetime` son *aware*; se convierten a `America/Costa_Rica` solo para
   agrupar por fecha y para mostrar.
5. Nada se borra: se anula, se rechaza o se cierra, y queda en bitacora.
6. Todo cambio que afecte un dia dispara `recalcular(empleado, fecha)`, excepto en
   periodos cerrados.
7. Ante una regla ambigua no se inventa: se anota en
   [docs/decisiones-abiertas.md](docs/decisiones-abiertas.md) y se consulta.
