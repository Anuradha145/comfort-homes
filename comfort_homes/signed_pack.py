"""Printable customer-document packs for a Loan Application.

The application itself is the source of truth for customer documents.  Every
individual document button and the combined download use the same configured
``Loan Customer Agreement`` rows and their linked Print Formats.  This module
does not sign, alter, or substitute any documents.
"""

import hashlib
import re
from io import BytesIO
from pathlib import Path
from urllib.parse import urlencode

import frappe
from frappe import _

try:
	from pypdf import PdfReader, PdfWriter
except ImportError:  # older benches
	from PyPDF2 import PdfReader, PdfWriter

def _agreement_rows(docname):
	rows = frappe.get_all(
		"Loan Customer Agreement",
		filters={"parent": docname, "parenttype": "Loan Application", "parentfield": "custom_customer_documents"},
		fields=["name", "idx", "status", "document_code", "document_template", "final_signed_file", "generated_html"],
		order_by="idx asc",
	)
	result = []
	for row in rows:
		template = frappe.db.get_value(
			"Loan Document Template", row.document_template, ["document_code", "document_name", "print_format"], as_dict=True
		) or {}
		code = row.document_code or template.get("document_code")
		if code == "REQ" or not template.get("print_format"):
			continue
		row.title = template.get("document_name") or code
		row.print_format = template.get("print_format")
		result.append(row)
	return result


@frappe.whitelist()
def get_document_print_url(loan_application, document_template):
	"""Return the print-view URL for one configured customer document.

	The template is verified against the Loan Application child table.  This
	prevents the Desk button from being used to print some unrelated format.
	"""
	application = _set_print_aliases(frappe.get_doc("Loan Application", loan_application))
	frappe.has_permission("Loan Application", "read", doc=application, throw=True)
	row = next((item for item in _agreement_rows(application.name) if item.document_template == document_template), None)
	if not row:
		frappe.throw(_("This document is not configured for the Loan Application."))
	if not frappe.db.exists("Print Format", row.print_format):
		frappe.throw(_("Print Format {0} configured for {1} was not found.").format(row.print_format, row.title))
	return {
		"title": row.title,
		"url": "/printview?" + urlencode(
			{
				"doctype": "Loan Application",
				"name": application.name,
				"format": row.print_format,
				"no_letterhead": 1,
			}
		),
	}


_TEXT = re.compile(r">([^<]+)<")
_EMPTY_VALUES = re.compile(r"(?<![\w.,])(?:None|0\.00?)(?![\w.])")
_LEGACY_LAYOUT_OVERRIDE = re.compile(
	r"\s*<style>\s*/\* Uniform Typography and Layout \*/.*?</style>\s*", re.IGNORECASE | re.DOTALL
)
CUSTOMER_PRINT_FORMATS = (
	"Hire Purchase Agreement",
	"Schedule 1",
	"Form 1",
	"Form 2",
	"Summary of Financial Obligations",
	"Consent Form",
)

# The customer-approved replacements are deliberately stored as app source,
# rather than depending on records that only exist in one site database.  The
# idempotent application setup syncs them after install/fixture sync, ensuring
# a restored site uses the reviewed layouts rather than stale database HTML.
REVIEWED_PRINT_FORMATS = {
	"Test Agreement": "test_agreement.html",
	"Schedule 1 Test": "schedule_1_test.html",
	"Form 1 Test": "form_1_test.html",
	"Form2 Test": "form_2_test.html",
	"Summary Test": "summary_test.html",
	"Consent Test": "consent_test.html",
	"Application Print WIP": "application_print_wip.html",
}

# Keep direct links to the former database-only formats safe during the
# transition.  We do not create these retired names on a new site, but where
# one already exists its HTML is made identical to the reviewed replacement.
# This prevents Desk Print view from disagreeing with Customer Documents.
LEGACY_PRINT_FORMAT_ALIASES = {
	"Hire Purchase Agreement": "test_agreement.html",
	"Schedule 1": "schedule_1_test.html",
	"Form 1": "form_1_test.html",
	"Form 2": "form_2_test.html",
	"Summary of Financial Obligations": "summary_test.html",
	"Consent Form": "consent_test.html",
}

