from datetime import date, timedelta

import csv

from django.db import models
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .forms import ReviewDecisionForm, RiskTuningForm, VerificationCaseForm
from .models import VerificationCase


def seed_demo_cases():
    """Populate a few demo cases so the dashboard isn't empty."""
    if VerificationCase.objects.exists():
        return
    sample_payloads = [
        {
            "full_name": "Aisha Rahman",
            "email": "aisha@fintech.test",
            "country": "Estonia",
            "issuing_country": "Estonia",
            "document_type": VerificationCase.DOC_PASSPORT,
            "document_number": "P1234567",
            "date_of_birth": date(1994, 7, 12),
            "doc_expiry": date.today() + timedelta(days=365 * 6),
            "ip_country": "Estonia",
            "device_os": "ios",
            "device_fingerprint": "ios-seed-1",
            "attempt_count": 1,
            "onboarding_channel": VerificationCase.ONBOARDING_IOS,
            "selfie_quality": 82,
        },
        {
            "full_name": "Carlos Mendez",
            "email": "carlos@marketplace.test",
            "country": "Mexico",
            "issuing_country": "Spain",
            "document_type": VerificationCase.DOC_DL,
            "document_number": "DL-99812",
            "date_of_birth": date(1988, 11, 3),
            "doc_expiry": date.today() + timedelta(days=365 * 2),
            "ip_country": "United States",
            "device_os": "android",
            "device_fingerprint": "android-seed-1",
            "attempt_count": 3,
            "onboarding_channel": VerificationCase.ONBOARDING_ANDROID,
            "selfie_quality": 58,
        },
        {
            "full_name": "Mila Novak",
            "email": "mila.novak@crypto.test",
            "country": "Slovenia",
            "issuing_country": "Slovenia",
            "document_type": VerificationCase.DOC_ID,
            "document_number": "ID-238999",
            "date_of_birth": date(2006, 2, 15),
            "doc_expiry": date.today() + timedelta(days=365),
            "ip_country": "Slovenia",
            "device_os": "web",
            "device_fingerprint": "web-seed-1",
            "attempt_count": 2,
            "onboarding_channel": VerificationCase.ONBOARDING_WEB,
            "selfie_quality": 62,
        },
    ]
    for payload in sample_payloads:
        case = VerificationCase(**payload)
        case.run_full_evaluation(save=False)
        case.save()


def dashboard(request):
    seed_demo_cases()
    cases = VerificationCase.objects.all()
    recent_cases = cases[:5]
    stats = {
        "total": cases.count(),
        "approved": cases.filter(status=VerificationCase.STATUS_APPROVED).count(),
        "needs_review": cases.filter(status=VerificationCase.STATUS_REVIEW).count(),
        "rejected": cases.filter(status=VerificationCase.STATUS_REJECTED).count(),
    }
    averages = {
        "doc_authenticity": int(cases.aggregate(models.Avg("doc_authenticity_score"))["doc_authenticity_score__avg"] or 0),
        "face_match": int(cases.aggregate(models.Avg("face_match_score"))["face_match_score__avg"] or 0),
        "fraud_risk": int(cases.aggregate(models.Avg("fraud_risk_score"))["fraud_risk_score__avg"] or 0),
    }
    risk_events = [
        "Document tampering detection",
        "Face-match + liveness",
        "Device fingerprinting & velocity",
        "PEP / sanctions screening",
        "Age verification for gaming/social",
    ]
    return render(
        request,
        "dashboard.html",
        {
            "stats": stats,
            "averages": averages,
            "recent_cases": recent_cases,
            "risk_events": risk_events,
        },
    )


def start_verification(request):
    initial = {
        "attempt_count": 1,
        "country": "United States",
        "issuing_country": "United States",
        "ip_country": "United States",
        "device_os": "web",
        "selfie_quality": 78,
    }
    if request.method == "POST":
        form = VerificationCaseForm(request.POST)
        if form.is_valid():
            case = form.save(commit=False)
            case.run_full_evaluation(save=False)
            case.save()
            return redirect(reverse("case_detail", kwargs={"pk": case.pk}))
    else:
        form = VerificationCaseForm(initial=initial)
    return render(request, "start_verification.html", {"form": form})


def case_detail(request, pk):
    case = get_object_or_404(VerificationCase, pk=pk)
    age, _ = case.evaluate_age()
    fraud_signals = case.fraud_signals or []
    aml_findings = case.aml_findings or {}
    return render(
        request,
        "case_detail.html",
        {"case": case, "age": age, "fraud_signals": fraud_signals, "aml_findings": aml_findings},
    )


def review_queue(request):
    pending = VerificationCase.objects.filter(status=VerificationCase.STATUS_REVIEW)
    recently_reviewed = VerificationCase.objects.filter(reviewed_at__isnull=False)[:5]
    case_forms = [(case, ReviewDecisionForm(initial={"decision": case.status})) for case in pending]
    return render(
        request,
        "review_queue.html",
        {"pending": case_forms, "recently_reviewed": recently_reviewed},
    )


