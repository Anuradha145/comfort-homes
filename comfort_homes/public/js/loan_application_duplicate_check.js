/* Public Loan Application guard: existing customers are handled by staff. */
(function () {
	if (window.__comfortHomesDuplicateCheckLoaded) return;
	window.__comfortHomesDuplicateCheckLoaded = true;

	let duplicateCheckBound = false;
	let submissionApproved = false;
	let checkingDuplicate = false;
	let duplicateFound = false;
	let fieldChecksBound = false;
	let fieldInputChecksBound = false;
	let documentInputChecksBound = false;
	let lookupTimer;
	let lookupSequence = 0;
	let duplicateMatch = [];

	function duplicateMessage(matchedBy = duplicateMatch) {
		if (window.__comfortHomesExistingCoApplicant) {
			return __("A matching Co-Applicant already exists. Please apply from the backend.");
		}
		const identifier = matchedBy.length === 1
			? matchedBy[0]
			: "TIN Number or Email Address";
		return __(
			"A customer already exists with this {0}. Please apply from the backend.",
			[identifier]
		);
	}

	function updateProgressAccess() {
		const blocked = duplicateFound;
		document.querySelectorAll(".btn-next, .submit-btn").forEach((button) => {
			button.disabled = blocked;
			button.setAttribute("aria-disabled", blocked ? "true" : "false");
			button.classList.toggle("disabled", blocked);
		});
	}

	function valueFromInput(fieldname) {
		const input = frappe.web_form.fields_dict[fieldname]?.wrapper?.querySelector("input");
		return String(input?.value ?? frappe.web_form.get_value(fieldname) ?? "").trim();
	}

	function checkExistingCustomer(showMessage) {
		if (!isLoanApplicationWebForm()) return Promise.resolve(false);
		const sequence = ++lookupSequence;
		return frappe.call({
			method: "comfort_homes.api.check_existing_customer",
			args: {
				tin_number: valueFromInput("custom_tin_number"),
				email: valueFromInput("applicant_email_address"),
			},
		}).then((response) => {
			if (sequence !== lookupSequence) return duplicateFound;
			const match = response.message || {};
			duplicateFound = Boolean(match.exists);
			window.__comfortHomesExistingCoApplicant = Boolean(match.co_applicant_exists);
			duplicateMatch = match.matched_by || [];
			updateProgressAccess();
			if (duplicateFound && showMessage) {
				frappe.msgprint({
					title: __("Existing customer"),
					message: duplicateMessage(),
					indicator: "orange",
				});
			}
			return duplicateFound;
		});
	}

	function isLoanApplicationWebForm() {
		return window.location.pathname.replace(/\/$/, "").startsWith("/loan-application") && window.frappe?.web_form;
	}

	function bindDuplicateCheck() {
		if (!isLoanApplicationWebForm() || duplicateCheckBound) return;
		const button = document.querySelector(".submit-btn");
		if (!button) {
			window.setTimeout(bindDuplicateCheck, 150);
			return;
		}
		duplicateCheckBound = true;
		button.addEventListener("click", (event) => {
			if (submissionApproved) {
				submissionApproved = false;
				return;
			}
			if (checkingDuplicate) {
				event.preventDefault();
				event.stopImmediatePropagation();
				return;
			}

			event.preventDefault();
			event.stopImmediatePropagation();
			checkingDuplicate = true;
			checkExistingCustomer(false).then((exists) => {
					checkingDuplicate = false;
					if (exists) {
						frappe.msgprint({
							title: __("Existing customer"),
							message: duplicateMessage(),
							indicator: "orange",
						});
						return;
					}
					submissionApproved = true;
					button.click();
				}).catch(() => {
					checkingDuplicate = false;
					frappe.msgprint(__("We could not validate existing customer details. Please try again."));
			});
		}, true);
	}

	function bindFieldChecks() {
		if (!isLoanApplicationWebForm() || fieldChecksBound) return;
		fieldChecksBound = true;
		["custom_tin_number", "applicant_email_address"].forEach((fieldname) => {
			frappe.web_form.on(fieldname, () => checkExistingCustomer(true));
		});
	}

	function bindImmediateInputChecks() {
		if (!isLoanApplicationWebForm() || fieldInputChecksBound) return;
		const inputs = ["custom_tin_number", "applicant_email_address"]
			.map((fieldname) => frappe.web_form.fields_dict[fieldname]?.wrapper?.querySelector("input"))
			.filter(Boolean);
		if (inputs.length !== 2) {
			window.setTimeout(bindImmediateInputChecks, 150);
			return;
		}
		fieldInputChecksBound = true;
		inputs.forEach((input) => {
			input.addEventListener("input", () => {
				window.clearTimeout(lookupTimer);
				lookupTimer = window.setTimeout(() => checkExistingCustomer(true), 500);
			});
			input.addEventListener("blur", () => {
				window.clearTimeout(lookupTimer);
				checkExistingCustomer(true);
			});
		});
	}

	function bindDocumentInputChecks() {
		if (documentInputChecksBound) return;
		documentInputChecksBound = true;
		const changed = (event) => {
			const fieldname = event.target?.closest?.("[data-fieldname]")?.dataset?.fieldname;
			if (!["custom_tin_number", "applicant_email_address"].includes(fieldname)) return;
			window.clearTimeout(lookupTimer);
			if (event.type === "change" || event.type === "blur") {
				checkExistingCustomer(true);
			} else {
				lookupTimer = window.setTimeout(() => checkExistingCustomer(true), 500);
			}
		};
		// Capturing listeners work even if another Web Form script fails later.
		document.addEventListener("input", changed, true);
		document.addEventListener("change", changed, true);
	}

	function initialiseWhenReady() {
		if (!window.location.pathname.replace(/\/$/, "").startsWith("/loan-application")) return;
		if (!window.frappe?.web_form?.events) {
			window.setTimeout(initialiseWhenReady, 150);
			return;
		}
		frappe.web_form.events.on("after_load", () => {
			bindDuplicateCheck();
			bindFieldChecks();
			bindImmediateInputChecks();
		});
		// If this asset is injected after the Web Form has already loaded,
		// attach immediately as well.
		window.setTimeout(() => {
			bindDuplicateCheck();
			bindFieldChecks();
			bindImmediateInputChecks();
		}, 300);
	}

	initialiseWhenReady();
	bindDocumentInputChecks();
})();