DOCUMENT_PRINT_FORMATS = {
	"HP-AGREEMENT": "Test Agreement",
	"SCHEDULE-1": "Schedule 1 Test",
	"FORM-1": "Form 1 Test",
	"FORM-2": "Form2 Test",
	"FINANCIAL-OBLIGATIONS": "Summary Test",
	"CONSENT-FORM": "Consent Test",
	"APPLICATION-ASSESSMENT": "Application Print WIP",
}

ASSESSMENT_DOCUMENT_CODE = "APPLICATION-ASSESSMENT"
ASSESSMENT_TEMPLATE_VALUES = {
	"name": "LDT-00008",
	"document_code": ASSESSMENT_DOCUMENT_CODE,
	"document_name": "Application Assessment Summary",
	"description": "Internal assessment summary for the complete loan application.",
	"print_format": "Application Print WIP",
	"template_type": "Print Format",
	"status": "Current",
	"sequence": 7,
	"version": 1,
	"requires_signature": 0,
	"requires_customer_read": 0,
	"requires_acknowledgement": 0,
	"requires_director_signature": 0,
}


def sync_reviewed_print_formats():
	"""Sync reviewed, app-owned print documents into a site.

	Called by the idempotent app setup after installation and fixture sync.  It
	is safe to re-run and creates a missing custom format when needed.
	"""
	formats_dir = Path(__file__).with_name("print_formats")
	updated = []
	for format_name, filename in REVIEWED_PRINT_FORMATS.items():
		path = formats_dir / filename
		if not path.exists():
			frappe.throw(_("The app-owned {0} HTML file is missing.").format(format_name))
		html = path.read_text(encoding="utf-8")
		if frappe.db.exists("Print Format", format_name):
			print_format = frappe.get_doc("Print Format", format_name)
			print_format.html = html
			print_format.save(ignore_permissions=True)
		else:
			frappe.get_doc(
				{
					"doctype": "Print Format",
					"name": format_name,
					"doc_type": "Loan Application",
					"print_format_type": "Jinja",
					"custom_format": 1,
					"module": "Loan Management",
					"html": html,
				}
			).insert(ignore_permissions=True)
		updated.append(format_name)

	# Existing direct-print links may still use a former format name.  Update
	# that record in place rather than creating a second layout or leaving a
	# stale legal document reachable from the Desk print menu.
	for format_name, filename in LEGACY_PRINT_FORMAT_ALIASES.items():
		if not frappe.db.exists("Print Format", format_name):
			continue
		path = formats_dir / filename
		legacy_format = frappe.get_doc("Print Format", format_name)
		legacy_format.html = path.read_text(encoding="utf-8")
		legacy_format.save(ignore_permissions=True)
		updated.append(format_name)

	_ensure_assessment_document_template()

	# Customer Documents is driven by Loan Document Template.  Map by stable
	# document code rather than site-specific LDT names, so individual and
	# combined buttons consistently use the reviewed replacement layouts.
	for document_code, format_name in DOCUMENT_PRINT_FORMATS.items():
		for template in frappe.get_all(
			"Loan Document Template", filters={"document_code": document_code}, pluck="name"
		):
			frappe.db.set_value("Loan Document Template", template, "print_format", format_name, update_modified=False)
	frappe.clear_cache(doctype="Loan Application")
	return {"updated_print_formats": updated}


def sync_test_agreement_print_format():
	"""Backward-compatible explicit entry point for the first reviewed format."""
	return sync_reviewed_print_formats()


def _assessment_template():
	"""Return the app-owned assessment template, if its schema is installed."""
	if not frappe.db.exists("DocType", "Loan Document Template"):
		return None
	return frappe.db.get_value(
		"Loan Document Template",
		{"document_code": ASSESSMENT_DOCUMENT_CODE, "status": "Current"},
		["name", "document_code", "version"],
		as_dict=True,
	)


def _ensure_assessment_document_template():
	"""Create/update the seventh, non-signing Customer Document template."""
	if not frappe.db.exists("DocType", "Loan Document Template"):
		return None
	template = _assessment_template()
	if template:
		frappe.db.set_value(
			"Loan Document Template", template.name,
			{key: value for key, value in ASSESSMENT_TEMPLATE_VALUES.items() if key != "name"},
			update_modified=False,
		)
		return _assessment_template()
	return frappe.get_doc({"doctype": "Loan Document Template", **ASSESSMENT_TEMPLATE_VALUES}).insert(
		ignore_permissions=True
	)


