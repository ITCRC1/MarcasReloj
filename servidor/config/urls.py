from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("horarios/", include("apps.horarios.urls")),
    path("marcas/", include("apps.marcas.urls")),
    path("reportes/", include("apps.reportes.urls")),
    path("", include("apps.core.urls")),
]
