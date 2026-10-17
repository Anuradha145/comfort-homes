"""Install small app-owned enhancements into the existing custom Web Form."""

from pathlib import Path

import frappe


MARKER = "/* comfort_homes: loan application duplicate customer check */"
CALCULATION_MARKER = "/* comfort_homes: loan application live calculation refresh v2 */"
CALCULATION_SCRIPT = r'''
/* comfort_homes: loan application live calculation refresh v2 */
(function () {
	let refreshTimer;
	let depositSource;
	const purchaseTable = "custom_flexi_purchase_items";
	const incomeTables = new Set([
		"custom_flexi_income_entries", "custom_flexi_living_expenses", "custom_flexi_finance_obligations"
	]);
	const financeFields = new Set([
		"custom_flexi_deposit_amount", "custom_flexi_deposit_percent", "custom_flexi_surcharge_rate",
		"custom_flexi_documentation_fee", "custom_flexi_admin_fee_rate", "custom_flexi_stamp_duty_fee",
		"custom_flexi_other_fee", "custom_flexi_term_months", "custom_flexi_interest_rate",
		"custom_flexi_payment_period", "custom_flexi_selected_dsr", "loan_product"
	]);
	const number = (value) => Number(String(value ?? 0).replace(/,/g, "")) || 0;
	const money = (value) => Math.round((number(value) + Number.EPSILON) * 100) / 100;

	function tableFor(target) {
		return [purchaseTable, ...incomeTables].find((fieldname) =>
			target?.closest?.(`[data-fieldname="${fieldname}"]`)
		);
	}

	function setChildValue(row, fieldname, value) {
		if (money(row[fieldname]) === money(value)) return;
		row[fieldname] = value;
		if (row.doctype && row.name) frappe.model.set_value(row.doctype, row.name, fieldname, value);
	}

	function sourceForDeposit() {
		if (depositSource) return depositSource;
		const amount = number(frappe.web_form.get_value("custom_flexi_deposit_amount"));
		const percent = number(frappe.web_form.get_value("custom_flexi_deposit_percent"));
		return !amount && percent ? "percent" : "amount";
	}

	function recalculate(kind) {
		if (!frappe.web_form) return;
		if (kind === "income") {
			calculateIncomeAndExpenses();
			return;
		}
		if (kind === "purchase") {
			const rows = frappe.web_form.get_value(purchaseTable) || [];
			const purchaseValue = rows.reduce((total, row) => {
				const lineTotal = money(number(row.quantity) * number(row.unit_price));
				setChildValue(row, "total_amount", lineTotal);
				return total + lineTotal;
			}, 0);
			frappe.web_form.set_value("custom_flexi_cash_price", money(purchaseValue));
			frappe.web_form.fields_dict[purchaseTable]?.refresh?.();
		}
		calculateFinanceSummary(sourceForDeposit());
	}

	function queue(kind) {
		window.clearTimeout(refreshTimer);
		// Grid controls finish updating their row a little after the browser event.
		refreshTimer = window.setTimeout(() => recalculate(kind), 450);
	}

	function onChanged(event) {
		const fieldname = event.target?.closest?.("[data-fieldname]")?.dataset?.fieldname;
		const table = tableFor(event.target);
		if (table === purchaseTable) {
			// Remember the initial 10% (or other configured) deposit before the
			// older table listener has a chance to reset it to zero on an empty row.
			depositSource = depositSource || sourceForDeposit();
			return queue("purchase");
		}
		if (incomeTables.has(table)) return queue("income");
		if (!financeFields.has(fieldname)) return;
		if (fieldname === "custom_flexi_deposit_percent") depositSource = "percent";
		if (fieldname === "custom_flexi_deposit_amount") depositSource = "amount";
		queue("finance");
	}

	document.addEventListener("input", onChanged, true);
	document.addEventListener("change", onChanged, true);
})();
'''


def _leaf_cost_center_options():
	"""Return only usable branch/location Cost Centers for public applicants."""
	return frappe.get_all("Cost Center", filters={"is_group": 0}, pluck="name", order_by="name asc")


def _configure_branch_location_field(web_form):
	"""Use a safe dropdown on public forms instead of an unfiltered Link search.

	The underlying Loan Application field stays a Cost Center Link in Desk.  The
	Web Form field is deliberately a Select so a public user can never choose a
	group Cost Center or create/lookup an unintended master record.
	"""
	options = "\n".join(_leaf_cost_center_options())
	for field in web_form.get("web_form_fields") or []:
		if field.fieldname != "custom_branchlocation":
			continue
		field.fieldtype = "Select"
		field.options = options
		field.read_only = 0
		break


def inject_loan_application_duplicate_check():
	"""Safely install the guard in every published Loan Application Web Form."""
	path = Path(__file__).parent / "public" / "js" / "loan_application_duplicate_check.js"
	managed_script = "\n".join([MARKER, path.read_text().strip()])
	web_forms = frappe.get_all(
		"Web Form", filters={"doc_type": "Loan Application", "published": 1}, fields=["name"]
	)
	for row in web_forms:
		web_form = frappe.get_doc("Web Form", row.name)
		_configure_branch_location_field(web_form)
		current_script = web_form.client_script or ""
		# Never rewrite a form already marked as managed. This keeps every
		# customer-authored form script intact on later migrations.
		if MARKER not in current_script:
			# Put the guard first so a later error in the large existing script does
			# not stop the TIN/email duplicate protection from binding.
			current_script = "\n\n".join([managed_script, current_script])
		# This block is appended rather than prepended because it intentionally
		# calls calculation functions declared in the customer-maintained form
		# script. It is idempotent and survives database restores/redeployments.
		if CALCULATION_MARKER not in current_script:
			current_script = "\n\n".join([current_script, CALCULATION_SCRIPT.strip()])
		web_form.client_script = current_script
		web_form.save(ignore_permissions=True)
