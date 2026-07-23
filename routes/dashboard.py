from __future__ import annotations

from datetime import date

from flask import Blueprint, current_app, flash, redirect, render_template, url_for

from database import db
from models import RFQ, Tender, TenderQuestion
from services.sample_data import seed_sample_data


dashboard_bp = Blueprint("dashboard", __name__)

OUTSTANDING_TENDER_STATUS_ORDER = {
    "New": 0,
    "Documents Uploaded": 1,
    "Metadata Extracted": 2,
    "Items Extracted": 3,
    "RFI Required": 4,
    "Quoted": 5,
    "Ready For Review": 6,
    "Submitted": 7,
}


@dashboard_bp.route("/")
def index():
    active_tenders = Tender.query.filter(Tender.status.notin_(["Awarded", "Lost", "Cancelled"])).count()
    tenders_awaiting_review = Tender.query.filter(Tender.status.in_(["Metadata Extracted", "Items Extracted", "Ready For Review"])).count()
    rfqs_waiting = RFQ.query.filter(RFQ.status.in_(["Draft", "Downloaded", "Sent Manually"])).count()
    unanswered_questions = TenderQuestion.query.filter(TenderQuestion.answer_status != "Answered").count()
    outstanding_tenders = (
        Tender.query.filter(Tender.status.notin_(["Awarded", "Lost", "Cancelled"]))
        .all()
    )
    outstanding_tenders = sorted(
        outstanding_tenders,
        key=lambda tender: (
            OUTSTANDING_TENDER_STATUS_ORDER.get(tender.status, 99),
            tender.submission_date or date.max,
            tender.tender_number or "",
        ),
    )[:12]
    chat_context = {"page": "dashboard"}
    return render_template(
        "dashboard.html",
        active_tenders=active_tenders,
        tenders_awaiting_review=tenders_awaiting_review,
        rfqs_waiting=rfqs_waiting,
        unanswered_questions=unanswered_questions,
        outstanding_tenders=outstanding_tenders,
        chat_context=chat_context,
    )


@dashboard_bp.route("/load-sample-data", methods=["POST"])
def load_sample_data():
    result = seed_sample_data(current_app.config["DATA_DIR"])
    flash(
        f"Sample data loaded: {result['tenders']} tenders, {result['documents']} documents, "
        f"{result['items']} items, {result['questions']} questions.",
        "success",
    )
    return redirect(url_for("dashboard.index"))
