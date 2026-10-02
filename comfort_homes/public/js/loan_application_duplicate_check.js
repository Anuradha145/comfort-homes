/* Public Loan Application guard: existing customers are handled by staff. */
(function () {
	let duplicateCheckBound = false;
	let submissionApproved = false;
	let checkingDuplicate = false;

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
			frappe.call({
				method: "comfort_homes.api.check_existing_customer",
				args: {
					tin_number: frappe.web_form.get_value("custom_tin_number") || "",
					email: frappe.web_form.get_value("applicant_email_address") || "",
				},
				callback(response) {
					checkingDuplicate = false;
					if ((response.message || {}).exists) {
						frappe.msgprint({
							title: __("Existing customer"),
							message: __("A customer with this TIN Number or Email Address already exists. Please process this loan through the backend."),
							indicator: "orange",
						});
						return;
					}
					submissionApproved = true;
					button.click();
				},
				error() {
					checkingDuplicate = false;
					frappe.msgprint(__("We could not validate existing customer details. Please try again."));
				},
			});
		}, true);
	}

	if (window.frappe?.web_form?.events) {
		frappe.web_form.events.on("after_load", bindDuplicateCheck);
	} else {
		document.addEventListener("DOMContentLoaded", bindDuplicateCheck);
	}
})();
