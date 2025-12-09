from django.contrib import admin
from .models import VerificationCase


@admin.register(VerificationCase)
class VerificationCaseAdmin(admin.ModelAdmin):
    list_display = ("full_name", "document_type", "status", "doc_authenticity_score", "fraud_risk_score", "created_at")
    list_filter = ("status", "document_type", "onboarding_channel")
    search_fields = ("full_name", "email", "document_number", "device_fingerprint")
