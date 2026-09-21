# API para el sistema de planillas

API de **solo lectura** en JSON. Entrega la misma información que el reporte de
asistencia: se calcula con el mismo código, así que la API y el Excel nunca dan
horas distintas para el mismo rango.

Base: `https://marcasreloj.up.railway.app/api/v1/`

## Autenticación

Todas las consultas llevan la clave en el encabezado:

```
Authorization: Bearer <API_TOKEN>
```

La clave se define en Railway, en la variable `API_TOKEN` del servicio web. Si la
variable no existe, la API responde `503` y no se puede consultar.

Para generar una clave en PowerShell:

```powershell
$b = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); [Convert]::ToBase64String($b)
```

## Parámetros comunes

| Parámetro | Obligatorio | Ejemplo | Nota |
|---|---|---|---|
| `desde` | sí | `2026-09-01` | AAAA-MM-DD, incluido |
| `hasta` | sí | `2026-09-15` | AAAA-MM-DD, incluido. Máximo 62 días por consulta |
| `person_id` | no | `14` | PersonID de SmartPSS |
| `codigo` | no | `E-0042` | Código de planilla (cuando el empleado está creado) |

## Cómo leer los tiempos

- Toda cantidad de tiempo viene doble: `{"minutos": 736, "texto": "12:16"}`.
  Use `minutos` para calcular; `texto` es solo para mostrar.
- Las horas de marca vienen en hora de Costa Rica (`"05:45"`) y completas en
  ISO 8601 con zona (`"2026-09-15T05:45:00-06:00"`).
- El reloj no distingue entrada de salida. El `tipo` sale del orden: 1ª entrada,
  2ª salida, 3ª entrada, 4ª salida.
- `trabajado` suma solo tramos completos. Un día con `"completo": false` tiene
  una entrada sin salida y **no debe pagarse sin revisar**.

## `GET /horas` — una fila por empleado y por día

La consulta más directa para cargar planilla: fecha y total, sin nada anidado.

```
GET /api/v1/horas?desde=2026-09-15&hasta=2026-09-20
```

```json
{
  "desde": "2026-09-15",
  "hasta": "2026-09-20",
  "filas": [
    {
      "codigo_planilla": "14",
      "person_id": "14",
      "nombre": "BENJAMIN QUIROS MORA",
      "fecha": "2026-09-15",
      "minutos": 736,
      "horas": "12:16",
      "completo": true,
      "observacion": null
    },
    {
      "codigo_planilla": "16",
      "person_id": "16",
      "nombre": "BRAYAN JORGE SOLANO GUIDO",
      "fecha": "2026-09-19",
      "minutos": 0,
      "horas": "0:00",
      "completo": false,
      "observacion": "Falta la salida de las 19:05"
    }
  ]
}
```

Solo salen los días con marcas: un día sin marcas no aparece.

Agregando `formato=csv` devuelve el mismo contenido como archivo, separado por
punto y coma y con BOM, para abrirlo o importarlo en Excel sin configurar nada:

```
GET /api/v1/horas?desde=2026-09-15&hasta=2026-09-20&formato=csv
```

```
codigo_planilla;person_id;nombre;fecha;minutos;horas;completo
14;14;BENJAMIN QUIROS MORA;2026-09-15;736;12:16;si
16;16;BRAYAN JORGE SOLANO GUIDO;2026-09-19;0;0:00;no
```

## `GET /resumen` — totales por persona

Lo más directo para cargar la planilla.

```
GET /api/v1/resumen?desde=2026-09-01&hasta=2026-09-15
```

```json
{
  "desde": "2026-09-01",
  "hasta": "2026-09-15",
  "personas": [
    {
      "person_id": "14",
      "codigo_planilla": null,
      "nombre": "BENJAMIN QUIROS MORA",
      "total_trabajado": {"minutos": 10206, "texto": "170:06"},
      "dias_con_marcas": 15,
      "dias_incompletos": 1,
      "fechas_incompletas": ["2026-09-04"]
    }
  ]
}
```

## `GET /asistencia` — día por día

```
GET /api/v1/asistencia?desde=2026-09-15&hasta=2026-09-15&person_id=14
```

```json
{
  "desde": "2026-09-15",
  "hasta": "2026-09-15",
  "zona_horaria": "America/Costa_Rica",
  "personas": [
    {
      "person_id": "14",
      "codigo_planilla": null,
      "nombre": "BENJAMIN QUIROS MORA",
      "total_trabajado": {"minutos": 736, "texto": "12:16"},
      "dias_con_marcas": 1,
      "dias_incompletos": 0,
      "dias": [
        {
          "fecha": "2026-09-15",
          "marcas": [
            {"tipo": "entrada", "hora": "05:45", "fecha_hora": "2026-09-15T05:45:26-06:00", "origen": "reloj"},
            {"tipo": "salida",  "hora": "14:05", "fecha_hora": "2026-09-15T14:05:15-06:00", "origen": "reloj"},
            {"tipo": "entrada", "hora": "16:30", "fecha_hora": "2026-09-15T16:30:06-06:00", "origen": "reloj"},
            {"tipo": "salida",  "hora": "20:26", "fecha_hora": "2026-09-15T20:26:00-06:00", "origen": "reloj"}
          ],
          "tramos": [
            {"entrada": "05:45", "salida": "14:05"},
            {"entrada": "16:30", "salida": "20:26"}
          ],
          "trabajado": {"minutos": 736, "texto": "12:16"},
          "completo": true,
          "marcas_repetidas_descartadas": 0,
          "observacion": null
        }
      ]
    }
  ]
}
```

`origen` es `"reloj"` o `"manual"` (corrección hecha en el sistema). Las marcas
anuladas no aparecen.

## `GET /marcas` — marcas crudas

Las marcas tal como llegaron del reloj, incluidas las anuladas (`"anulada": true`).
Sirve para auditar o conciliar.

```
GET /api/v1/marcas?desde=2026-09-15&hasta=2026-09-15&person_id=16
```

```json
{
  "desde": "2026-09-15",
  "hasta": "2026-09-15",
  "marcas": [
    {
      "id": 11181,
      "person_id": "16",
      "codigo_planilla": null,
      "nombre": "BRAYAN JORGE SOLANO GUIDO",
      "fecha": "2026-09-15",
      "hora": "05:49:51",
      "fecha_hora": "2026-09-15T05:49:51-06:00",
      "reloj": "COMEDOR",
      "metodo": "huella",
      "anulada": false
    }
  ]
}
```

## Errores

Siempre JSON con un mensaje: `{"error": "..."}`

| Código | Cuándo |
|---|---|
| `400` | Falta `desde`/`hasta`, formato inválido, rango al revés o de más de 62 días |
| `401` | Sin encabezado `Authorization` o clave incorrecta |
| `405` | Método distinto de GET: la API no modifica nada |
| `503` | `API_TOKEN` no está definida en el servidor |

## Ejemplo con curl

```bash
curl -H "Authorization: Bearer $API_TOKEN" \
  "https://marcasreloj.up.railway.app/api/v1/resumen?desde=2026-09-01&hasta=2026-09-15"
```
