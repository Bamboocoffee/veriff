from datetime import date, timedelta

import csv
import hashlib
import hmac
import io
import json
import uuid
import zipfile

from django.db import models
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .forms import ExportFilterForm, ReviewDecisionForm, RiskTuningForm, VerificationCaseForm, WebhookSimulatorForm
from .models import AuditEvent, VerificationCase


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
            case.log_event(AuditEvent.EVENT_CREATED, "Verification case created via onboarding flow")
            return redirect(reverse("case_detail", kwargs={"pk": case.pk}))
    else:
        form = VerificationCaseForm(initial=initial)
    return render(request, "start_verification.html", {"form": form})


def case_detail(request, pk):
    case = get_object_or_404(VerificationCase, pk=pk)
    age, _ = case.evaluate_age()
    fraud_signals = case.fraud_signals or []
    aml_findings = case.aml_findings or {}
    audit_events = case.audit_events.all()[:10]
    return render(
        request,
        "case_detail.html",
        {
            "case": case,
            "age": age,
            "fraud_signals": fraud_signals,
            "aml_findings": aml_findings,
            "audit_events": audit_events,
        },
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
        case.log_event(
            AuditEvent.EVENT_REVIEW,
            f"Manual decision: {case.get_status_display()}",
        )
    return redirect(reverse("case_detail", kwargs={"pk": case.pk}))


def rerun_case(request, pk):
    """Allow quick re-evaluation after metadata tweaks or retry attempts."""
    case = get_object_or_404(VerificationCase, pk=pk)
    if request.method == "POST":
        case.run_full_evaluation()
        case.log_event(AuditEvent.EVENT_RERUN, "Verification checks re-run")
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


def webhook_simulator(request):
    """Generate a signed webhook payload to test integrations."""
    seed_demo_cases()
    form = WebhookSimulatorForm(request.POST or None)
    payload = None
    signature = None
    payload_json = None
    if form.is_valid():
        case = VerificationCase.objects.order_by("-created_at").first()
        if not case:
            case = VerificationCase.objects.create(
                full_name="Webhook Sample",
                email="demo@veriff.test",
                country="Estonia",
                issuing_country="Estonia",
                document_type=VerificationCase.DOC_PASSPORT,
                document_number="P0000",
                date_of_birth=date(1990, 1, 1),
                doc_expiry=date.today() + timedelta(days=365),
                ip_country="Estonia",
                device_os="web",
                attempt_count=1,
                onboarding_channel=VerificationCase.ONBOARDING_WEB,
                selfie_quality=80,
            )
            case.run_full_evaluation()
        payload = build_webhook_payload(
            case,
            decision=form.cleaned_data["decision"],
            include_aml=form.cleaned_data.get("include_aml", True),
            include_device=form.cleaned_data.get("include_device", True),
        )
        signature = sign_payload(payload)
        payload_json = json.dumps(payload, indent=2)
    return render(
        request,
        "webhook_simulator.html",
        {"form": form, "payload": payload_json, "signature": signature, "callback_url": form["callback_url"].value()},
    )


def export_cases_csv(request):
    """Advanced export with filters and CSV/ZIP options."""
    form = ExportFilterForm(request.GET or None)
    cases = VerificationCase.objects.none()
    if form.is_valid():
        cases = _filtered_cases(form.cleaned_data)
        if request.GET.get("download") == "1":
            return _stream_cases_export(cases, form.cleaned_data)
    sample_count = cases.count() if form.is_valid() else 0
    return render(request, "export.html", {"form": form, "sample_count": sample_count})


def velocity_dashboard(request):
    """Show device/IP reuse and velocity signals."""
    seed_demo_cases()
    top_devices = (
        VerificationCase.objects.exclude(device_fingerprint="")
        .values("device_fingerprint")
        .annotate(
            count=models.Count("id"),
            max_risk=models.Max("fraud_risk_score"),
            last_seen=models.Max("created_at"),
        )
        .order_by("-count")[:10]
    )
    top_ips = (
        VerificationCase.objects.exclude(ip_country="")
        .values("ip_country")
        .annotate(count=models.Count("id"), max_risk=models.Max("fraud_risk_score"))
        .order_by("-count")[:10]
    )
    velocity_alerts = [d for d in top_devices if d["count"] > 1 and d["max_risk"] >= 40]
    return render(
        request,
        "velocity.html",
        {"top_devices": top_devices, "top_ips": top_ips, "velocity_alerts": velocity_alerts},
    )


def healthcheck(request):
    """Lightweight health endpoint with verification stats."""
    seed_demo_cases()
    qs = VerificationCase.objects.all()
    payload = {
        "status": "ok",
        "counts": {
            "total": qs.count(),
            "approved": qs.filter(status=VerificationCase.STATUS_APPROVED).count(),
            "review": qs.filter(status=VerificationCase.STATUS_REVIEW).count(),
            "rejected": qs.filter(status=VerificationCase.STATUS_REJECTED).count(),
        },
        "latest_case_id": qs.first().pk if qs.exists() else None,
    }
    return JsonResponse(payload)


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


def build_webhook_payload(case: VerificationCase, decision: str, include_aml=True, include_device=True):
    data = {
        "case_id": case.pk,
        "status": decision,
        "full_name": case.full_name,
        "document_type": case.document_type,
        "country": case.country,
        "scores": {
            "doc_authenticity": case.doc_authenticity_score,
            "face_match": case.face_match_score,
            "fraud_risk": case.fraud_risk_score,
        },
        "age_verified": case.age_verified,
        "created_at": case.created_at.isoformat() if case.created_at else "",
    }
    if include_aml:
        data["aml"] = {
            "pep": bool(case.aml_findings.get("pep")) if case.aml_findings else False,
            "sanctions": bool(case.aml_findings.get("sanctions")) if case.aml_findings else False,
            "adverse_media": bool(case.aml_findings.get("adverse_media")) if case.aml_findings else False,
        }
    if include_device:
        data["device"] = {
            "device_os": case.device_os,
            "ip_country": case.ip_country,
            "fingerprint": case.device_fingerprint,
        }
    payload = {
        "id": str(uuid.uuid4()),
        "type": f"verification.{decision}",
        "data": data,
        "delivered_at": timezone.now().isoformat(),
    }
    return payload


def sign_payload(payload: dict, secret: str = "demo_webhook_secret") -> str:
    serialized = json.dumps(payload, sort_keys=True).encode()
    return hmac.new(secret.encode(), serialized, hashlib.sha256).hexdigest()


# Export helpers
def _filtered_cases(filters):
    qs = VerificationCase.objects.all()
    if filters.get("status"):
        qs = qs.filter(status__in=filters["status"])
    if filters.get("doc_type"):
        qs = qs.filter(document_type__in=filters["doc_type"])
    if filters.get("date_from"):
        qs = qs.filter(created_at__date__gte=filters["date_from"])
    if filters.get("date_to"):
        qs = qs.filter(created_at__date__lte=filters["date_to"])
    if filters.get("min_doc_score") is not None:
        qs = qs.filter(doc_authenticity_score__gte=filters["min_doc_score"])
    if filters.get("min_face_match") is not None:
        qs = qs.filter(face_match_score__gte=filters["min_face_match"])
    if filters.get("max_fraud_risk") is not None:
        qs = qs.filter(fraud_risk_score__lte=filters["max_fraud_risk"])
    limit = filters.get("limit") or 500
    return qs.order_by("-created_at")[:limit]


def _stream_cases_export(cases, filters):
    include_aml = filters.get("include_aml", True)
    include_risk_summary = filters.get("include_risk_summary", True)
    export_format = filters.get("export_format", "csv")

    header = [
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
        "created_at",
    ]
    if include_aml:
        header.extend(["aml_pep", "sanctions", "adverse_media"])
    if include_risk_summary:
        header.append("risk_summary")

    if export_format == "zip":
        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)
        writer.writerow(header)
        for row in _case_rows(cases, include_aml, include_risk_summary):
            writer.writerow(row)
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("verifications.csv", csv_buffer.getvalue())
        zip_buffer.seek(0)
        response = HttpResponse(zip_buffer.getvalue(), content_type="application/zip")
        response["Content-Disposition"] = 'attachment; filename="verifications.zip"'
        return response

    class Echo:
        def write(self, value):
            return value

    writer = csv.writer(Echo())

    def row_generator():
        yield writer.writerow(header)
        for row in _case_rows(cases, include_aml, include_risk_summary):
            yield writer.writerow(row)

    resp = HttpResponse(row_generator(), content_type="text/csv")
    resp["Content-Disposition"] = 'attachment; filename="verifications.csv"'
    return resp


def _case_rows(cases, include_aml, include_risk_summary):
    for case in cases:
        row = [
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
            case.created_at,
        ]
        if include_aml:
            row.extend(
                [
                    bool(case.aml_findings.get("pep")) if case.aml_findings else False,
                    bool(case.aml_findings.get("sanctions")) if case.aml_findings else False,
                    bool(case.aml_findings.get("adverse_media")) if case.aml_findings else False,
                ]
            )
        if include_risk_summary:
            row.append(case.risk_summary)
        yield row
