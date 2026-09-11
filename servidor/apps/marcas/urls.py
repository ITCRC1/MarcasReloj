from django.urls import path

from apps.marcas import views

app_name = "marcas"

urlpatterns = [
    path("crudas/", views.crudas, name="crudas"),
    path("dia/<str:codigo>/hoy/", views.dia_de_hoy, name="dia_hoy"),
    path("dia/<str:codigo>/<str:fecha>/", views.dia, name="dia"),
    path(
        "dia/<str:codigo>/<str:fecha>/manual/",
        views.marca_manual_crear,
        name="marca_manual_crear",
    ),
    path(
        "dia/<str:codigo>/<str:fecha>/recalcular/",
        views.recalcular_dia,
        name="recalcular_dia",
    ),
    path("marca/<int:pk>/anular/", views.marca_anular, name="marca_anular"),
    path("manual/<int:pk>/anular/", views.manual_anular, name="manual_anular"),
]