def review_case(request, pk):
    case = get_object_or_404(VerificationCase, pk=pk)
    if request.method != "POST":
        return redirect(reverse("review_queue"))
    form = ReviewDecisionForm(request.POST)
    if form.is_valid():
        case.mark_review(
            decision=form.cleaned_data["decision"],
            reviewer_name=form.cleaned_data.get("reviewer_name", ""),
            notes=form.cleaned_data.get("reviewer_notes", ""),
        )
    return redirect(reverse("case_detail", kwargs={"pk": case.pk}))


def rerun_case(request, pk):
    """Allow quick re-evaluation after metadata tweaks or retry attempts."""
    case = get_object_or_404(VerificationCase, pk=pk)
    if request.method == "POST":
        case.run_full_evaluation()
        return redirect(reverse("case_detail", kwargs={"pk": case.pk}))
    return redirect(reverse("case_detail", kwargs={"pk": case.pk}))


def sdk_playground(request):
    """Show how the SDK-based onboarding flow might be stitched together."""
    sample_steps = [
        {"title": "Session creation", "body": "Create a verification session with allowed document types and callbacks."},
        {"title": "Document capture", "body": "Client SDK guides the user through MRZ scan + glare/blur checks."},
        {"title": "Selfie + liveness", "body": "SDK performs active liveness and returns biometrics hash."},
        {"title": "Submit artifacts", "body": "Images, video snippets, device metadata shipped to backend."},
        {"title": "Decision webhook", "body": "Receive approve/review/decline with fraud and AML reasons."},
    ]
    customization = [
        "White-label UI with brand colors and fonts",
        "Configurable steps per market (age gating, doc types)",
        "Callbacks for custom fraud rules or manual review",
        "Drop-in mode or fully headless APIs",
    ]
    return render(
        request,
        "sdk_playground.html",
        {"sample_steps": sample_steps, "customization": customization},
    )


def export_cases_csv(request):
    """Export recent verification cases for ops review."""
    cases = VerificationCase.objects.all().select_related()[:200]
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="verifications.csv"'
    writer = csv.writer(response)
    writer.writerow(
        [
            "id",
            "full_name",
            "email",
            "country",
            "issuing_country",
            "document_type",
            "status",
            "doc_authenticity_score",
            "face_match_score",
            "fraud_risk_score",
            "age_verified",
            "aml_pep",
            "sanctions",
            "created_at",
        ]
    )
    for case in cases:
        writer.writerow(
            [
                case.pk,
                case.full_name,
                case.email,
                case.country,
                case.issuing_country,
                case.get_document_type_display(),
                case.get_status_display(),
                case.doc_authenticity_score,
                case.face_match_score,
                case.fraud_risk_score,
                case.age_verified,
                bool(case.aml_findings.get("pep")) if case.aml_findings else False,
                bool(case.aml_findings.get("sanctions")) if case.aml_findings else False,
                case.created_at,
            ]
        )
    return response


def risk_tuning(request):
    """Adjust thresholds and preview how a case would be decided."""
    cases = VerificationCase.objects.all()
    choices = [(str(c.pk), f"{c.full_name} ({c.get_status_display()})") for c in cases]
    preview = None
    selected_case = None
    form = RiskTuningForm(request.POST or None, case_choices=choices)
    if request.method == "POST" and form.is_valid():
        selected_case = get_object_or_404(VerificationCase, pk=form.cleaned_data["case_id"])
        selected_case.run_full_evaluation(save=False)
        preview = simulate_decision(
            selected_case,
            {
                "min_doc_score": form.cleaned_data["min_doc_score"],
                "min_face_match": form.cleaned_data["min_face_match"],
                "fraud_review_cutoff": form.cleaned_data["fraud_review_cutoff"],
                "enforce_liveness": form.cleaned_data["enforce_liveness"],
            },
        )
    return render(
        request,
        "risk_tuning.html",
        {"form": form, "preview": preview, "selected_case": selected_case},
    )


def simulate_decision(case: VerificationCase, thresholds: dict):
    """Apply custom thresholds to a case without persisting."""
    reasons = []
    decision = VerificationCase.STATUS_APPROVED

    if case.aml_findings.get("sanctions"):
        decision = VerificationCase.STATUS_REJECTED
        reasons.append("Sanctions hit")
    if thresholds.get("enforce_liveness") and not case.liveness_passed:
        decision = VerificationCase.STATUS_REVIEW
        reasons.append("Liveness required but not passed")
    if case.doc_authenticity_score < thresholds.get("min_doc_score", 55):
        decision = VerificationCase.STATUS_REVIEW
        reasons.append(f"Doc authenticity below {thresholds.get('min_doc_score')}")
    if case.face_match_score < thresholds.get("min_face_match", 60):
        decision = VerificationCase.STATUS_REVIEW
        reasons.append(f"Face match below {thresholds.get('min_face_match')}")
    if case.fraud_risk_score >= thresholds.get("fraud_review_cutoff", 45):
        decision = VerificationCase.STATUS_REVIEW
        reasons.append(f"Fraud score above {thresholds.get('fraud_review_cutoff')}")
    if not case.age_verified:
        decision = VerificationCase.STATUS_REVIEW
        reasons.append("Age under threshold")

    return {
        "decision": decision,
        "reasons": reasons or ["All signals within thresholds"],
        "case": case,
        "thresholds": thresholds,
    }
