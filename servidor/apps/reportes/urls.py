from django.urls import path

from apps.reportes import views

app_name = "reportes"

urlpatterns = [
    path("", views.indice, name="indice"),
    path("periodo/<int:periodo_id>/resumen/", views.resumen, name="resumen"),
    path("periodo/<int:periodo_id>/tardias/", views.tardias, name="tardias"),
    path(
        "periodo/<int:periodo_id>/empleado/<str:codigo>/",
        views.detalle_empleado,
        name="detalle_empleado",
    ),
]
