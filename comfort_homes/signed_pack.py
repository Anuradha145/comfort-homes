"""Printable customer-document packs for a Loan Application.

The application itself is the source of truth for customer documents.  Every
individual document button and the combined download use the same configured
``Loan Customer Agreement`` rows and their linked Print Formats.  This module
does not sign, alter, or substitute any documents.
"""

import hashlib
import re
from io import BytesIO
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
	application = frappe.get_doc("Loan Application", loan_application)
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
	application = frappe.get_doc("Loan Application", loan_application)
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
