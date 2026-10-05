/* Public Loan Application guard: existing customers are handled by staff. */
(function () {
	let duplicateCheckBound = false;
	let submissionApproved = false;
	let checkingDuplicate = false;
	let duplicateFound = false;

	function checkExistingCustomer(showMessage) {
		if (!isLoanApplicationWebForm()) return Promise.resolve(false);
		return frappe.call({
			method: "comfort_homes.api.check_existing_customer",
			args: {
				tin_number: frappe.web_form.get_value("custom_tin_number") || "",
				email: frappe.web_form.get_value("applicant_email_address") || "",
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

	if (window.frappe?.web_form?.events) {
		frappe.web_form.events.on("after_load", () => {
			bindDuplicateCheck();
			["custom_tin_number", "applicant_email_address"].forEach((fieldname) => {
				frappe.web_form.on(fieldname, () => checkExistingCustomer(true));
			});
		});
	} else {
		document.addEventListener("DOMContentLoaded", bindDuplicateCheck);
	}
})();
