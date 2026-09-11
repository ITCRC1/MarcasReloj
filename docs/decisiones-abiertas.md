# Decisiones abiertas

Complemento de las secciones 20 y 21 de la especificacion. Recoge lo que aparecio al
implementar y no estaba resuelto en el documento. Cada punto dice que hace el codigo
hoy, para que el sistema funcione, y que hay que confirmar.

Regla del anexo: ante una regla ambigua no se inventa, se anota aqui y se consulta.

---

## 1. Los minutos de un dia justificado caen en "no laborados"

**Estado actual.** En un dia laboral con justificacion y sin marcas, el motor devuelve
estado `JUSTIFICADO`, `minutos_esperados = 480` y `minutos_ordinarios = 0`. Por la
invariante `ordinarios + no_laborados = esperados`, los 480 minutos terminan en
`minutos_no_laborados`.

**El problema.** Planillas recibe una quincena con vacaciones aprobadas y ve 480 minutos
no laborados por dia, indistinguibles de una ausencia injustificada. La seccion 13.1
expone `dias_justificados`, pero los minutos no tienen concepto propio.

**Para RRHH.** Un dia de vacaciones o incapacidad, para efectos del tiempo que se entrega
a planillas, cuenta como jornada cumplida, como ausencia, o como una tercera categoria?

**Si se decide una categoria propia**, hay que agregar `minutos_justificados` a
`ResultadoDiario`, al resumen de la API y a los reportes, y ajustar la invariante a
`ordinarios + justificados + no_laborados = esperados`.

---

## 2. La ventana de duplicados choca con horarios de intermedio corto

**Estado actual.** El descarte por duplicado se aplica sobre la lista ordenada de marcas
antes de saber si cada una es entrada o salida. Con `ventana_duplicado_min = 5`, un
horario cuyo bloque 2 empieza menos de 5 minutos despues de que termina el bloque 1
pierde la entrada del segundo bloque y el dia queda en `INCONSISTENTE`.

Con el horario de referencia (intermedio de una hora) no ocurre nunca.

**Propuesta.** Validar en `BloqueHorario` que el intermedio entre el bloque 1 y el
bloque 2 sea mayor que `ventana_duplicado_min`, y mostrar el error en el formulario de
horarios. Asi el problema se detecta al configurar y no al calcular.

---

## 3. Limite exacto de la ventana de duplicados

**Estado actual.** El limite es estricto: una marca a exactamente 5 minutos de la anterior
**se conserva**. Solo se descarta lo que esta por debajo de la ventana.

**Por que.** Descartar una marca legitima produce un calculo silenciosamente equivocado.
Conservar una duplicada produce un numero impar de marcas, el dia cae en `INCONSISTENTE`
y alguien lo revisa. Ante la duda, el error que se ve es preferible al que no se ve.

**Para RRHH.** Confirmar, o cambiar a "5 minutos o menos se descarta".

---

## 4. Feriado que cae en dia de descanso

**Estado actual.** El feriado tiene precedencia. Si alguien trabaja un domingo que ademas
es feriado, los minutos van completos a `minutos_feriado` y `minutos_descanso_trabajado`
queda en cero. La tabla 7.3 no contempla la combinacion.

**Para RRHH.** Es lo correcto para efectos de pago, o los dos conceptos deben reportarse
por separado?

---

## 5. `person_id_smartpss` es unico global, pero `PersonID` es unico por instalacion

**Estado actual.** No implementado todavia (toca en la fase 1).

**El problema.** Cada instalacion de SmartPSS tiene su propio catalogo de personas. Con
dos o mas sucursales, el `PersonID` 1024 puede ser dos personas distintas. El modelo de
la seccion 6 pone `person_id_smartpss` como unico global y la llave unica de `MarcaReloj`
como `(person_id, utc_ms, device_ip)`, sin sucursal.

**Propuesta.** Si hay mas de una sucursal (pendiente de la seccion 21), la unicidad debe
ser `(sucursal, person_id)` en `Empleado` y `(sucursal, person_id, utc_ms, device_ip)` en
`MarcaReloj`.

---

## 6. `api_key_hash` con hash salteado no se puede buscar

**Estado actual.** No implementado todavia (toca en la fase 1).

**El problema.** Si `api_key_hash` guarda un hash salteado tipo `make_password`, para
autenticar un `X-API-Key` hay que recorrer todas las filas ejecutando PBKDF2 en cada una,
en cada request. No es indexable.

