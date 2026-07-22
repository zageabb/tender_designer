from __future__ import annotations

from pathlib import Path

from flask import Blueprint, current_app, flash, redirect, render_template, request, send_file, url_for

from database import db
from models import Tender, TenderDocument, TenderEmail
from services.mailbox_service import send_eml_file
from services.tender_email_service import build_tender_email_defaults, create_tender_email_draft, write_tender_email_eml


tender_emails_bp = Blueprint("tender_emails", __name__, url_prefix="/tender-emails")


def _selected_documents_for_tender(tender: Tender, selected_document_ids: list[int]) -> list[TenderDocument]:
    selected_ids = set(selected_document_ids)
    return [document for document in tender.documents if document.id in selected_ids]


@tender_emails_bp.route("/tender/<int:tender_id>/new", methods=["GET", "POST"])
def create_tender_email(tender_id: int):
    tender = Tender.query.get_or_404(tender_id)
    selected_document_ids = request.values.getlist("document_ids", type=int)
    selected_documents = _selected_documents_for_tender(tender, selected_document_ids)
    if request.method == "POST" and request.form.get("save_draft") == "1":
        recipient_email = request.form.get("recipient_email", "").strip()
        subject = request.form.get("subject", "").strip()
        body_text = request.form.get("body_text", "").strip()
        if not selected_documents:
            flash("Select at least one valid document before creating an email draft.", "warning")
            return redirect(url_for("tenders.detail_tender", tender_id=tender.id, _anchor="documents"))
        if not recipient_email or not subject or not body_text:
            flash("Recipient email, subject, and body are required.", "warning")
            return render_template(
                "tender_emails/form.html",
                tender=tender,
                selected_documents=selected_documents,
                recipient_email=recipient_email,
                subject=subject,
                body_text=body_text,
                chat_context={"page": "tender_email_create", "tender_id": tender.id},
            )
        try:
            tender_email = create_tender_email_draft(
                db,
                current_app.config["DATA_DIR"],
                tender,
                selected_documents,
                recipient_email,
                subject,
                body_text,
            )
            db.session.commit()
        except FileNotFoundError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
            return render_template(
                "tender_emails/form.html",
                tender=tender,
                selected_documents=selected_documents,
                recipient_email=recipient_email,
                subject=subject,
                body_text=body_text,
                chat_context={"page": "tender_email_create", "tender_id": tender.id},
            )
        flash("Tender email draft created.", "success")
        return redirect(url_for("tender_emails.view_tender_email", tender_email_id=tender_email.id))

    if not selected_documents:
        flash("Select at least one document before creating an email draft.", "warning")
        return redirect(url_for("tenders.detail_tender", tender_id=tender.id, _anchor="documents"))

    recipient_email = request.form.get("recipient_email", "").strip()
    subject = request.form.get("subject", "").strip()
    body_text = request.form.get("body_text", "").strip()
    if not subject or not body_text:
        subject, body_text = build_tender_email_defaults(tender, selected_documents, recipient_email=recipient_email)
    return render_template(
        "tender_emails/form.html",
        tender=tender,
        selected_documents=selected_documents,
        recipient_email=recipient_email,
        subject=subject,
        body_text=body_text,
        chat_context={"page": "tender_email_create", "tender_id": tender.id},
    )


@tender_emails_bp.route("/<int:tender_email_id>")
def view_tender_email(tender_email_id: int):
    tender_email = TenderEmail.query.get_or_404(tender_email_id)
    return render_template(
        "tender_emails/view.html",
        tender_email=tender_email,
        chat_context={"page": "tender_email_view", "tender_id": tender_email.tender_id},
    )


@tender_emails_bp.route("/<int:tender_email_id>/edit", methods=["GET", "POST"])
def edit_tender_email(tender_email_id: int):
    tender_email = TenderEmail.query.get_or_404(tender_email_id)
    documents = [link.tender_document for link in tender_email.documents]
    if request.method == "POST":
        tender_email.recipient_email = request.form.get("recipient_email", "").strip() or None
        tender_email.subject = request.form.get("subject", "").strip() or tender_email.subject
        tender_email.body_text = request.form.get("body_text", "").strip() or ""
        tender_email.status = request.form.get("status", "").strip() or "Draft"
        tender_email.notes = request.form.get("notes", "").strip() or None
        try:
            email_path = write_tender_email_eml(
                current_app.config["DATA_DIR"],
                tender_email.tender,
                tender_email,
                documents,
            )
        except FileNotFoundError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
            return render_template(
                "tender_emails/edit.html",
                tender_email=tender_email,
                documents=documents,
                chat_context={"page": "tender_email_edit", "tender_id": tender_email.tender_id},
            )
        tender_email.eml_file_path = str(email_path)
        db.session.commit()
        flash("Tender email draft updated.", "success")
        return redirect(url_for("tender_emails.view_tender_email", tender_email_id=tender_email.id))
    return render_template(
        "tender_emails/edit.html",
        tender_email=tender_email,
        documents=documents,
        chat_context={"page": "tender_email_edit", "tender_id": tender_email.tender_id},
    )


@tender_emails_bp.route("/<int:tender_email_id>/download")
def download_tender_email(tender_email_id: int):
    tender_email = TenderEmail.query.get_or_404(tender_email_id)
    path = Path(tender_email.eml_file_path or "")
    if not path.exists():
        flash("The tender email EML file is missing.", "danger")
        return redirect(url_for("tender_emails.view_tender_email", tender_email_id=tender_email.id))
    return send_file(path, as_attachment=True, download_name=path.name, mimetype="message/rfc822")


@tender_emails_bp.route("/<int:tender_email_id>/send", methods=["POST"])
def send_tender_email(tender_email_id: int):
    tender_email = TenderEmail.query.get_or_404(tender_email_id)
    try:
        send_eml_file(tender_email.eml_file_path or "")
        tender_email.status = "Sent Direct"
        db.session.commit()
        flash(f"Tender email sent directly to {tender_email.recipient_email or 'the configured recipient list'}.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Direct send failed: {exc}", "danger")
    return redirect(url_for("tender_emails.view_tender_email", tender_email_id=tender_email.id))


@tender_emails_bp.route("/<int:tender_email_id>/delete", methods=["POST"])
def delete_tender_email(tender_email_id: int):
    tender_email = TenderEmail.query.get_or_404(tender_email_id)
    tender_id = tender_email.tender_id
    subject = tender_email.subject
    eml_path = Path(tender_email.eml_file_path) if tender_email.eml_file_path else None
    db.session.delete(tender_email)
    db.session.commit()
    if eml_path and eml_path.exists():
        eml_path.unlink()
    flash(f"Deleted tender email draft: {subject}.", "success")
    return redirect(url_for("tenders.detail_tender", tender_id=tender_id, _anchor="tender-emails"))
