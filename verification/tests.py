from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import AuditEvent, VerificationCase
from .views import build_webhook_payload, sign_payload


class VerificationCaseEvaluationTests(TestCase):
    def _base_payload(self):
        return {
            "full_name": "Test User",
            "email": "user@test.dev",
            "country": "Estonia",
            "issuing_country": "Estonia",
            "document_type": VerificationCase.DOC_PASSPORT,
            "document_number": "P1234567",
            "date_of_birth": date(1990, 1, 1),
            "doc_expiry": date.today() + timedelta(days=365),
            "ip_country": "Estonia",
            "device_os": "web",
            "device_fingerprint": "web-abc",
            "attempt_count": 1,
            "onboarding_channel": VerificationCase.ONBOARDING_WEB,
            "selfie_quality": 80,
        }

    def test_expired_document_goes_to_review(self):
        case = VerificationCase(**self._base_payload())
        case.doc_expiry = date.today() - timedelta(days=1)
        case.document_number = "P1"
        case.run_full_evaluation()
        self.assertEqual(case.status, VerificationCase.STATUS_REVIEW)
        self.assertLess(case.doc_authenticity_score, 70)
        self.assertIn("Document expired", case.risk_summary)

    def test_sanctions_pattern_rejects(self):
        case = VerificationCase(**self._base_payload())
        case.document_number = "ABC999"  # triggers sanctions pattern
        case.run_full_evaluation()
        self.assertEqual(case.status, VerificationCase.STATUS_REJECTED)
        self.assertTrue(case.aml_findings.get("sanctions"))

    def test_mark_review_records_decision(self):
        case = VerificationCase.objects.create(**self._base_payload())
        now = timezone.now()
        case.mark_review(VerificationCase.STATUS_APPROVED, reviewer_name="Reviewer", notes="Looks good")
        self.assertEqual(case.status, VerificationCase.STATUS_APPROVED)
        self.assertEqual(case.reviewer_name, "Reviewer")
        self.assertEqual(case.reviewer_notes, "Looks good")
        self.assertIsNotNone(case.reviewed_at)
        self.assertGreaterEqual(case.reviewed_at, now)