def ensure_assessment_customer_document(doc, method=None):
	"""Add the non-signing assessment summary to new or edited applications.

	The row is deliberately idempotent and does not change any existing document
	or signing status.  It makes the assessment available through the same
	individual-print and Download All Documents paths as the six legal forms.
	"""
	template = _assessment_template()
	if not template or not doc.meta.has_field("custom_customer_documents"):
		return
	for row in doc.get("custom_customer_documents") or []:
		if row.document_template == template.name or row.document_code == ASSESSMENT_DOCUMENT_CODE:
			return
	row = doc.append("custom_customer_documents", {})
	row.document_template = template.name
	row.document_code = template.document_code
	row.version = template.version or 1
	row.status = "Pending"


@frappe.whitelist()
def add_assessment_document_to_existing_applications():
	"""Explicit, safe one-time backfill for existing non-cancelled applications.

	It must be deliberately invoked after the reviewed print pack is deployed;
	it does not run during migration and never replaces existing child rows.
	"""
	template = _assessment_template()
	if not template:
		frappe.throw(_("The Application Assessment Summary template is not installed."))

	added = 0
	applications = frappe.get_all("Loan Application", filters={"docstatus": ["!=", 2]}, pluck="name")
	for application_name in applications:
		exists = frappe.db.exists(
			"Loan Customer Agreement",
			{
				"parent": application_name,
				"parenttype": "Loan Application",
				"parentfield": "custom_customer_documents",
				"document_template": template.name,
			},
		)
		if exists:
			continue
		last_row = frappe.get_all(
			"Loan Customer Agreement",
			filters={"parent": application_name, "parentfield": "custom_customer_documents"},
			fields=["idx"],
			order_by="idx desc",
			limit_page_length=1,
		)
		idx = (last_row[0].idx if last_row else 0) + 1
		frappe.get_doc(
			{
				"doctype": "Loan Customer Agreement",
				"parent": application_name,
				"parenttype": "Loan Application",
				"parentfield": "custom_customer_documents",
				"idx": idx,
				"document_template": template.name,
				"document_code": template.document_code,
				"version": template.version or 1,
				"status": "Pending",
			}
		).db_insert()
		added += 1
	frappe.db.commit()
	return {"added": added}


def _set_print_aliases(application):
	"""Provide values used by historic placeholders in legal print layouts."""
	application.hp_account_no = application.get("custom_flexi_hp_account_number") or ""
	application.hp_reference_no = application.get("custom_flexi_quotation_number") or ""
	return application


@frappe.whitelist()
def normalize_customer_print_formats():
	"""Remove the accidental global CSS override from the physical print pack.

	Each legal document defines its own A4 size, margins, typography, borders,
	and tables.  The old appended style overrode all of those rules with
	``!important`` and even removed table borders.  It must not be applied to
	any customer document.
	"""
	updated = []
	for name in CUSTOMER_PRINT_FORMATS:
		if not frappe.db.exists("Print Format", name):
			continue
		print_format = frappe.get_doc("Print Format", name)
		cleaned_html = _LEGACY_LAYOUT_OVERRIDE.sub("\n", print_format.html or "")
		# Direct print URLs load a fresh document, so use the persisted custom
		# fields rather than the aliases created by old signing server scripts.
		cleaned_html = cleaned_html.replace("doc.hp_account_no", "doc.custom_flexi_hp_account_number")
		cleaned_html = cleaned_html.replace("doc.hp_reference_no", "doc.custom_flexi_quotation_number")
		if cleaned_html != (print_format.html or ""):
			print_format.html = cleaned_html
			print_format.save(ignore_permissions=True)
			updated.append(name)

	# Both old Client Scripts open, sequence, or gate electronic signature
	# dialogs.  The app's Desk script replaces them with print-only actions.
	for script_name in ("Flexi Customer Document Signing", "Flexi Customer Document Signing Order"):
		if not frappe.db.exists("Client Script", script_name):
			continue
		client_script = frappe.get_doc("Client Script", script_name)
		if client_script.enabled:
			client_script.enabled = 0
			client_script.save(ignore_permissions=True)

	frappe.clear_cache(doctype="Loan Application")
	frappe.db.commit()
	return {"updated_print_formats": updated, "signing_client_scripts_disabled": True}


def _clear_empty_values(html):
	"""On a blank form, print nothing instead of "None", "0.00" or "0.0" in visible text."""
	return _TEXT.sub(lambda m: ">" + _EMPTY_VALUES.sub("", m.group(1)) + "<", html)


