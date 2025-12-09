from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("start/", views.start_verification, name="start_verification"),
    path("case/<int:pk>/", views.case_detail, name="case_detail"),
    path("review/", views.review_queue, name="review_queue"),
    path("case/<int:pk>/review/", views.review_case, name="review_case"),
    path("case/<int:pk>/rerun/", views.rerun_case, name="rerun_case"),
    path("risk-tuning/", views.risk_tuning, name="risk_tuning"),
    path("sdk-playground/", views.sdk_playground, name="sdk_playground"),
]
