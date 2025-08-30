from django.urls import path
from .views import remove_background, api_remove_background, index


urlpatterns = [
    path("", index, name="index"),
    path("remove/", remove_background, name="upload"),
    path("api/remove/", api_remove_background, name="api_remove"),
]