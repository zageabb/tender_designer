from __future__ import annotations

from flask import Blueprint, current_app, flash, redirect, render_template, url_for

from database import db
from models import RFQ, Tender, TenderQuestion
from services.sample_data import seed_sample_data


dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
def index():
    active_tenders = Tender.query.filter(Tender.status.notin_(["Awarded", "Lost", "Cancelled"])).count()
    tenders_awaiting_review = Tender.query.filter(Tender.status.in_(["Metadata Extracted", "Items Extracted", "Ready For Review"])).count()
    rfqs_waiting = RFQ.query.filter(RFQ.status.in_(["Draft", "Downloaded", "Sent Manually"])).count()
    unanswered_questions = TenderQuestion.query.filter(TenderQuestion.answer_status != "Answered").count()
    recent_tenders = Tender.query.order_by(Tender.updated_at.desc()).limit(5).all()
    chat_context = {"page": "dashboard"}
    return render_template(
        "dashboard.html",
        active_tenders=active_tenders,
        tenders_awaiting_review=tenders_awaiting_review,
        rfqs_waiting=rfqs_waiting,
        unanswered_questions=unanswered_questions,
        recent_tenders=recent_tenders,
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
