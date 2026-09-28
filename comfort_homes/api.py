"""Bank-statement import and Loan Repayment actions for Comfort Homes."""

import csv
import re
from datetime import date, datetime
from io import BytesIO, StringIO

import frappe
from frappe import _


DEFAULT_COMPANY = "Comfort Home Furnishing PTE Limited"
CARD_PREFIXES = ("GRA", "NAM", "LTK", "NAU", "DEN", "NOU", "SC")
ALIASES = {
	"date": ("value date", "effective date", "transaction date", "date", "posted date"),
	"description": ("transaction description", "description", "operation", "narration", "details"),
	"credit": ("credit amount", "amount (credit)", "amount credit", "credit (fjd)", "credit", "deposit"),
	"amount": ("amount", "transaction amount"),
}


def _header(value):
	return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _amount(value):
	text = str(value or "").replace(",", "").replace("FJD", "").replace("$", "").strip()
	if not text:
		return 0
	try:
		return float(text.strip("() ")) * (-1 if text.startswith("(") else 1)
	except ValueError:
		return 0


def _date(value):
	if isinstance(value, datetime):
		return value.date()
	if isinstance(value, date):
		return value
	for pattern in ("%d/%m/%Y", "%d/%m/%y", "%d %b %Y", "%d %B %Y", "%Y-%m-%d"):
		try:
			return datetime.strptime(str(value or "").strip(), pattern).date()
		except ValueError:
			pass
	return None


def _mapping(headers):
	lookup = {_header(header): header for header in headers if header}
	return {key: next((lookup[value] for value in names if value in lookup), "") for key, names in ALIASES.items()}


def _table(rows, sheet):
	best = None
	for row_number, row in enumerate(rows[:30]):
		headers = [str(cell).strip() if cell is not None else "" for cell in row]
		non_blank = sum(bool(header) for header in headers)
		if non_blank < 2:
			continue
		mapping = _mapping(headers)
		score = sum(bool(mapping[key]) for key in ("date", "description", "credit", "amount"))
		candidate = (score, non_blank, row_number, headers, mapping)
		if not best or candidate[:2] > best[:2]:
			best = candidate
	if not best:
		return None
	_, _, row_number, headers, mapping = best
	return {"sheet": sheet, "headers": headers, "mapping": mapping, "rows": rows[row_number + 1 :]}


def _tables(content, filename):
	if (filename or "").lower().endswith((".xlsx", ".xlsm")):
		from openpyxl import load_workbook

		book = load_workbook(BytesIO(content), read_only=True, data_only=True)
		tables = [_table(list(sheet.iter_rows(values_only=True)), sheet.title) for sheet in book.worksheets]
	else:
		text = content.decode("utf-8-sig", errors="replace") if isinstance(content, bytes) else content
		try:
			dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
		except csv.Error:
			dialect = csv.excel
		tables = [_table(list(csv.reader(StringIO(text), dialect)), "Statement")]
	tables = [table for table in tables if table]
	if not tables:
		frappe.throw(_("No row with statement columns was found in the attached file."))
	return tables


def _file(doc):
	if not doc.statement_file:
		frappe.throw(_("Attach a CSV or Excel bank statement before importing."))
	name = frappe.db.get_value("File", {"file_url": doc.statement_file}, "name")
	if not name:
		frappe.throw(_("The attached statement file could not be found."))
	file_doc = frappe.get_doc("File", name)
	return file_doc.get_content(), file_doc.file_name or doc.statement_file


def extract_card_id(description):
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


def _customer_and_loan(card_id):
	customers = frappe.get_all("Customer", filters={"custom_card_id": card_id}, fields=["name"], limit_page_length=1) if card_id else []
	if not customers:
		return "", "", 0
	customer = customers[0].name
	loans = frappe.get_all("Loan", filters={"applicant": ["like", f"%{customer}%"], "status": "Disbursed"}, fields=["name"], order_by="disbursement_date desc, modified desc", limit_page_length=20)
	return customer, loans[0].name if len(loans) == 1 else "", len(loans)


