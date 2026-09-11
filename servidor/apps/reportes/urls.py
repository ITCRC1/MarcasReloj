from django.urls import path

from apps.reportes import views

app_name = "reportes"

urlpatterns = [
    path("", views.reporte, name="reporte"),
    path("empleado/<str:codigo>/", views.detalle_empleado, name="detalle_empleado"),
]
