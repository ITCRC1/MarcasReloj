from django.contrib import admin
from django.urls import include, path

from apps.api.api import api

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", api.urls),
    path("horarios/", include("apps.horarios.urls")),
    path("marcas/", include("apps.marcas.urls")),
    path("periodos/", include("apps.periodos.urls")),
    path("reportes/", include("apps.reportes.urls")),
    path("", include("apps.core.urls")),
]
