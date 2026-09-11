from django.urls import path

from apps.horarios import views

app_name = "horarios"

urlpatterns = [
    path("", views.horarios, name="lista"),
    path("nuevo/", views.horario_form, name="nuevo"),
    path("<int:pk>/", views.horario_detalle, name="detalle"),
    path("<int:pk>/editar/", views.horario_form, name="editar"),
    path("<int:pk>/bloques/", views.bloque_crear, name="bloque_crear"),
    path("bloques/<int:pk>/borrar/", views.bloque_borrar, name="bloque_borrar"),
    path("asignaciones/", views.asignaciones, name="asignaciones"),
    path("feriados/", views.feriados, name="feriados"),
    path("justificaciones/", views.justificaciones, name="justificaciones"),
]
