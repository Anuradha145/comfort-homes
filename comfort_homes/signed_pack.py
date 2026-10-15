"""Contract pack downloads for a Loan Application.

* make_signed_pack  - every completed agreement's signed copy joined into one PDF.
* make_blank_forms  - every agreement form, completely blank, joined into one PDF.

The Loan Application's "Download PDF With Signed Documents?" field chooses which
one is offered: Yes -> signed pack (all documents Completed), No -> blank forms.
"""

import hashlib
import re
from io import BytesIO

import frappe
from frappe import _

try:
	from pypdf import PdfReader, PdfWriter
except ImportError:  # older benches
	from PyPDF2 import PdfReader, PdfWriter

COLLECTION_LABEL = "download pdf with signed documents"
# Used for blank forms when an application has no agreement rows yet.
DEFAULT_FORMS = (
	"Hire Purchase Agreement",
	"Schedule 1",
	"Form 1",
	"Form 2",
	"Summary of Financial Obligations",
	"Consent Form",
)


def _collection_fieldname():
	for df in frappe.get_meta("Loan Application").fields:
		if (df.label or "").strip().lower().startswith(COLLECTION_LABEL):
			return df.fieldname
	return None


def _check_collection_complete(application):
	fieldname = _collection_fieldname()
	if fieldname and str(application.get(fieldname) or "").strip().lower() not in ("yes", "1"):
		frappe.throw(
			_("Set \"Download PDF With Signed Documents?\" to Yes to download the signed pack."),
			title=_("Signed documents not selected"),
		)


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
		if code == "REQ":
			continue
		row.title = template.get("document_name") or code
		row.print_format = template.get("print_format")
		result.append(row)
	return result


_TEXT = re.compile(r">([^<]+)<")
_EMPTY_VALUES = re.compile(r"(?<![\w.,])(?:None|0\.00?)(?![\w.])")


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
def make_blank_forms(loan_application):
	"""Every agreement form with no customer details at all, joined into one PDF."""
	application = frappe.get_doc("Loan Application", loan_application)
	frappe.has_permission("Loan Application", "read", doc=application, throw=True)

	rows = _agreement_rows(application.name)
	forms = [(row.title, row.print_format) for row in rows if row.print_format] or [
		(name, name) for name in DEFAULT_FORMS
	]

	forms = [(title, pf) for title, pf in forms if frappe.db.exists("Print Format", pf)]
	if not forms:
		frappe.throw(_("None of the contract print formats were found."))
	titles = [title for title, _pf in forms]

	# Blank forms are identical for every application, so build them once and reuse
	# the file until one of the print formats is edited.
	version = "|".join(
		"{0}@{1}".format(pf, frappe.db.get_value("Print Format", pf, "modified")) for _t, pf in forms
	)
	file_name = "Blank Contract Forms - {0}.pdf".format(hashlib.md5(version.encode()).hexdigest()[:10])
	cached = frappe.db.get_value("File", {"file_name": file_name, "is_private": 0}, "file_url")
	if cached:
		return {"mode": "pdf", "file_url": cached, "documents": titles, "pages": None}

	parts = []
	for title, print_format in forms:
		blank = frappe.new_doc("Loan Application")
		blank.name = ""
		blank.company = application.company
		html = frappe.get_print("Loan Application", print_format=print_format, doc=blank, no_letterhead=1)
		parts.append({"title": title, "html": _clear_empty_values(html)})

	content, pages = _join(parts)
	if content is None:
		return {"mode": "html", "documents": parts}
	# Public: the blank forms hold no customer data, and every user can reuse the same file.
	file_doc = frappe.get_doc(
		{"doctype": "File", "file_name": file_name, "content": content, "is_private": 0}
	).insert(ignore_permissions=True)
	return {"mode": "pdf", "file_url": file_doc.file_url, "documents": titles, "pages": pages}