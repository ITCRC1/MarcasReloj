from django.urls import path

from apps.periodos import views

app_name = "periodos"

urlpatterns = [
    path("", views.periodos, name="lista"),
    path("<int:pk>/", views.periodo_detalle, name="detalle"),
    path("<int:pk>/estado/<str:estado>/", views.periodo_estado, name="estado"),
    path("<int:pk>/cerrar/", views.periodo_cerrar, name="cerrar"),
    path("<int:pk>/recalcular/", views.periodo_recalcular, name="recalcular"),
    path("<int:pk>/ajustes/", views.ajuste_crear, name="ajuste_crear"),
]
