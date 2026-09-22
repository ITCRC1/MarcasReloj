from django.contrib.auth import views as auth_views
from django.urls import path
from django.views.generic import RedirectView

from apps.core import views

app_name = "core"

urlpatterns = [
    # La raiz lleva al reporte, que es la unica pantalla del sistema.
    path("", RedirectView.as_view(pattern_name="reportes:marcas"), name="inicio"),
    path("tablero/", views.tablero, name="tablero"),
    path(
        "entrar/",
        auth_views.LoginView.as_view(template_name="core/entrar.html"),
        name="entrar",
    ),
    path("salir/", auth_views.LogoutView.as_view(), name="salir"),
    path("empleados/", views.empleados, name="empleados"),
    path("empleados/nuevo/", views.empleado_form, name="empleado_nuevo"),
    path("empleados/<int:pk>/", views.empleado_detalle, name="empleado_detalle"),
    path("empleados/<int:pk>/editar/", views.empleado_form, name="empleado_editar"),
    path("empleados/<int:pk>/mapear/", views.empleado_mapear, name="empleado_mapear"),
]
