/* Customer signs every agreement first; company signs only afterwards. */

function flexi_customer_documents_complete(frm) {
	return (frm.doc.custom_customer_documents || [])
		.filter((row) => row.document_code !== "REQ")
		.every((row) => ["Customer Signed", "Director Signed", "Completed"].includes(row.status));
}

window.flexi_can_open_document = () => true;

window.flexi_open_customer_document = function (frm, row) {
	if (row.document_code === "REQ") return;
	if (row.status === "Completed") {
		if (row.final_signed_file) window.open(row.final_signed_file, "_blank");
		else frappe.msgprint(__("The final signed copy is not available."));
		return;
	}
	if (row.status === "Director Signed") {
		if (row.final_signed_file) window.open(row.final_signed_file, "_blank");
		return;
	}
	if (row.status === "Customer Signed") {
		if (!flexi_customer_documents_complete(frm)) {
			frappe.msgprint(__("Complete every customer document before the Director / Manager signs."));
			return;
		}
		flexi_open_director_signing(frm, row);
		return;
	}
	flexi_open_customer_signing(frm, row);
};

window.flexi_add_document_buttons = function (frm) {
	(frm.doc.custom_customer_documents || [])
		.filter((row) => row.document_code !== "REQ")
		.forEach((row) => {
			const status = row.status || "Pending";
			const icon = status === "Completed" ? "✓" : "•";
			frm.add_custom_button(
				__(`${icon} ${flexi_document_title(row)} — ${status}`),
				() => flexi_open_customer_document(frm, row),
				__("Customer Documents")
			);
		});
};
