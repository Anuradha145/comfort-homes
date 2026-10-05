"""Workflow safeguards for the Flexi Loan Application process."""

import frappe
from frappe import _
from frappe.utils import flt


CONTRACT_STATES = {"Contract Signing", "Awaiting Customer Signature"}
POST_CONTRACT_STATES = {"Ready for Disbursement", "Signed Contract Pending Compliance"}


def validate_deposit_invoice(doc, method=None):
	"""A submitted Sales Invoice is required before a deposit-bearing contract progresses."""
	previous = doc.get_doc_before_save()
	if not previous or previous.workflow_state not in CONTRACT_STATES:
		return
	if doc.workflow_state not in POST_CONTRACT_STATES:
		return
	if flt(doc.get("custom_flexi_deposit_amount")) <= 0:
		return

	loans = frappe.get_all("Loan", filters={"loan_application": doc.name}, pluck="name")
	invoice = (
		frappe.get_all(
			"Sales Invoice",
			filters={"loan": ["in", loans], "docstatus": 1},
			fields=["name"],
			order_by="posting_date desc, modified desc",
			limit_page_length=1,
		)
		if loans
		else []
	)
	if not invoice:
		frappe.throw(
			_("A submitted Sales Invoice for the loan deposit is required before moving from Contract Signing."),
			title=_("Loan Deposit Invoice Required"),
		)
	doc.custom_deposit_sales_invoice = invoice[0].name