/*
 * Public loan application calculation refresh.
 *
 * Web Form child tables do not consistently emit `frappe.web_form.on` events
 * while a user is typing.  The application already owns the finance formula
 * (`calculateFinanceSummary`); this small bridge only makes sure that formula
 * is run after the grid has accepted the user's latest value.
 */
(function () {
	if (window.__comfortHomesLoanCalculationRefreshLoaded) return;
	window.__comfortHomesLoanCalculationRefreshLoaded = true;

	let refreshTimer;
	// No source is assumed until the applicant explicitly changes a deposit
	// field.  A form that starts with 10% and zero dollars must calculate the
	// deposit from the percentage once purchase items are entered.
	let depositSource;
	const purchaseTable = "custom_flexi_purchase_items";
	const incomeTables = new Set([
		"custom_flexi_income_entries",
		"custom_flexi_living_expenses",
		"custom_flexi_finance_obligations",
	]);
	const financeFields = new Set([
		"custom_flexi_deposit_amount",
		"custom_flexi_deposit_percent",
		"custom_flexi_surcharge_rate",
		"custom_flexi_documentation_fee",
		"custom_flexi_admin_fee_rate",
		"custom_flexi_stamp_duty_fee",
		"custom_flexi_other_fee",
		"custom_flexi_term_months",
		"custom_flexi_interest_rate",
		"custom_flexi_payment_period",
		"custom_flexi_selected_dsr",
		"loan_product",
	]);

	function isLoanApplicationWebForm() {
		return window.location.pathname.replace(/\/$/, "").startsWith("/loan-application") && window.frappe?.web_form;
	}

	function number(value) {
		const parsed = Number(String(value ?? "").replace(/[^0-9.-]/g, ""));
		return Number.isFinite(parsed) ? parsed : 0;
	}

	function money(value) {
		return Math.round((number(value) + Number.EPSILON) * 100) / 100;
	}

	function tableFor(target) {
		return [purchaseTable, ...incomeTables].find((fieldname) =>
			target?.closest?.(`[data-fieldname="${fieldname}"]`)
		);
	}

	function setChildValue(row, fieldname, value) {
		if (money(row[fieldname]) === money(value)) return;
		row[fieldname] = value;
		if (row.doctype && row.name && frappe.model?.set_value) {
			frappe.model.set_value(row.doctype, row.name, fieldname, value);
		}
	}

	function synchronisePurchaseRows() {
		const form = frappe.web_form;
		const rows = form.get_value(purchaseTable) || [];
		const purchaseValue = rows.reduce((total, row) => {
			const lineTotal = money(number(row.quantity) * number(row.unit_price));
			setChildValue(row, "total_amount", lineTotal);
			return total + lineTotal;
		}, 0);
		form.set_value("custom_flexi_cash_price", money(purchaseValue));
		form.fields_dict[purchaseTable]?.refresh?.();
	}

	function triggerFormCalculation(fieldname) {
		const events = frappe.web_form?.events;
		if (events?.trigger) {
			events.trigger(fieldname);
			return true;
		}
		return false;
	}

	function currentDepositSource() {
		if (depositSource) return depositSource;
		const amount = number(frappe.web_form.get_value("custom_flexi_deposit_amount"));
		const percent = number(frappe.web_form.get_value("custom_flexi_deposit_percent"));
		return !amount && percent ? "percent" : "amount";
	}

	function monthlyFactor(frequency) {
		return ({ Weekly: 52 / 12, Fortnightly: 26 / 12, "Bi-monthly": 2, Monthly: 1 })[frequency] || 1;
	}

	function setValue(fieldname, value) {
		if (!frappe.web_form.fields_dict[fieldname]) return;
		const current = frappe.web_form.get_value(fieldname);
		if (typeof value === "number" && money(current) === money(value)) return;
		if (current === value) return;
		frappe.web_form.set_value(fieldname, value);
	}

	function updateHirePurchaseOptionTable(values) {
		const rows = document.querySelectorAll(".flexi-hp-options-table tbody tr");
		if (rows.length < 2) return;
		const keys = ["weekly", "fortnightly", "bimonthly", "monthly"];
		keys.forEach((key, index) => {
			const count = rows[0].children[index + 1];
			const amount = rows[1].children[index + 1];
			if (count) count.textContent = String(values[`${key}_instalments`]);
			if (amount) amount.textContent = `FJD ${money(values[`${key}_instalment_amount`]).toLocaleString(undefined, {
				minimumFractionDigits: 2, maximumFractionDigits: 2,
			})}`;
		});
	}

	function calculateIncomeValues() {
		const form = frappe.web_form;
		const incomeRows = form.get_value("custom_flexi_income_entries") || [];
		const expenseRows = form.get_value("custom_flexi_living_expenses") || [];
		const obligationRows = form.get_value("custom_flexi_finance_obligations") || [];
		const income = incomeRows.reduce((sum, row) => {
			const monthlyAmount = money(number(row.amount) * monthlyFactor(row.frequency));
			setChildValue(row, "monthly_amount", monthlyAmount);
			return sum + (row.income_type === "Salary Deductions" ? Math.abs(monthlyAmount) : monthlyAmount);
		}, 0);
		const expenses = expenseRows.reduce((sum, row) => {
			const monthlyAmount = money(number(row.expense_amount) * number(row.frequency_per_month || 1));
			setChildValue(row, "monthly_amount", monthlyAmount);
			return sum + monthlyAmount;
		}, 0);
		const obligations = obligationRows.reduce((sum, row) => {
			const monthlyAmount = money(number(row.amount) * monthlyFactor(row.frequency));
			setChildValue(row, "monthly_amount", monthlyAmount);
			return sum + monthlyAmount;
		}, 0);
		setValue("custom_flexi_total_monthly_income", money(income));
		setValue("custom_flexi_total_annual_income", money(income * 12));
		setValue("custom_flexi_total_monthly_expenses", money(expenses));
		setValue("custom_flexi_net_monthly_income", money(income - expenses));
		setValue("custom_flexi_dsr_total_income", money(income));
		setValue("custom_flexi_total_finance_obligations", money(obligations));
		setValue("custom_flexi_dsr_net_income", money(income - obligations));
		const maxDsr = number(form.get_value("custom_flexi_selected_dsr")) || 35;
		const preDsr = income ? money(obligations / income * 100) : 0;
		setValue("custom_flexi_pre_dsr", preDsr);
		setValue("custom_flexi_dsr_margin", money(Math.max(maxDsr - preDsr, 0)));
		setValue("custom_flexi_weekly_eligibility", money(Math.max((income * maxDsr / 100 - obligations) * 12 / 52, 0)));
		form.fields_dict.custom_flexi_income_entries?.refresh?.();
		form.fields_dict.custom_flexi_living_expenses?.refresh?.();
		form.fields_dict.custom_flexi_finance_obligations?.refresh?.();
		return { income, obligations };
	}

	function calculateFinanceValues(assessment = {}) {
		const form = frappe.web_form;
		const items = form.get_value(purchaseTable) || [];
		const purchaseValue = money(items.reduce((sum, row) => sum + number(row.quantity) * number(row.unit_price), 0));
		items.forEach((row) => setChildValue(row, "total_amount", money(number(row.quantity) * number(row.unit_price))));
		const surchargeRate = Math.max(number(form.get_value("custom_flexi_surcharge_rate")), 0);
		const surchargeAmount = money(purchaseValue * surchargeRate / 100);
		const source = currentDepositSource();
		const enteredPercent = number(form.get_value("custom_flexi_deposit_percent"));
		const enteredAmount = number(form.get_value("custom_flexi_deposit_amount"));
		const depositAmount = source === "percent"
			? Math.min(Math.ceil(Math.max(purchaseValue * enteredPercent / 100, 0)), purchaseValue)
			: Math.min(Math.max(enteredAmount, 0), purchaseValue);
		const depositPercent = source === "percent"
			? enteredPercent
			: (purchaseValue ? money(depositAmount / purchaseValue * 100) : 0);
		const afterDeposit = money(Math.max(purchaseValue - depositAmount, 0) + surchargeAmount);
		const documentationFee = number(form.get_value("custom_flexi_documentation_fee") || 25);
		const adminFeeRate = number(form.get_value("custom_flexi_admin_fee_rate") || 2.5);
		const adminFee = money(afterDeposit * adminFeeRate / 100);
		const stampDuty = number(form.get_value("custom_flexi_stamp_duty_fee"));
		const otherFee = number(form.get_value("custom_flexi_other_fee"));
		const financed = purchaseValue ? money(afterDeposit + documentationFee + adminFee + stampDuty + otherFee) : 0;
		const months = number(form.get_value("custom_flexi_term_months") || 12);
		const interestRate = number(form.get_value("custom_flexi_interest_rate"));
		const termCharges = money(financed * interestRate / 100 * months / 12);
		const totalRepayment = money(financed + termCharges);
		const values = {
			weekly_instalments: Math.round(months * 52 / 12),
			fortnightly_instalments: Math.round(months * 26 / 12),
			bimonthly_instalments: months * 2,
			monthly_instalments: months,
		};
		values.weekly_instalment_amount = values.weekly_instalments ? money(totalRepayment / values.weekly_instalments) : 0;
		values.fortnightly_instalment_amount = values.fortnightly_instalments ? money(totalRepayment / values.fortnightly_instalments) : 0;
		values.bimonthly_instalment_amount = values.bimonthly_instalments ? money(totalRepayment / values.bimonthly_instalments) : 0;
		values.monthly_instalment_amount = values.monthly_instalments ? money(totalRepayment / values.monthly_instalments) : 0;
		const period = form.get_value("custom_flexi_payment_period");
		const selectedMonthly = {
			Weekly: values.weekly_instalment_amount * 52 / 12,
			Fortnightly: values.fortnightly_instalment_amount * 26 / 12,
			"Bi-monthly": values.bimonthly_instalment_amount * 2,
			Monthly: values.monthly_instalment_amount,
		}[period] || values.monthly_instalment_amount;
		const income = assessment.income ?? number(form.get_value("custom_flexi_total_monthly_income"));
		const obligations = assessment.obligations ?? number(form.get_value("custom_flexi_total_finance_obligations"));
		const maxDsr = number(form.get_value("custom_flexi_selected_dsr")) || 35;
		const weeklyEligibility = Math.max((income * maxDsr / 100 - obligations) * 12 / 52, 0);
		const postDsr = income ? money((obligations + selectedMonthly) / income * 100) : 0;
		const assessed = income > 0 && totalRepayment > 0;
		const eligible = assessed && values.weekly_instalment_amount <= weeklyEligibility && postDsr <= maxDsr;
		const parentValues = {
			custom_flexi_cash_price: purchaseValue,
			custom_flexi_surcharge_amount: surchargeAmount,
			custom_flexi_full_value: money(purchaseValue + surchargeAmount),
			custom_flexi_deposit_amount: money(depositAmount),
			custom_flexi_deposit_percent: money(depositPercent),
			custom_flexi_value_after_deposit: afterDeposit,
			loan_amount: afterDeposit,
			custom_flexi_documentation_fee: money(documentationFee),
			custom_flexi_admin_fee: adminFee,
			custom_flexi_stamp_duty_fee: money(stampDuty),
			custom_flexi_net_amount_financed: financed,
			custom_flexi_term_charges: termCharges,
			custom_flexi_total_receivable: totalRepayment,
			custom_flexi_weekly_instalments: values.weekly_instalments,
			custom_flexi_weekly_instalment_amount: values.weekly_instalment_amount,
			custom_flexi_fortnightly_instalments: values.fortnightly_instalments,
			custom_flexi_fortnightly_instalment_amount: values.fortnightly_instalment_amount,
			custom_flexi_bimonthly_instalments: values.bimonthly_instalments,
			custom_flexi_bimonthly_instalment_amount: values.bimonthly_instalment_amount,
			custom_flexi_monthly_instalments: values.monthly_instalments,
			custom_flexi_monthly_instalment_amount: values.monthly_instalment_amount,
			custom_flexi_post_dsr: postDsr,
			custom_flexi_eligibility_status: assessed ? (eligible ? "Achieved" : "Not Achieved") : "Not Assessed",
			repayment_periods: values.monthly_instalments,
			repayment_amount: values.monthly_instalment_amount,
			total_payable_amount: totalRepayment,
			total_payable_interest: termCharges,
		};
		Object.entries(parentValues).forEach(([fieldname, value]) => setValue(fieldname, value));
		form.fields_dict[purchaseTable]?.refresh?.();
		updateHirePurchaseOptionTable(values);
	}

	function recalculate(kind) {
		if (!isLoanApplicationWebForm()) return;
		const assessment = kind === "income" ? calculateIncomeValues() : {};
		calculateFinanceValues(assessment);
	}

	function queueRecalculation(kind) {
		window.clearTimeout(refreshTimer);
		// Let Frappe finish its own grid/control change cycle first.  Some
		// Currency controls schedule an older parent calculation for ~100 ms;
		// running after it ensures the current keystroke is the final value.
		refreshTimer = window.setTimeout(() => recalculate(kind), 450);
	}

	function handleChange(event) {
		if (!isLoanApplicationWebForm()) return;
		const target = event.target;
		const fieldname = target?.closest?.("[data-fieldname]")?.dataset?.fieldname;
		const table = tableFor(target);
		if (table === purchaseTable) {
			queueRecalculation("purchase");
			return;
		}
		if (incomeTables.has(table)) {
			queueRecalculation("income");
			return;
		}
		if (!financeFields.has(fieldname)) return;
		if (fieldname === "custom_flexi_deposit_percent") depositSource = "percent";
		if (fieldname === "custom_flexi_deposit_amount") depositSource = "amount";
		queueRecalculation("finance");
	}

	// Capture both input and change: Currency and Data controls use different
	// browser events, and this remains reliable for editable grid rows.
	document.addEventListener("input", handleChange, true);
	document.addEventListener("change", handleChange, true);
})();
