# Conectar con SmartPSS

Pasar de los datos de demostracion a los reales.

Los datos que cargo `datos_demo` (Maria Rodriguez, Jose Perez y compania) son
ficticios y se borran en el paso 3.

---

## La idea

SmartPSS Lite sabe escribir sus marcas en una base MySQL externa. Se le dan cinco
datos —IP, puerto, base, usuario y clave— y el escribe ahi solo.

**Si esa base es la misma del sistema de asistencia, no hay nada que transportar.**
SmartPSS deja las marcas en una tabla suya, y el sistema las lee de ahi con un
comando. Sin agente, sin HTTP, sin una segunda base.

```
[Reloj Dahua] → [SmartPSS Lite]
                       │ escribe con las credenciales que usted le da
                       ▼
              ┌────────────────────────────────────┐
              │  SU BASE MySQL                     │
              │                                    │
              │  tabla_asistencia   ← SmartPSS     │
              │  marcas_marcareloj  ← el sistema   │
              │  core_empleado      ← el sistema   │
              │  ...                               │
              └────────────────────────────────────┘
                       │ manage.py leer_smartpss
                       ▼
            [Calculo, pantallas, reportes, API]
```

El sistema **nunca escribe** en la tabla de SmartPSS. Solo la lee.

### Cuando si hace falta el agente

Solo si SmartPSS no alcanza la base del sistema: por ejemplo, si el servidor vive
en Railway y la PC de SmartPSS no puede escribirle directo. En ese caso el agente
corre en la PC de SmartPSS, lee la base local y envia por HTTPS. Esta documentado
en [operacion.md](operacion.md), seccion 3. **Si ambas cosas hablan con la misma
base, no lo use: es una pieza de mas que puede fallar.**

---

## Lo que ya sabemos de la tabla

SmartPSS escribe 12 columnas, y el sistema las lee todas:

| # | Campo | Tipo | Uso en el sistema |
|---|---|---|---|
| 1 | `PersonID` | varchar(30) | Identifica a la persona. Se mapea al codigo de planilla |
| 2 | `PersonName` | varchar(36) | Referencia. Ayuda a mapear marcas sin empleado |
| 3 | `PerSonCardNo` | varchar(20) | Referencia |
| 4 | `AttendanceDateTime` | bigint | **Se ignora.** Es la hora local disfrazada de epoch |
| 5 | `AttendanceState` | int | Se guarda. No participa en el calculo |
| 6 | `AttendanceMethod` | int | Se guarda y se muestra (tarjeta, huella, rostro) |
| 7 | `DeviceIPAddress` | varchar(20) | Parte de la llave unica. Puede venir vacio |
| 8 | `DeviceName` | varchar(50) | Se muestra en el detalle |
| 9 | `SnapshotsPath` | varchar(200) | Se guarda. La imagen no se descarga |
| 10 | `Handler` | varchar(50) | Si trae valor, la marca fue tocada dentro de SmartPSS |
| 11 | `AttendanceUtcTime` | bigint | **La fuente de verdad de la hora** |
| 12 | `Remarks` | varchar(256) | Se guarda y se muestra |

Lo que **no** sabemos es el **nombre de la tabla**: lo pone SmartPSS. El paso 4 lo
averigua solo.

---

## Paso 1. Apuntar el sistema a su base

En `servidor/.env`:

```ini
DATABASE_URL=mysql://usuario:clave@servidor:3306/nombre_de_su_base
```

Con `mysqlclient` instalado (ya viene en `requirements.txt`), cree las tablas:

```powershell
cd servidor
..\.venv\Scripts\python.exe manage.py migrate
..\.venv\Scripts\python.exe manage.py crear_roles
..\.venv\Scripts\python.exe manage.py createsuperuser
```

Si la base esta en otro servidor, el usuario de MySQL tiene que poder conectarse
desde esta maquina (`'usuario'@'%'` o `'usuario'@'la-ip'`, no solo `@'localhost'`).

---

## Paso 2. Decirle a SmartPSS que escriba ahi

