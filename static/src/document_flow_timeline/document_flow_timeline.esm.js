/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { formatDate } from "@web/core/l10n/dates";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

const { DateTime } = luxon;

/**
 * Visual summary of the signature flow, shown on top of the document form.
 *
 * Purely presentational: it reads the very same `signers_lines` datapoints the
 * editable list below already loads, so it stays in sync while the user edits
 * and never writes anything itself. The signing logic is untouched.
 */
export class DocumentFlowTimeline extends Component {
    static template = "hr_document_flow.DocumentFlowTimeline";
    static props = { ...standardWidgetProps };

    // --- data -------------------------------------------------------------

    get record() {
        return this.props.record;
    }

    get documentState() {
        return this.record.data.state;
    }

    /** Signer datapoints, ordered the way the flow processes them. */
    get signers() {
        const list = this.record.data.signers_lines;
        if (!list || !list.records) {
            return [];
        }
        return [...list.records].sort((a, b) => {
            const seqA = a.data.sequence || 0;
            const seqB = b.data.sequence || 0;
            if (seqA !== seqB) {
                return seqA - seqB;
            }
            // Unsaved rows have no resId yet; keep them in insertion order.
            return (a.resId || 0) - (b.resId || 0);
        });
    }

    get signedCount() {
        return this.signers.filter((rec) => rec.data.state === "completed").length;
    }

    get progress() {
        const total = this.signers.length;
        if (!total) {
            return 0;
        }
        if (this.record.data.single_signature) {
            return this.signedCount ? 100 : 0;
        }
        return Math.round((this.signedCount * 100) / total);
    }

    // --- per-signer presentation -----------------------------------------

    /** Icon / colour / label for one signer state. */
    signerVisual(signer) {
        switch (signer.data.state) {
            case "completed":
                return { icon: "fa-check", cls: "o_df_done", label: _t("Signed") };
            case "sent":
                return { icon: "fa-paper-plane-o", cls: "o_df_current", label: _t("Awaiting signature") };
            case "refused":
                return { icon: "fa-times", cls: "o_df_refused", label: _t("Refused") };
            case "archived":
                return { icon: "fa-archive", cls: "o_df_muted", label: _t("Archived") };
            default:
                return { icon: "fa-clock-o", cls: "o_df_pending", label: _t("Queued") };
        }
    }

    signerName(signer) {
        const employee = signer.data.employee_id;
        return (employee && employee[1]) || _t("Unnamed signer");
    }

    signerAvatarUrl(signer) {
        const employee = signer.data.employee_id;
        if (!employee || !employee[0]) {
            return false;
        }
        // hr.employee itself is readable by HR officers only; the public view
        // shares the same ids and is what core uses for avatars.
        return `/web/image/hr.employee.public/${employee[0]}/avatar_128`;
    }

    signerRole(signer) {
        const role = signer.data.role_id;
        return (role && role[1]) || "";
    }

    signerDate(signer) {
        const date = signer.data.signing_date;
        return date ? formatDate(date) : "";
    }

    /** True for the signer the flow is currently waiting on. */
    isCurrent(signer) {
        return signer.data.state === "sent" && this.documentState === "sent";
    }

    // --- overall status ---------------------------------------------------

    /** Headline describing where the flow stands right now. */
    get statusLine() {
        const state = this.documentState;
        if (state === "refused") {
            const refused = this.signers.find((rec) => rec.data.state === "refused");
            return refused
                ? _t("Refused by %s", this.signerName(refused))
                : _t("Refused");
        }
        if (state === "canceled") {
            return _t("Flow canceled");
        }
        if (state === "expired") {
            return _t("Validity expired");
        }
        if (state === "verified-done") {
            return _t("All required signatures collected");
        }
        if (state === "archived") {
            return _t("Archived");
        }
        if (!this.signers.length) {
            return _t("Add the signers below to start the flow");
        }
        if (state === "sent") {
            const current = this.signers.find((rec) => rec.data.state === "sent");
            return current
                ? _t("Waiting for %s", this.signerName(current))
                : _t("Waiting for the remaining signatures");
        }
        return _t("Ready to be sent for signature");
    }

    get statusClass() {
        switch (this.documentState) {
            case "verified-done":
                return "o_df_status_done";
            case "refused":
            case "expired":
            case "canceled":
                return "o_df_status_alert";
            case "sent":
                return "o_df_status_running";
            default:
                return "o_df_status_draft";
        }
    }

    get counterLabel() {
        return _t("%(signed)s of %(total)s signed", {
            signed: this.signedCount,
            total: this.signers.length,
        });
    }

    // --- validity ---------------------------------------------------------

    get validityDate() {
        return this.record.data.validity || false;
    }

    get validityLabel() {
        const validity = this.validityDate;
        if (!validity) {
            return "";
        }
        const days = Math.ceil(validity.diff(DateTime.now().startOf("day"), "days").days);
        if (days < 0) {
            return _t("Overdue since %s", formatDate(validity));
        }
        if (days === 0) {
            return _t("Due today (%s)", formatDate(validity));
        }
        return _t("Valid until %(date)s (%(days)s days left)", {
            date: formatDate(validity),
            days: days,
        });
    }

    /** Only warn while the flow can still act on the deadline. */
    get validityClass() {
        const validity = this.validityDate;
        if (!validity || ["verified-done", "archived", "canceled"].includes(this.documentState)) {
            return "o_df_validity_neutral";
        }
        const days = Math.ceil(validity.diff(DateTime.now().startOf("day"), "days").days);
        if (days < 0) {
            return "o_df_validity_over";
        }
        if (days <= 3) {
            return "o_df_validity_soon";
        }
        return "o_df_validity_neutral";
    }

    // --- static labels ----------------------------------------------------

    get progressTitle() {
        return _t("Signature progress");
    }

    get emptyLabel() {
        return _t("No signers added yet.");
    }

    get secretLabel() {
        return _t("Secret document");
    }

    get singleSignatureLabel() {
        return _t("One signature is enough");
    }
}

export const documentFlowTimeline = {
    component: DocumentFlowTimeline,
    fieldDependencies: [
        { name: "state", type: "selection" },
        { name: "single_signature", type: "boolean" },
        { name: "validity", type: "date" },
        { name: "secret_doc", type: "boolean" },
    ],
};

registry.category("view_widgets").add("document_flow_timeline", documentFlowTimeline);
