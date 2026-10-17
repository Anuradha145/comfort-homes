"""Workflow safeguards for the Flexi Loan Application process."""

import frappe
from frappe import _
from frappe.utils import flt

from comfort_homes.api import _existing_customer_match


CONTRACT_STATES = {"Contract Signing", "Awaiting Customer Signature"}
POST_CONTRACT_STATES = {"Ready for Disbursement", "Signed Contract Pending Compliance"}


def validate_public_application_not_existing_customer(doc, method=None):
	"""Public applications must not create a duplicate customer application."""
	if not frappe.flags.in_web_form:
		return
	match = _existing_customer_match(doc.get("custom_tin_number"), doc.get("applicant_email_address"))
	if match["exists"]:
		matched_by = match.get("matched_by") or []
		identifier = matched_by[0] if len(matched_by) == 1 else _("TIN Number or Email Address")
		frappe.throw(
		_("A customer already exists with this {0}. Please apply from the backend.").format(identifier),
			title=_("Existing Customer"),
		)


def validate_branch_location(doc, method=None):
	"""A branch/location must be a selectable child Cost Center, never a group."""
	branch_location = doc.get("custom_branchlocation")
	if not branch_location:
		return

	if frappe.db.get_value("Cost Center", branch_location, "is_group"):
		frappe.throw(
			_("Select a branch/location Cost Center, not a Cost Center group."),
			title=_("Child Cost Center Required"),
		)


def validate_deposit_invoice(doc, method=None):
	"""A submitted Sales Invoice is required before a deposit-bearing contract progresses."""
	previous = doc.get_doc_before_save()
	if not previous or previous.workflow_state not in CONTRACT_STATES:
		return
	if doc.workflow_state not in POST_CONTRACT_STATES:
		return
	if flt(doc.get("custom_flexi_deposit_amount")) <= 0:
		return

	invoice = frappe.get_all(
		"Sales Invoice",
		filters={"custom_loan_application": doc.name, "docstatus": 1},
		fields=["name"],
		order_by="posting_date desc, modified desc",
		limit_page_length=1,
	)
	if not invoice:
		frappe.throw(
			_("A submitted Sales Invoice for the loan deposit is required before moving from Contract Signing."),
			title=_("Loan Deposit Invoice Required"),
		)
	doc.custom_deposit_sales_invoice = invoice[0].name