En SmartPSS Lite: **Config → Base de Datos de Asistencia (Externa)**.

Los cinco campos son los mismos datos del `DATABASE_URL` del paso anterior:

| Campo de SmartPSS | Que poner |
|---|---|
| IP Servidor | La IP o el nombre del servidor MySQL |
| Puerto servidor | `3306` |
| Nombre de la base de datos | Su base |
| Nombre Usuario | Un usuario con permiso de escritura ahi |
| Contraseña usuario | Su clave |

Luego:

1. **Prueba de conexion**, y espere que confirme.
2. **Encienda el interruptor "Habilitar Base de Datos".** Es el paso que mas se
   olvida: con todo lleno, la prueba en verde y el interruptor apagado, SmartPSS
   no escribe nada y todo lo demas parece roto sin motivo.
3. Guarde.
4. **Marque una vez en el reloj.** SmartPSS crea la tabla cuando escribe la primera
   marca, no al guardar la configuracion. Si nadie marca, no hay tabla.

### Si SmartPSS no conecta

- Que el usuario de MySQL acepte conexiones desde la IP de la PC de SmartPSS.
- Que use el metodo de autenticacion viejo, que es el que entiende SmartPSS Lite:
  `ALTER USER 'usuario'@'%' IDENTIFIED WITH mysql_native_password BY 'clave';`
- Que el firewall no bloquee el 3306 entre las dos maquinas.

---

## Paso 3. Vaciar los datos de demostracion

```powershell
..\.venv\Scripts\python.exe manage.py empezar_de_cero
```

Pide escribir `BORRAR TODO`. Borra marcas, resultados, periodos, empleados,
horarios y feriados. **No borra usuarios ni grupos**: sus cuentas se conservan.
**Tampoco toca la tabla de SmartPSS.**

---

## Paso 4. Encontrar la tabla

```powershell
..\.venv\Scripts\python.exe manage.py leer_smartpss --explorar
```

Busca en su base las tablas que tengan la columna `AttendanceUtcTime`, y de cada
una muestra cuantas filas tiene, desde cuando hay marcas, las ultimas con nombre y
hora en hora de Costa Rica, y la linea exacta para el `.env`:

```
Tabla: tabla_asistencia
Filas: 10
Marcas del 2026-09-11 07:58 al 2026-09-11 18:45 (hora de Costa Rica)

Ultimas marcas:
  PersonID=1025    Jose Perez               2026-09-11 18:45:00  dispositivo=Reloj Entrada
  PersonID=1024    Maria Rodriguez          2026-09-11 17:04:00  dispositivo=Reloj Entrada

Comprobacion de zona horaria:
  AttendanceUtcTime  = 1789087500000 (ms)
  AttendanceDateTime = 1789065900000 (ms)
  Diferencia 6 h: correcto, el reloj esta en UTC-6

Para servidor/.env:
  SMARTPSS_TABLA=tabla_asistencia
```

Tambien hace la comprobacion de zona horaria de la seccion 21 de la
especificacion, y avisa si la diferencia no son 6 horas.

**Si no encuentra ninguna**, SmartPSS todavia no ha escrito: vuelva al paso 2 y
revise el interruptor y que alguien haya marcado.

Copie `SMARTPSS_TABLA` a `servidor/.env`.

---

## Paso 5. Crear la sucursal

```powershell
..\.venv\Scripts\python.exe manage.py crear_sucursal --nombre "Oficina Central" --codigo-agente oficina-central
```

Imprime una clave de API. Con lectura directa **no la necesita** (es para el
agente), pero no estorba tenerla.

---

## Paso 6. Crear los horarios y cargar los feriados

En **Horarios → Nuevo horario**. Por cada uno: nombre, tipo de jornada, los
parametros de calculo, y los bloques dia por dia. Un dia sin bloques es libre; un
dia con dos bloques es horario partido.

Luego **Horarios → Feriados**, con los del ano segun el calendario oficial. No se
calculan solos porque algunos se trasladan por ley.

---

## Paso 7. Cargar los empleados