@frappe.whitelist()
def analyse_statement(name):
	doc = frappe.get_doc("Loan Bank Reconciliation", name)
	content, filename = _file(doc)
	tables = _tables(content, filename)
	return {"file_name": filename, "columns": tables[0]["headers"], "mapping": tables[0]["mapping"], "sheets": [table["sheet"] for table in tables]}


def _payment_account(bank_account):
	bank = frappe.db.get_value("Bank Account", bank_account, ["account", "disabled", "is_company_account"], as_dict=True)
	if not bank or bank.disabled or not bank.is_company_account or not bank.account:
		frappe.throw(_("Select an active company Bank Account with a linked ledger account."))
	return bank.account


@frappe.whitelist()
def loan_reconciliation(name, action, mapping=None):
	doc = frappe.get_doc("Loan Bank Reconciliation", name)
	if doc.docstatus:
		frappe.throw(_("Only a draft reconciliation can be changed."))
	if action == "import_statement":
		return import_statement(doc, frappe.parse_json(mapping) if mapping else None)
	if action == "create_repayments":
		return create_repayments(doc)
	frappe.throw(_("A valid reconciliation action is required."))


def import_statement(doc, mapping):
	if any(row.loan_repayment for row in doc.transactions):
		frappe.throw(_("Create a new reconciliation for another import after repayments have been created."))
	content, filename = _file(doc)
	tables = _tables(content, filename)
	mapping = mapping or tables[0]["mapping"]
	if not mapping.get("date") or not mapping.get("description") or not (mapping.get("credit") or mapping.get("amount")):
		frappe.throw(_("Choose transaction date, description, and credit or amount columns."))
	doc.transactions = []
	imported = ready = review = 0
	for table in tables:
		for values in table["rows"]:
			row = {header: values[index] if index < len(values) else "" for index, header in enumerate(table["headers"])}
			transaction_date = _date(row.get(mapping["date"]))
			description = str(row.get(mapping["description"]) or "").strip()
			amount = _amount(row.get(mapping.get("credit"))) if mapping.get("credit") else _amount(row.get(mapping.get("amount")))
			if not transaction_date or not description or amount <= 0:
				continue
			card_id = extract_card_id(description)
			customer, loan, count = _customer_and_loan(card_id)
			status = "Ready" if loan else "Choose Loan" if customer and count > 1 else "No Disbursed Loan" if customer else "Unmatched"
			ready += int(bool(loan)); review += int(not loan)
			doc.append("transactions", {"transaction_date": transaction_date, "description": description, "amount": amount, "customer_card_id": card_id, "customer": customer, "suggested_loan": loan, "loan": loan, "selected": int(bool(loan)), "status": status})
			imported += 1
	doc.update({"status": "Imported", "imported_transactions": imported, "ready_transactions": ready, "review_transactions": review})
	doc.save(ignore_permissions=True)
	return {"imported": imported, "ready": ready, "review": review, "format": filename}


def create_repayments(doc):
	account = _payment_account(doc.bank_account)
	created = skipped = 0
	errors = []
	for row in doc.transactions:
		if not row.selected or row.loan_repayment:
			continue
		loan = row.loan or row.suggested_loan
		if not loan:
			row.status = "Choose Loan"; skipped += 1
			continue
		try:
			repayment = frappe.get_doc({"doctype": "Loan Repayment", "against_loan": loan, "company": doc.company or DEFAULT_COMPANY, "posting_date": row.transaction_date, "value_date": row.transaction_date, "amount_paid": row.amount, "cost_center": "HQ - CHFPL", "repayment_type": "Normal Repayment", "payment_account": account})
			repayment.insert(ignore_permissions=True); repayment.submit()
			row.update({"loan": loan, "loan_repayment": repayment.name, "status": "Loan Repayment Created"}); created += 1
		except Exception as error:
			row.status = "Error"; errors.append(f"{row.customer_card_id or row.name}: {str(error)[:120]}")
	posted = sum(bool(row.loan_repayment) for row in doc.transactions)
	doc.update({"created_repayments": posted, "status": "Reconciled" if posted and posted == len(doc.transactions) else "Partially Reconciled"})
	doc.save(ignore_permissions=True)
	return {"created": created, "skipped": skipped, "errors": errors[:10]}
