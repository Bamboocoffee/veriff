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


class ReviewDecisionForm(forms.Form):
    decision = forms.ChoiceField(
        choices=[
            (VerificationCase.STATUS_APPROVED, "Approve"),
            (VerificationCase.STATUS_REJECTED, "Decline"),
            (VerificationCase.STATUS_REVIEW, "Keep in review"),
        ]
    )
    reviewer_name = forms.CharField(max_length=120, required=False, label="Reviewer")
    reviewer_notes = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False, label="Notes")


class RiskTuningForm(forms.Form):
    def __init__(self, *args, **kwargs):
        case_choices = kwargs.pop("case_choices", [])
        super().__init__(*args, **kwargs)
        self.fields["case_id"].choices = case_choices

    case_id = forms.ChoiceField(label="Case", choices=[])
    min_doc_score = forms.IntegerField(label="Min document authenticity %", min_value=0, max_value=100, initial=55)
    min_face_match = forms.IntegerField(label="Min face match %", min_value=0, max_value=100, initial=60)
    fraud_review_cutoff = forms.IntegerField(label="Fraud risk review cutoff", min_value=0, max_value=100, initial=45)
    enforce_liveness = forms.BooleanField(label="Require liveness pass", required=False, initial=True)
