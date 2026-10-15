/* Contract pack download, chosen by the "Download PDF With Signed Documents?" field:
 *   Yes -> Signed Contract Pack (PDF), shown once every document is Completed.
 *   No  -> Blank Contract Forms (PDF), shown at any time (no documents needed).
 */

function comfort_collection_complete(frm) {
	const df = (frm.meta.fields || []).find((field) =>
		(field.label || "").trim().toLowerCase().startsWith("download pdf with signed documents")
	);
	if (!df) return false;
	const value = String(frm.doc[df.fieldname] || "").trim().toLowerCase();
	return value === "yes" || value === "1";
}

frappe.ui.form.on("Loan Application", {
	// Save as soon as the choice changes, so the right button appears straight away.
	custom_download_pdf_with_signed_documents(frm) {
		if (frm.is_new() || !frm.is_dirty()) return;
		frm.save(frm.doc.docstatus === 1 ? "Update" : "Save");
	},
	refresh(frm) {
		if (frm.is_new()) return;
		const rows = (frm.doc.custom_customer_documents || []).filter((row) => row.document_code !== "REQ");
		const allCompleted = rows.length > 0 && rows.every((row) => row.status === "Completed");
		if (comfort_collection_complete(frm)) {
			if (!allCompleted) return; // Signed pack only after every document is Completed.
			frm.add_custom_button(
				__("Download All Signed Copy"),
				() => comfort_contract_pdf(frm, "comfort_homes.signed_pack.make_signed_pack", __("Signed Contract Pack")),
				__("Customer Documents")
			);
		} else {
			frm.add_custom_button(
				__("Download All Copy"),
				() => comfort_contract_pdf(frm, "comfort_homes.signed_pack.make_blank_forms", __("Blank Contract Forms")),
				__("Customer Documents")
			);
		}
	},
});

function comfort_print_pack_html(win, title, documents) {
	if (!win) {
		frappe.msgprint(__("Allow pop-ups for this site to open the contract pack."));
		return;
	}
	win.document.open();
	win.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>${frappe.utils.escape_html(title)}</title>
		<style>
			@page { size: A4; margin: 10mm; }
			html, body { margin: 0; padding: 0; background: #fff; }
			.pack-doc + .pack-doc { break-before: page; page-break-before: always; }
		</style></head><body></body></html>`);
	win.document.close();
	documents.forEach((d) => {
		const host = win.document.createElement("div");
		host.className = "pack-doc";
		win.document.body.appendChild(host);
		host.attachShadow({ mode: "open" }).innerHTML = d.html;
	});
	setTimeout(() => { win.focus(); win.print(); }, 800);
}

function comfort_contract_pdf(frm, method, label) {
	// Open the tab inside the click so pop-up blockers allow it.
	const win = window.open("", "_blank");
	frappe.call({
		method,
		args: { loan_application: frm.doc.name },
		freeze: true,
		freeze_message: __("Preparing {0}…", [label]),
		callback(r) {
			const result = r.message;
			if (!result) {
				if (win) win.close();
				return;
			}
			if (result.mode === "html") {
				// No PDF engine on the server: show the documents together for printing.
				comfort_print_pack_html(win, `${label} - ${frm.doc.name}`, result.documents);
				frappe.show_alert({
					message: __("PDF generation is unavailable on this server. Use Print → Save as PDF to keep one file."),
					indicator: "orange",
				}, 10);
				return;
			}
			if (win) win.location = result.file_url;
			else window.open(result.file_url, "_blank");
			frappe.show_alert({
				message: result.pages
					? __("{0} created: {1} documents, {2} pages.", [label, result.documents.length, result.pages])
					: __("{0} ready: {1} documents.", [label, result.documents.length]),
				indicator: "green",
			}, 7);
			frm.reload_doc();
		},
		error() {
			if (win) win.close();
		},
	});
}