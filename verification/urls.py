from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("start/", views.start_verification, name="start_verification"),
    path("case/<int:pk>/", views.case_detail, name="case_detail"),
    path("sdk-playground/", views.sdk_playground, name="sdk_playground"),
]