class ExportTests(TestCase):
    def setUp(self):
        self.case_ok = VerificationCase.objects.create(
            full_name="Clean Case",
            email="clean@test.dev",
            country="Estonia",
            issuing_country="Estonia",
            document_type=VerificationCase.DOC_PASSPORT,
            document_number="P1234567",
            date_of_birth=date(1990, 1, 1),
            doc_expiry=date.today() + timedelta(days=365),
            ip_country="Estonia",
            device_os="web",
            attempt_count=1,
            onboarding_channel=VerificationCase.ONBOARDING_WEB,
            selfie_quality=90,
            doc_authenticity_score=95,
            face_match_score=92,
            fraud_risk_score=5,
            age_verified=True,
            status=VerificationCase.STATUS_APPROVED,
        )
        self.case_review = VerificationCase.objects.create(
            full_name="Fraud Risk",
            email="risk@test.dev",
            country="Spain",
            issuing_country="Mexico",
            document_type=VerificationCase.DOC_DL,
            document_number="DL-999999",
            date_of_birth=date(1995, 1, 1),
            doc_expiry=date.today() + timedelta(days=365),
            ip_country="United States",
            device_os="ios",
            attempt_count=4,
            onboarding_channel=VerificationCase.ONBOARDING_IOS,
            selfie_quality=55,
            doc_authenticity_score=60,
            face_match_score=58,
            fraud_risk_score=70,
            age_verified=True,
            status=VerificationCase.STATUS_REVIEW,
            aml_findings={"sanctions": True},
            risk_summary="High risk",
        )

    def test_export_filter_status(self):
        url = reverse("export_cases_csv")
        resp = self.client.get(
            url,
            {
                "download": 1,
                "status": [VerificationCase.STATUS_APPROVED],
                "limit": 10,
                "export_format": "csv",
            },
        )
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn("Clean Case", content)
        self.assertNotIn("Fraud Risk", content)

    def test_export_zip_includes_risk_summary(self):
        url = reverse("export_cases_csv")
        resp = self.client.get(
            url,
            {
                "download": 1,
                "export_format": "zip",
                "include_risk_summary": True,
                "limit": 5,
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/zip")


class WebhookSimulatorTests(TestCase):
    def test_webhook_signature_generation(self):
        case = VerificationCase.objects.create(
            full_name="Webhook Case",
            email="webhook@test.dev",
            country="Estonia",
            issuing_country="Estonia",
            document_type=VerificationCase.DOC_PASSPORT,
            document_number="P1234",
            date_of_birth=date(1990, 1, 1),
            doc_expiry=date.today() + timedelta(days=365),
            ip_country="Estonia",
            device_os="web",
            attempt_count=1,
            onboarding_channel=VerificationCase.ONBOARDING_WEB,
            selfie_quality=85,
        )
        case.run_full_evaluation()
        payload = build_webhook_payload(case, "approved")
        sig = sign_payload(payload, secret="secret")
        self.assertTrue(sig)
        # Signatures should change if payload changes
        payload["data"]["status"] = "needs_review"
        sig2 = sign_payload(payload, secret="secret")
        self.assertNotEqual(sig, sig2)


class VelocityDashboardTests(TestCase):
    def setUp(self):
        VerificationCase.objects.bulk_create(
            [
                VerificationCase(
                    full_name="User A",
                    email="a@test.dev",
                    country="Estonia",
                    issuing_country="Estonia",
                    document_type=VerificationCase.DOC_PASSPORT,
                    document_number="P111",
                    date_of_birth=date(1990, 1, 1),
                    doc_expiry=date.today() + timedelta(days=365),
                    ip_country="Estonia",
                    device_os="web",
                    device_fingerprint="fp-123",
                    fraud_risk_score=10,
                    status=VerificationCase.STATUS_APPROVED,
                ),
                VerificationCase(
                    full_name="User B",
                    email="b@test.dev",
                    country="Estonia",
                    issuing_country="Estonia",
                    document_type=VerificationCase.DOC_PASSPORT,
                    document_number="P222",
                    date_of_birth=date(1990, 1, 1),
                    doc_expiry=date.today() + timedelta(days=365),
                    ip_country="Estonia",
                    device_os="web",
                    device_fingerprint="fp-123",
                    fraud_risk_score=65,
                    status=VerificationCase.STATUS_REVIEW,
                ),
            ]
        )

    def test_velocity_page_shows_reused_fingerprint(self):
        resp = self.client.get(reverse("velocity_dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "fp-123")


class HealthcheckTests(TestCase):
    def test_healthcheck_returns_status_and_counts(self):
        VerificationCase.objects.create(
            full_name="Health User",
            email="health@test.dev",
            country="Estonia",
            issuing_country="Estonia",
            document_type=VerificationCase.DOC_PASSPORT,
            document_number="P999",
            date_of_birth=date(1990, 1, 1),
            doc_expiry=date.today() + timedelta(days=365),
            ip_country="Estonia",
            device_os="web",
            attempt_count=1,
            onboarding_channel=VerificationCase.ONBOARDING_WEB,
            selfie_quality=80,
            status=VerificationCase.STATUS_APPROVED,
        )
        resp = self.client.get(reverse("healthcheck"))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertGreaterEqual(data["counts"]["total"], 1)


class AuditTrailTests(TestCase):
    def test_audit_event_created_on_case_creation(self):
        payload = {
            "full_name": "Audit User",
            "email": "audit@test.dev",
            "country": "Estonia",
            "issuing_country": "Estonia",
            "document_type": VerificationCase.DOC_PASSPORT,
            "document_number": "P3333",
            "date_of_birth": date(1990, 1, 1),
            "doc_expiry": date.today() + timedelta(days=365),
            "ip_country": "Estonia",
            "device_os": "web",
            "attempt_count": 1,
            "onboarding_channel": VerificationCase.ONBOARDING_WEB,
            "selfie_quality": 80,
        }
        resp = self.client.post(reverse("start_verification"), payload)
        self.assertEqual(resp.status_code, 302)
        case = VerificationCase.objects.get(email="audit@test.dev")
        self.assertTrue(AuditEvent.objects.filter(case=case, event_type=AuditEvent.EVENT_CREATED).exists())
