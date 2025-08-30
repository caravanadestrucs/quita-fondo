from django.urls import path
from .views import remove_background, api_remove_background, index
from django.views.static import serve


urlpatterns = [
    path("", index, name="index"),
    path("remove/", remove_background, name="upload"),
    path("api/remove/", api_remove_background, name="api_remove"),
    path("robots.txt", serve, {"path": "robots.txt", "document_root": "static"}, name="robots"),
    path("sitemap.xml", serve, {"path": "sitemap.xml", "document_root": "static"}, name="sitemap"),
]