def _file_content(file_url):
	name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not name:
		return None
	return frappe.get_doc("File", name).get_content()


def _join(parts):
	"""Join [{"title", "pdf" or "html"}] into one PDF.

	Returns (pdf_bytes, page_count), or (None, 0) when an HTML part cannot be
	converted because the site has no working PDF engine.
	"""
	writer = PdfWriter()
	for part in parts:
		content = part.get("pdf")
		if content is None:
			try:
				from frappe.utils.pdf import get_pdf

				content = get_pdf(part["html"])
			except Exception:
				frappe.log_error(title="Contract pack: PDF engine unavailable", message=frappe.get_traceback())
				return None, 0
		for page in PdfReader(BytesIO(content)).pages:
			writer.add_page(page)
	output = BytesIO()
	writer.write(output)
	return output.getvalue(), len(writer.pages)


def _attach(application, file_name, content):
	"""Attach the file to the application, replacing any earlier copy of the same name."""
	for old in frappe.get_all(
		"File",
		filters={"attached_to_doctype": "Loan Application", "attached_to_name": application.name, "file_name": file_name},
		pluck="name",
	):
		frappe.delete_doc("File", old, ignore_permissions=True)
	return frappe.get_doc(
		{
			"doctype": "File",
			"file_name": file_name,
			"content": content,
			"is_private": 1,
			"attached_to_doctype": "Loan Application",
			"attached_to_name": application.name,
		}
	).insert(ignore_permissions=True)


def _result(application, file_name, parts):
	content, pages = _join(parts)
	if content is None:
		# No PDF engine on this site: hand back the documents for the browser to print.
		return {"mode": "html", "documents": [{"title": p["title"], "html": p["html"]} for p in parts]}
	file_doc = _attach(application, file_name, content)
	return {"mode": "pdf", "file_url": file_doc.file_url, "documents": [p["title"] for p in parts], "pages": pages}


@frappe.whitelist()
def make_signed_pack(loan_application):
	"""Join every completed agreement's signed copy, in document order, and attach it."""
	application = _set_print_aliases(frappe.get_doc("Loan Application", loan_application))
	frappe.has_permission("Loan Application", "read", doc=application, throw=True)
	_check_collection_complete(application)

	rows = _agreement_rows(application.name)
	if not rows:
		frappe.throw(_("This Loan Application has no customer documents."))
	not_ready = [row.title for row in rows if row.status != "Completed" or not row.final_signed_file]
	if not_ready:
		frappe.throw(
			_("All documents must be fully signed first. Still waiting for: {0}").format(", ".join(not_ready)),
			title=_("Signed pack not ready"),
		)

	parts = []
	for row in rows:
		content = _file_content(row.final_signed_file)
		if content is None:
			frappe.throw(_("The signed copy of {0} could not be found.").format(row.title))
		is_pdf = row.final_signed_file.lower().endswith(".pdf")
		if is_pdf:
			if isinstance(content, str):
				content = content.encode("latin-1")
			parts.append({"title": row.title, "pdf": content, "html": row.generated_html or ""})
		else:
			html = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content
			parts.append({"title": row.title, "html": html})
	return _result(application, "Signed Contract Pack - {0}.pdf".format(application.name), parts)


@frappe.whitelist()
def make_document_pack(loan_application):
	"""Join the exact configured Print Formats for this application into one PDF."""
	application = frappe.get_doc("Loan Application", loan_application)
	frappe.has_permission("Loan Application", "read", doc=application, throw=True)

	rows = _agreement_rows(application.name)
	if not rows:
		frappe.throw(
			_("No printable customer documents are configured for this Loan Application."),
			title=_("No Print Formats configured"),
		)

	parts = []
	for row in rows:
		if not frappe.db.exists("Print Format", row.print_format):
			frappe.throw(
				_("Print Format {0} configured for {1} was not found.").format(row.print_format, row.title),
				title=_("Missing Print Format"),
			)
		html = frappe.get_print("Loan Application", print_format=row.print_format, doc=application, no_letterhead=1)
		parts.append({"title": row.title, "html": html})

	return _result(application, "Customer Documents - {0}.pdf".format(application.name), parts)


@frappe.whitelist()
def make_blank_forms(loan_application):
	"""Compatibility alias retained for existing users of the old button."""
	return make_document_pack(loan_application)
