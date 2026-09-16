from django.contrib import admin
from django.urls import include, path

from apps.marcas.views import estado_lector

urlpatterns = [
    path("admin/", admin.site.urls),
    path("estado-lector/", estado_lector, name="estado_lector"),
    path("horarios/", include("apps.horarios.urls")),
    path("marcas/", include("apps.marcas.urls")),
    path("reportes/", include("apps.reportes.urls")),
    path("", include("apps.core.urls")),
]
