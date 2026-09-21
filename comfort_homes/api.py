"""Whitelisted server actions for Comfort Homes."""

import csv
from datetime import datetime
from io import StringIO

import frappe
from frappe import _


DEFAULT_COMPANY = "Comfort Home Furnishing PTE Limited"
CARD_PREFIXES = ("GRA", "NAM", "LTK", "NAU", "DEN", "NOU", "SC2")


def extract_card_id(description):
	"""Return the known customer card reference embedded in BSP narration."""
	text = (description or "").upper()
	for prefix in CARD_PREFIXES:
		start = text.find(prefix)
		if start < 0:
			continue
		value = ""
		for character in text[start:]:
			if character.isalnum():
				value += character
			else:
				break
		if len(value) >= 7:
			return value
	return ""


def get_customer_and_loan(card_id):
	if not card_id:
		return "", "", 0
	customers = frappe.get_all("Customer", filters={"custom_card_id": card_id}, fields=["name"], limit_page_length=1)
	if not customers:
		return "", "", 0
	customer = customers[0].name
	loans = frappe.get_all(
		"Loan",
		filters={"applicant": ["like", f"%{customer}%"], "status": "Disbursed"},
		fields=["name"],
		order_by="disbursement_date desc, modified desc",
		limit_page_length=20,
	)
	return customer, loans[0].name if len(loans) == 1 else "", len(loans)


def parse_bsp_date(value):
	try:
		return datetime.strptime((value or "").strip(), "%d/%m/%Y").date()
	except ValueError:
		return None


def get_payment_account(bank_account):
	"""Use the Account selected on the reconciliation, including old imports."""
	if frappe.db.exists("Account", bank_account):
		return bank_account

	# Reconciliations created before v16.0.2 stored a display label rather than
	# the Account document name. Resolve it only when there is one clear match.
	matches = frappe.get_all(
		"Account",
		filters={"name": ["like", f"%{bank_account}%"], "is_group": 0},
		pluck="name",
		limit_page_length=2,
	)
	if len(matches) == 1:
		return matches[0]
	frappe.throw(_("Select a valid ledger Account in Bank Account before creating repayments."))


@frappe.whitelist()
def loan_reconciliation(name, action):
	"""Import BSP credits or create repayments for loan-officer selected rows."""
	if action not in {"import_statement", "create_repayments"}:
		frappe.throw(_("A valid reconciliation action is required."))
	doc = frappe.get_doc("Loan Bank Reconciliation", name)
	if doc.docstatus != 0:
		frappe.throw(_("Only a draft reconciliation can be changed."))
	return import_statement(doc) if action == "import_statement" else create_repayments(doc)


def import_statement(doc):
	if not doc.statement_file:
		frappe.throw(_("Attach the BSP statement CSV before importing."))
	if any(row.loan_repayment for row in doc.transactions):
		frappe.throw(_("Create a new reconciliation for another import after repayments have been created."))
	files = frappe.get_all("File", filters={"file_url": doc.statement_file}, fields=["name"], limit_page_length=1)
	if not files:
		frappe.throw(_("The attached statement file could not be found."))
	content = frappe.get_doc("File", files[0].name).get_content()
	if isinstance(content, bytes):
		content = content.decode("latin-1")
	reader = csv.DictReader(StringIO(content))
	required = {"Date", "Description", "Credit (FJD)"}
	if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
		missing = ", ".join(sorted(required - set(reader.fieldnames or [])))
		frappe.throw(_("This import accepts the BSP CSV format. Missing column(s): {0}").format(missing))
	doc.transactions = []
	imported = ready = review = 0
	for source in reader:
		try:
			amount = float((source.get("Credit (FJD)") or "").replace(",", "").strip())
		except (TypeError, ValueError):
			continue
		if amount <= 0:
			continue
		card_id = extract_card_id(source.get("Description"))
		customer, suggested_loan, loan_count = get_customer_and_loan(card_id)
		if suggested_loan:
			status = "Ready"
			ready += 1
		elif customer and loan_count > 1:
			status = "Choose Loan"
			review += 1
		elif customer:
			status = "No Disbursed Loan"
			review += 1
		else:
			status = "Unmatched"
			review += 1
		doc.append("transactions", {"transaction_date": parse_bsp_date(source.get("Date")), "description": source.get("Description") or "", "amount": amount, "customer_card_id": card_id, "customer": customer, "suggested_loan": suggested_loan, "loan": suggested_loan, "selected": int(bool(suggested_loan)), "status": status})
		imported += 1
	doc.update({"status": "Imported", "imported_transactions": imported, "ready_transactions": ready, "review_transactions": review})
	doc.save(ignore_permissions=True)
	return {"imported": imported, "ready": ready, "review": review}


def create_repayments(doc):
	account = get_payment_account(doc.bank_account)
	created = skipped = 0
	errors = []
	for row in doc.transactions:
		if not row.selected or row.loan_repayment:
			continue
		loan = row.loan or row.suggested_loan
		if not loan:
			row.status = "Choose Loan"
			skipped += 1
			continue
		try:
			repayment = frappe.get_doc({"doctype": "Loan Repayment", "against_loan": loan, "company": doc.company or DEFAULT_COMPANY, "posting_date": row.transaction_date, "value_date": row.transaction_date, "amount_paid": row.amount, "cost_center": "HQ - CHFPL", "repayment_type": "Normal Repayment", "payment_account": account})
			repayment.insert(ignore_permissions=True)
			repayment.submit()
			row.update({"loan": loan, "loan_repayment": repayment.name, "status": "Loan Repayment Created"})
			created += 1
		except Exception as error:
			row.status = "Error"
			errors.append(f"{row.customer_card_id or row.name}: {str(error)[:120]}")
	posted = sum(bool(row.loan_repayment) for row in doc.transactions)
	doc.update({"created_repayments": posted, "status": "Reconciled" if posted and posted == len(doc.transactions) else "Partially Reconciled"})
	doc.save(ignore_permissions=True)
	return {"created": created, "skipped": skipped, "errors": errors[:10]}
