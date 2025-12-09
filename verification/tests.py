from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import VerificationCase


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
