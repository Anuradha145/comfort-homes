"""Install small app-owned enhancements into the existing custom Web Form."""

from pathlib import Path

import frappe


MARKER = "/* comfort_homes: loan application duplicate customer check */"
CALCULATION_MARKER = "/* comfort_homes: loan application live calculation refresh v3 */"
EMPLOYMENT_MARKER = "/* comfort_homes: loan application employment period */"
EMPLOYMENT_SCRIPT = r'''
/* comfort_homes: loan application employment period */
(function () {
	function updateEmploymentPeriod() {
		const startDate = frappe.web_form.get_value("custom_flexi_employment_start_date");
		if (!startDate) {
			frappe.web_form.set_value("custom_flexi_employment_period", "");
			return;
		}
		const start = new Date(`${startDate}T00:00:00`);
		const now = new Date();
		if (Number.isNaN(start.getTime()) || start > now) return;
		let months = (now.getFullYear() - start.getFullYear()) * 12 + now.getMonth() - start.getMonth();
		if (now.getDate() < start.getDate()) months -= 1;
		months = Math.max(months, 0);
		const years = Math.floor(months / 12);
		const remainder = months % 12;
		const period = `${years} ${years === 1 ? "year" : "years"}${remainder ? ` ${remainder} ${remainder === 1 ? "month" : "months"}` : ""}`;
		frappe.web_form.set_value("custom_flexi_employment_period", period);
	}

	frappe.web_form.on("custom_flexi_employment_start_date", updateEmploymentPeriod);
	frappe.web_form.events.on("after_load", updateEmploymentPeriod);
})();
'''
CALCULATION_SCRIPT = r'''
/* comfort_homes: loan application live calculation refresh v3 */
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
	// Preserve a configured default percentage (for example 10%) before a
	// newly-added blank item row causes the legacy table listener to reset it.
	window.setTimeout(() => {
		if (!depositSource) depositSource = sourceForDeposit();
	}, 0);
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


def _ensure_employment_fields(web_form):
	"""Expose existing employment fields in a useful order on the public form."""
	fields = web_form.get("web_form_fields") or []
	by_name = {field.fieldname: field for field in fields if field.fieldname}

	def ensure(fieldname, **values):
		field = by_name.get(fieldname)
		if not field:
			field = web_form.append("web_form_fields", {"fieldname": fieldname, **values})
			by_name[fieldname] = field
		else:
			for key, value in values.items():
				setattr(field, key, value)
		return field

	start_date = ensure(
		"custom_flexi_employment_start_date", label="Employment Start Date", fieldtype="Date", read_only=0
	)
	history_section = ensure(
		"custom_flexi_employment_history_section", label="Employment History", fieldtype="Section Break", read_only=0
	)
	history = ensure(
		"custom_flexi_employment_history",
		label="Employment History",
		fieldtype="Table",
		options="Flexi Employment History",
		read_only=0,
	)

	def move_after(field, after_fieldname):
		all_fields = web_form.web_form_fields
		if field in all_fields:
			all_fields.remove(field)
		position = next((index for index, item in enumerate(all_fields) if item.fieldname == after_fieldname), len(all_fields) - 1)
		all_fields.insert(position + 1, field)

	# Date belongs beside the existing calculated period. The table follows the
	# current-employer details, before family contacts.
	move_after(start_date, "custom_flexi_employment_column")
	move_after(history_section, "custom_flexi_employer_address")
	move_after(history, "custom_flexi_employment_history_section")
	for index, field in enumerate(web_form.web_form_fields, start=1):
		field.idx = index


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
		_ensure_employment_fields(web_form)
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
		if EMPLOYMENT_MARKER not in current_script:
			current_script = "\n\n".join([current_script, EMPLOYMENT_SCRIPT.strip()])
		web_form.client_script = current_script
		web_form.save(ignore_permissions=True)