Un CSV guardado desde Excel como **CSV UTF-8 (delimitado por comas)**:

```csv
codigo_planilla,nombre,identificacion,person_id,departamento,fecha_ingreso,horario
E-0001,Ana Lucia Vargas,1-0888-0777,1024,Administracion,2024-03-01,Administrativo partido
E-0002,Roberto Jimenez,2-0555-0444,,Administracion,2023-11-15,Administrativo partido
```

Revise primero sin escribir nada:

```powershell
..\.venv\Scripts\python.exe manage.py importar_empleados empleados.csv --simular
```

Reporta cada problema con su numero de fila: codigos repetidos, PersonID que ya es
de otro, fechas mal escritas, horarios que no existen. Cuando no salga ninguno,
quite `--simular`.

Puede dejar `person_id` vacio: el paso 9 lo resuelve.

### De donde salen los PersonID

De **Gestion de Personas** en SmartPSS Lite. O deje que el sistema se los diga: el
`--explorar` del paso 4 ya se los mostro junto al nombre que trae el reloj.

---

## Paso 8. Importar las marcas

Una pasada:

```powershell
..\.venv\Scripts\python.exe manage.py leer_smartpss
```

```
08:56:46  leidas 10, nuevas 10, duplicadas 0, sin empleado 2
```

Correrlo dos veces no duplica nada: la ingesta descarta lo que ya tiene.

La primera vez trae todo lo que haya en la tabla. Si quiere empezar desde una fecha
concreta, ponga en `servidor/.env`:

```ini
SMARTPSS_FECHA_INICIO=2026-09-01
```

De ahi en adelante el comando arranca solo desde la ultima marca importada, menos
48 horas de relectura por si SmartPSS escribio marcas con horas pasadas.

### Dejarlo corriendo

Como tarea programada de Windows, cada minuto:

```powershell
$accion = New-ScheduledTaskAction `
  -Execute "C:\ruta\MarcasReloj\.venv\Scripts\python.exe" `
  -Argument "manage.py leer_smartpss" `
  -WorkingDirectory "C:\ruta\MarcasReloj\servidor"
$disparador = New-ScheduledTaskTrigger -Once -At (Get-Date) `
  -RepetitionInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "AsistenciaLeerSmartPSS" `
  -Action $accion -Trigger $disparador -RunLevel Highest
```

O como servicio con NSSM, usando `--continuo`:

```powershell
nssm install AsistenciaLector "C:\ruta\MarcasReloj\.venv\Scripts\python.exe"
nssm set AsistenciaLector AppParameters "manage.py leer_smartpss --continuo"
nssm set AsistenciaLector AppDirectory "C:\ruta\MarcasReloj\servidor"
nssm set AsistenciaLector Start SERVICE_AUTO_START
nssm set AsistenciaLector AppExit Default Restart
nssm start AsistenciaLector
```

---

## Paso 9. Mapear lo que quedo suelto

El tablero y **Pendientes** muestran las marcas sin dueno con su `PersonID` y el
nombre que trae el reloj. Entre a la ficha de cada empleado sin mapear y asignele
el suyo: el sistema adopta todas sus marcas anteriores y recalcula esos dias solo.

El tablero tambien avisa en rojo si hay empleados activos sin `PersonID`, porque
esos acumulan ausencias en silencio.

---

## Paso 10. La tarea diaria de recalculo

Obligatoria. Un empleado sin marcas no dispara ningun evento, asi que sin esta
tarea nunca apareceria como `AUSENTE`. Esta en [operacion.md](operacion.md),
seccion 4.

---

## Paso 11. El primer periodo

**Periodos → Crear**, con las fechas de su primera quincena real. El ciclo de cada
quincena esta en [operacion.md](operacion.md), seccion 8.

---

## Antes de pagar con esto

Corra una quincena en paralelo con el metodo que usa hoy y compare. Es la unica
forma honesta de confirmar que los parametros de calculo son los que RRHH tiene en
la cabeza. Las doce preguntas abiertas estan en
[decisiones-abiertas.md](decisiones-abiertas.md).