**Propuesta.** Las claves las genera el sistema, con entropia alta, asi que no necesitan
sal ni derivacion lenta. Guardar SHA-256 de la clave en un campo unico e indexado, mas un
prefijo visible de 8 caracteres (`ak_3f9c2b71...`) para identificar la clave en pantalla
sin poder reconstruirla.

---

## 7. La comprobacion de `AttendanceDateTime` depende de las unidades

**Estado actual.** No implementado todavia (toca en la fase 1).

**El problema.** La seccion 21 pide verificar que
`AttendanceUtcTime - AttendanceDateTime = 21 600 000`. Eso solo se cumple si los dos
campos estan en milisegundos. Si `AttendanceDateTime` viene en segundos, la relacion real
es `AttendanceUtcTime / 1000 - AttendanceDateTime = 21 600`.

**Como verificarlo.** Mirar la cantidad de digitos de una fila cualquiera: 13 digitos son
milisegundos, 10 son segundos. Recien ahi aplicar la formula que corresponda. En cualquier
caso `AttendanceUtcTime` sigue siendo la fuente de verdad y `AttendanceDateTime` se ignora;
la comprobacion solo sirve para confirmar que el reloj esta en la zona correcta.

---

## 8. La validacion 5 del cierre no prueba lo que quiere probar

**Estado actual.** No implementado todavia (toca en la fase 4).

**El problema.** "La ultima sincronizacion de cada sucursal es posterior a la fecha final
del periodo" se cumple sola con que el agente este vivo hoy y el periodo haya terminado
ayer. No dice nada sobre si llegaron todas las marcas.

**Propuesta.** Comparar contra la marca mas reciente recibida por sucursal, no contra el
ultimo latido, y avisar si alguna sucursal no reporta marcas desde antes del final del
periodo.

---

## 9. `AUSENTE` para el dia de hoy

**Estado actual.** El motor no sabe que dia es hoy: `ContextoDia` no lo incluye y el
modulo es puro. Un dia laboral sin marcas siempre devuelve `AUSENTE`.

**Donde se resuelve.** La regla "no se generan resultados AUSENTE para el dia actual ni
para dias futuros" (7.3) la aplica el servicio de recalculo, que si conoce la fecha
actual. Queda anotado para no perderlo de vista en la fase 2.

---

## 10. Un empleado activo sin `PersonID` acumula ausencias en silencio

**Estado actual.** Apareció al cargar los datos de demostración: un empleado activo,
con horario asignado y sin `person_id_smartpss` nunca recibe marcas, asi que todos sus
dias laborales salen `AUSENTE`. En una quincena eso fueron 4 800 minutos no laborados
sin que nada lo advirtiera.

**Que se hizo.** El tablero muestra una alerta roja con la lista de empleados activos
sin PersonID. No bloquea nada, pero se ve antes de cerrar.

**Para RRHH.** Deberia ademas bloquear el cierre del periodo, como las marcas sin
empleado asignado? Hoy no lo hace.

---

## 11. Los dias futuros quedan a medias en los reportes

**Estado actual.** La regla 7.3 dice que no se generan ausencias para hoy ni para el
futuro, y asi esta implementado. Pero solo afecta a `AUSENTE`: un domingo futuro si se
guarda como `LIBRE` y un feriado futuro como `FERIADO`.

**Como se ve.** Al recalcular una quincena en curso, el detalle diario muestra los
domingos y feriados que aun no llegan, pero no los dias habiles que aun no llegan.
La lista se ve con huecos irregulares.

**Por que no es grave.** Se corrige solo: la tarea diaria de las 00:30 va llenando cada
dia conforme pasa, y al momento de cerrar el periodo ya no hay dias futuros.

**Para RRHH.** Conviene que el reporte de una quincena en curso oculte del todo los dias
que aun no llegan, o esta bien asi?

---

## 12. `Marca` lleva dos campos mas que en la seccion 7.1

**Estado actual.** El motor necesita saber si una marca trae `Handler` de SmartPSS y cual
es el motivo de una marca manual, porque las dos cosas son alertas obligatorias de la
seccion 7.6. La dataclass de la seccion 7.1 solo tiene `hora`, `origen` y `ref_id`.

**Que se hizo.** Se agregaron `handler: str = ""` y `motivo: str = ""`, ambos con valor
por defecto, asi que la firma documentada sigue siendo valida. Conviene reflejarlo en la
seccion 7.1 de la especificacion.
