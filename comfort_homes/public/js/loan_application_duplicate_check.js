/* Public Loan Application guard: existing customers are handled by staff. */
(function () {
	let duplicateCheckBound = false;
	let submissionApproved = false;
	let checkingDuplicate = false;
	let duplicateFound = false;
	let fieldChecksBound = false;
	let fieldInputChecksBound = false;
	let lookupTimer;

	function valueFromInput(fieldname) {
		const input = frappe.web_form.fields_dict[fieldname]?.wrapper?.querySelector("input");
		return String(input?.value ?? frappe.web_form.get_value(fieldname) ?? "").trim();
	}

	function checkExistingCustomer(showMessage) {
		if (!isLoanApplicationWebForm()) return Promise.resolve(false);
		return frappe.call({
			method: "comfort_homes.api.check_existing_customer",
			args: {
				tin_number: valueFromInput("custom_tin_number"),
				email: valueFromInput("applicant_email_address"),
			},
		}).then((response) => {
			duplicateFound = Boolean((response.message || {}).exists);
			if (duplicateFound && showMessage) {
				frappe.msgprint({
					title: __("Existing customer"),
					message: __("A customer with this TIN Number or Email Address already exists. Please add the loan application from the backend."),
					indicator: "orange",
				});
			}
			return duplicateFound;
		});
	}

	function isLoanApplicationWebForm() {
		return window.location.pathname.replace(/\/$/, "") === "/loan-application" && window.frappe?.web_form;
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
							message: __("A customer with this TIN Number or Email Address already exists. Please process this loan through the backend."),
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

	function initialiseWhenReady() {
		if (!window.location.pathname.replace(/\/$/, "").endsWith("/loan-application")) return;
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
})();
