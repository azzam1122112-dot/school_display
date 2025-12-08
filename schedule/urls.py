from django.urls import path
from .api import api_current_lessons
from . import views

urlpatterns = [
    path("api/current/<int:school_id>/", api_current_lessons, name="api_current_lessons"),
     path("api/<int:school_id>/current/", views.api_current_lessons, name="api_current"),

]
