from __future__ import annotations

from pathlib import Path

from flask import Blueprint, current_app, flash, redirect, render_template, send_file, url_for

from database import db
from models import RFQ, Tender
from services.rfq_service import create_rfq_for_selection


rfqs_bp = Blueprint("rfqs", __name__, url_prefix="/rfqs")


@rfqs_bp.route("/tender/<int:tender_id>/new", methods=["GET", "POST"])
def create_rfq(tender_id: int):
    from flask import request

    tender = Tender.query.get_or_404(tender_id)
    if request.method == "POST":
        supplier_name = request.form.get("supplier_name", "").strip()
        supplier_email = request.form.get("supplier_email", "").strip()
        selected_item_ids = request.form.getlist("item_ids", type=int)
        selected_sub_item_ids = request.form.getlist("sub_item_ids", type=int)
        if not selected_item_ids and not selected_sub_item_ids:
            flash("Select at least one item or sub-item for the RFQ.", "warning")
            return redirect(url_for("rfqs.create_rfq", tender_id=tender.id))
        rfq = create_rfq_for_selection(
            db,
            current_app.config["DATA_DIR"],
            tender,
            supplier_name,
            supplier_email,
            selected_item_ids,
            selected_sub_item_ids,
        )
        db.session.commit()
        flash("RFQ created and EML generated.", "success")
        return redirect(url_for("rfqs.view_rfq", rfq_id=rfq.id))
    return render_template(
        "rfqs/form.html",
        tender=tender,
        chat_context={
            "page": "rfq_create",
            "tender_id": tender.id,
            "tender_number": tender.tender_number,
            "customer_name": tender.customer_name,
        },
    )


@rfqs_bp.route("/<int:rfq_id>")
def view_rfq(rfq_id: int):
    rfq = RFQ.query.get_or_404(rfq_id)
    return render_template(
        "rfqs/view.html",
        rfq=rfq,
        chat_context={
            "page": "rfq_view",
            "tender_id": rfq.tender_id,
            "visible_rfq_ids": [rfq.id],
        },
    )


@rfqs_bp.route("/<int:rfq_id>/download")
def download_rfq(rfq_id: int):
    rfq = RFQ.query.get_or_404(rfq_id)
    path = Path(rfq.eml_file_path or "")
    if not path.exists():
        flash("The RFQ EML file is missing.", "danger")
        return redirect(url_for("rfqs.view_rfq", rfq_id=rfq.id))
    return send_file(path, as_attachment=True, download_name=path.name, mimetype="message/rfc822")


@rfqs_bp.route("/<int:rfq_id>/delete", methods=["POST"])
def delete_rfq(rfq_id: int):
    rfq = RFQ.query.get_or_404(rfq_id)
    tender_id = rfq.tender_id
    subject = rfq.subject
    eml_path = Path(rfq.eml_file_path) if rfq.eml_file_path else None
    db.session.delete(rfq)
    db.session.commit()
    if eml_path and eml_path.exists():
        eml_path.unlink()
    flash(f"Deleted RFQ: {subject}.", "success")
    return redirect(url_for("tenders.detail_tender", tender_id=tender_id))
