from datetime import date
from django.db import models
from django.utils import timezone


class VerificationCase(models.Model):
    """Lightweight representation of a Veriff-style verification case."""

    STATUS_PENDING = "pending"
    STATUS_REVIEW = "needs_review"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_REVIEW, "Needs review"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
    ]

    DOC_PASSPORT = "passport"
    DOC_DL = "driver_license"
    DOC_ID = "national_id"
    DOC_RESIDENCE = "residence_permit"
    DOC_TYPES = [
        (DOC_PASSPORT, "Passport"),
        (DOC_DL, "Driver's licence"),
        (DOC_ID, "National ID"),
        (DOC_RESIDENCE, "Residence permit"),
    ]

    ONBOARDING_WEB = "web"
    ONBOARDING_IOS = "ios"
    ONBOARDING_ANDROID = "android"
    ONBOARDING_CHOICES = [
        (ONBOARDING_WEB, "Web SDK"),
        (ONBOARDING_IOS, "iOS SDK"),
        (ONBOARDING_ANDROID, "Android SDK"),
    ]

    full_name = models.CharField(max_length=120)
    email = models.EmailField()
    country = models.CharField(max_length=64, help_text="User-declared country of residence")
    issuing_country = models.CharField(max_length=64, help_text="Country that issued the document")
    document_type = models.CharField(max_length=32, choices=DOC_TYPES, default=DOC_PASSPORT)
    document_number = models.CharField(max_length=32)
    date_of_birth = models.DateField()
    doc_expiry = models.DateField()
    ip_country = models.CharField(max_length=64, blank=True)
    device_os = models.CharField(max_length=32, default="web")
    device_fingerprint = models.CharField(max_length=64, blank=True)
    attempt_count = models.PositiveIntegerField(default=1)
    onboarding_channel = models.CharField(max_length=24, choices=ONBOARDING_CHOICES, default=ONBOARDING_WEB)
    selfie_quality = models.PositiveIntegerField(default=70)

    doc_authenticity_score = models.PositiveIntegerField(default=0)
    face_match_score = models.PositiveIntegerField(default=0)
    liveness_passed = models.BooleanField(default=False)
    fraud_risk_score = models.PositiveIntegerField(default=0)
    fraud_signals = models.JSONField(default=dict, blank=True)
    aml_findings = models.JSONField(default=dict, blank=True)
    age_verified = models.BooleanField(default=False)
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_PENDING)
    risk_summary = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.full_name} ({self.document_type})"

    # Evaluation helpers
    def evaluate_document(self):
        """Score document authenticity with simple heuristics."""
        score = 92
        flags = []
        today = date.today()
        if len(self.document_number) < 6:
            score -= 22
            flags.append("Document number is shorter than expected")
        if self.doc_expiry <= today:
            score -= 35
            flags.append("Document expired")
        if self.country and self.issuing_country and self.country != self.issuing_country:
            score -= 10
            flags.append("Residence country differs from issuing country")
        return max(score, 0), flags

    def evaluate_biometrics(self):
        """Approximate face match and liveness from capture quality."""
        base = (self.selfie_quality * 0.6) + (self.doc_authenticity_score * 0.4)
        face_match = max(30, min(int(base), 100))
        liveness_passed = self.selfie_quality >= 55 and self.attempt_count <= 4
        reasons = []
        if not liveness_passed:
            reasons.append("Motion / liveness confidence below threshold")
        if face_match < 65:
            reasons.append("Face match below recommended threshold")
        return face_match, liveness_passed, reasons

    def evaluate_fraud(self):
        """Simulate device/velocity/behaviour signals."""
        risk = 10
        signals = []
        if self.ip_country and self.country and self.ip_country != self.country:
            risk += 18
            signals.append("IP geolocation differs from claimed country")
        if self.attempt_count > 2:
            extra = min(25, (self.attempt_count - 1) * 6)
            risk += extra
            signals.append(f"{self.attempt_count} capture attempts in session")
        if self.device_fingerprint:
            reused = (
                VerificationCase.objects.filter(device_fingerprint=self.device_fingerprint)
                .exclude(pk=self.pk)
                .count()
            )
            if reused:
                risk += 22
                signals.append(f"Device fingerprint seen in {reused} other case(s)")
        if self.doc_authenticity_score < 60:
            risk += 14
            signals.append("Low document security score")
        return min(risk, 100), signals

    def evaluate_aml(self):
        """Fake AML/PEP hits based on lightweight pattern checks."""
        findings = {"pep": False, "sanctions": False, "adverse_media": False, "notes": []}
        lowered_name = self.full_name.lower()
        if any(token in lowered_name for token in ["minister", "senator", "mp", "council"]):
            findings["pep"] = True
            findings["notes"].append("Potential PEP keyword in name")
        if self.document_number.endswith("999"):
            findings["sanctions"] = True
            findings["notes"].append("Document number pattern seen on sanctions list sample")
        if self.email.lower().endswith((".ru", ".cn", ".ir", ".kp")):
            findings["adverse_media"] = True
            findings["notes"].append("Email TLD flagged for adverse media screening")
        return findings

    def evaluate_age(self):
        today = timezone.now().date()
        age = today.year - self.date_of_birth.year - (
            (today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day)
        )
        return age, age >= 18

    def run_full_evaluation(self, save=True):
        """Run a lightweight version of Veriff's decision engine."""
        self.doc_authenticity_score, doc_flags = self.evaluate_document()
        self.face_match_score, self.liveness_passed, biometric_notes = self.evaluate_biometrics()
        self.fraud_risk_score, fraud_signals = self.evaluate_fraud()
        self.fraud_signals = fraud_signals
        self.aml_findings = self.evaluate_aml()
        age, age_ok = self.evaluate_age()
        self.age_verified = age_ok

        reasons = doc_flags + biometric_notes + fraud_signals
        aml_hits = [
            key for key, value in self.aml_findings.items() if key in {"pep", "sanctions", "adverse_media"} and value
        ]
        if aml_hits:
            reasons.append(f"AML flags: {', '.join(aml_hits)}")
        if not age_ok:
            reasons.append(f"Age {age} under threshold")

        if self.aml_findings.get("sanctions"):
            self.status = self.STATUS_REJECTED
        elif self.doc_authenticity_score < 55 or self.face_match_score < 60 or not self.liveness_passed:
            self.status = self.STATUS_REVIEW
        elif self.fraud_risk_score >= 45:
            self.status = self.STATUS_REVIEW
        else:
            self.status = self.STATUS_APPROVED

        self.risk_summary = "; ".join(reasons) if reasons else "All signals within acceptable ranges"
        if save:
            self.save()
        return {
            "age": age,
            "doc_flags": doc_flags,
            "biometric_notes": biometric_notes,
            "fraud_signals": fraud_signals,
            "reasons": reasons,
        }
