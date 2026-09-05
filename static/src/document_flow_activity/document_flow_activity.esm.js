/** @odoo-module **/

import { Component, onWillStart, onWillUpdateProps, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { deserializeDateTime, formatDateTime } from "@web/core/l10n/dates";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

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
        const rows = await this.orm.searchRead(
            "hr.document_flow.activity_logs",
            [["document_id", "=", record.resId]],
            ["action", "log_date", "employee_id"],
            { order: "log_date asc, id asc" }
        );
        this.state.entries = rows;
        this.state.loaded = true;
    }

    /** Icon / colour / label per logged action. */
    visual(entry) {
        switch (entry.action) {
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
            case "archived":
                return { icon: "fa-archive", cls: "o_df_log_muted", label: _t("Archived") };
            case "expired":
                return { icon: "fa-hourglass-end", cls: "o_df_log_refuse", label: _t("Validity expired") };
            default:
                return { icon: "fa-circle-o", cls: "o_df_log_muted", label: entry.action || "" };
        }
    }

    author(entry) {
        return (entry.employee_id && entry.employee_id[1]) || _t("System");
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
