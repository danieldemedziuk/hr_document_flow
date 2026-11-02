/** @odoo-module **/

import { Component, onWillStart, onWillUpdateProps, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { deserializeDateTime, formatDateTime } from "@web/core/l10n/dates";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

/** Icon / colour / label per logged action; shared with the progress widget. */
export function logVisual(action) {
    switch (action) {
        case "create":
            return { icon: "fa-plus", cls: "o_df_log_create", label: _t("Document created") };
        case "sent":
            return { icon: "fa-paper-plane", cls: "o_df_log_sent", label: _t("Sent for signature") };
        case "resent":
            return { icon: "fa-repeat", cls: "o_df_log_sent", label: _t("Reminder resent") };
        case "sign":
            return { icon: "fa-check", cls: "o_df_log_sign", label: _t("Document signed") };
        case "refuse":
            return { icon: "fa-times", cls: "o_df_log_refuse", label: _t("Signature refused") };
        case "verified":
            return { icon: "fa-flag-checkered", cls: "o_df_log_sign", label: _t("Flow completed") };
        case "canceled":
            return { icon: "fa-ban", cls: "o_df_log_refuse", label: _t("Flow canceled") };
        case "archived":
            return { icon: "fa-archive", cls: "o_df_log_muted", label: _t("Archived") };
        case "expired":
            return { icon: "fa-hourglass-end", cls: "o_df_log_refuse", label: _t("Validity expired") };
        default:
            return { icon: "fa-circle-o", cls: "o_df_log_muted", label: action || "" };
    }
}

/** Fetches the activity log of a document, oldest first. */
export function fetchActivityLogs(orm, documentId) {
    return orm.searchRead(
        "hr.document_flow.activity_logs",
        [["document_id", "=", documentId]],
        ["action", "log_date", "employee_id", "signer_id"],
        { order: "log_date asc, id asc" }
    );
}

/**
 * Read-only history of what happened to the document, as a vertical timeline.
 *
 * The entries are the very same `hr.document_flow.activity_logs` rows the plain
 * list used to show - only the presentation changed. They are fetched directly
 * so the widget does not depend on the x2many being present in the arch, and
 * refetched whenever the record is written (every logged action writes it).
 */
export class DocumentFlowActivity extends Component {
    static template = "hr_document_flow.DocumentFlowActivity";
    static props = { ...standardWidgetProps };

    setup() {
        this.orm = useService("orm");
        this.state = useState({ entries: [], loaded: false });
        onWillStart(() => this.loadEntries(this.props.record));
        onWillUpdateProps((nextProps) => {
            const next = this.signature(nextProps.record);
            if (next !== this.loadedSignature) {
                return this.loadEntries(nextProps.record);
            }
        });
    }

    /** Cheap change detector: a new id or a new write stamp means new logs. */
    signature(record) {
        const writeDate = record.data.write_date;
        return `${record.resId || 0}|${writeDate ? writeDate.toMillis() : 0}`;
    }

    async loadEntries(record) {
        this.loadedSignature = this.signature(record);
        if (!record.resId) {
            this.state.entries = [];
            this.state.loaded = true;
            return;
        }
        const rows = await fetchActivityLogs(this.orm, record.resId);
        this.state.entries = rows;
        this.state.loaded = true;
    }

    visual(entry) {
        return logVisual(entry.action);
    }

    author(entry) {
        return (entry.employee_id && entry.employee_id[1]) || _t("System");
    }

    /** Recipient of a send/reminder, shown as "→ name". */
    target(entry) {
        if (!["sent", "resent"].includes(entry.action) || !entry.signer_id) {
            return "";
        }
        return entry.signer_id[1];
    }

    avatarUrl(entry) {
        if (!entry.employee_id || !entry.employee_id[0]) {
            return false;
        }
        return `/web/image/hr.employee.public/${entry.employee_id[0]}/avatar_128`;
    }

    when(entry) {
        // searchRead returns a serialized datetime string, not a luxon object.
        return entry.log_date ? formatDateTime(deserializeDateTime(entry.log_date)) : "";
    }

    get emptyLabel() {
        return _t("Nothing has happened on this document yet.");
    }
}

export const documentFlowActivity = {
    component: DocumentFlowActivity,
    fieldDependencies: [{ name: "write_date", type: "datetime" }],
};

registry.category("view_widgets").add("document_flow_activity_log", documentFlowActivity);
