from django import forms

from .models import VerificationCase


class VerificationCaseForm(forms.ModelForm):
    """Form used to simulate Veriff's capture and verification flow."""

    class Meta:
        model = VerificationCase
        fields = [
            "full_name",
            "email",
            "country",
            "issuing_country",
            "document_type",
            "document_number",
            "date_of_birth",
            "doc_expiry",
            "ip_country",
            "device_os",
            "device_fingerprint",
            "attempt_count",
            "onboarding_channel",
            "selfie_quality",
        ]
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
            "doc_expiry": forms.DateInput(attrs={"type": "date"}),
            "attempt_count": forms.NumberInput(attrs={"min": 1, "max": 10}),
            "selfie_quality": forms.NumberInput(attrs={"min": 1, "max": 100}),
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("attempt_count", 1) < 1:
            self.add_error("attempt_count", "Attempts must be at least one.")
        return cleaned
