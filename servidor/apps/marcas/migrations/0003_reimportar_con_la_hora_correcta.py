"""Borra las marcas importadas con la hora corrida 6 horas, para reimportarlas.

Hasta aqui el lector tomaba AttendanceDateTime como hora local de Costa Rica,
pero es la hora UTC real (comprobado contra el informe impreso de SmartPSS).
Todas las marcas quedaron 6 horas despues de la real y las de la tarde en el
dia siguiente.

Son copias: la tabla de SmartPSS no se toca. Con esta tabla vacia, la primera
pasada del lector automatico vuelve a traer todo con la hora correcta.

Solo se borran las que nadie ha tocado. Una marca anulada o ya asignada a un
empleado lleva trabajo de alguien y se deja; al momento de escribir esto no
habia ninguna.
"""

from django.db import migrations


def borrar_marcas_con_la_hora_corrida(apps, schema_editor):
    MarcaReloj = apps.get_model("marcas", "MarcaReloj")
    MarcaReloj.objects.filter(anulada=False, empleado__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("marcas", "0002_alter_marcareloj_device_ip"),
    ]

    operations = [
        migrations.RunPython(borrar_marcas_con_la_hora_corrida, migrations.RunPython.noop),
    ]
