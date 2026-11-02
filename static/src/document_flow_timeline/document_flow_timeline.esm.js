/** @odoo-module **/

import { Component, onWillStart, onWillUpdateProps, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { deserializeDateTime, formatDate, formatDateTime } from "@web/core/l10n/dates";
import { localization } from "@web/core/l10n/localization";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { fetchActivityLogs, logVisual } from "../document_flow_activity/document_flow_activity.esm";

const { DateTime } = luxon;

/**
 * Visual summary of the signature flow, shown on top of the document form.
 *
 * Purely presentational: it reads the very same `signers_lines` datapoints the
 * editable list below already loads, so it stays in sync while the user edits
 * and never writes anything itself. The signing logic is untouched.
 *
 * The who/when details come from the activity log (the same rows as the
 * "Activity Logs" tab), refetched whenever the record is written.
 */
export class DocumentFlowTimeline extends Component {
    static template = "hr_document_flow.DocumentFlowTimeline";
    static props = { ...standardWidgetProps };

    setup() {
        this.orm = useService("orm");
        this.logState = useState({ logs: [] });
        onWillStart(() => this.loadLogs(this.props.record));
        onWillUpdateProps((nextProps) => {
            if (this.logSignature(nextProps.record) !== this.loadedSignature) {
                return this.loadLogs(nextProps.record);
            }
        });
    }

    logSignature(record) {
        const writeDate = record.data.write_date;
        return `${record.resId || 0}|${writeDate ? writeDate.toMillis() : 0}`;
    }

    async loadLogs(record) {
        this.loadedSignature = this.logSignature(record);
        this.logState.logs = record.resId ? await fetchActivityLogs(this.orm, record.resId) : [];
    }

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
        return this.employeeAvatarUrl(signer.data.employee_id);
    }

    employeeAvatarUrl(employee) {
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

    // --- history from the activity log -----------------------------------

    logWho(log) {
        return (log.employee_id && log.employee_id[1]) || _t("System");
    }

    logWhen(log) {
        if (!log.log_date) {
            return "";
        }
        // Seconds would not fit under a signer card.
        return formatDateTime(deserializeDateTime(log.log_date), {
            format: `${localization.dateFormat} HH:mm`,
        });
    }

    /**
     * Log entries concerning one signer. Entries written before the log was
     * linked to signer lines carry no signer_id; signatures and refusals are
     * then matched by the employee who performed them, which is the signer.
     */
    signerLogs(signer) {
        const employeeId = signer.data.employee_id && signer.data.employee_id[0];
        return this.logState.logs.filter((log) => {
            if (log.signer_id) {
                return signer.resId && log.signer_id[0] === signer.resId;
            }
            return (
                ["sign", "refuse"].includes(log.action) &&
                employeeId &&
                log.employee_id &&
                log.employee_id[0] === employeeId
            );
        });
    }

    /** Received / reminded / signed / refused lines under a signer card. */
    signerEvents(signer) {
        const logs = this.signerLogs(signer);
        const events = [];
        const sent = logs.find((log) => log.action === "sent");
        if (sent) {
            events.push({
                key: "sent",
                icon: "fa-inbox",
                cls: "o_df_ev_sent",
                label: _t("Received"),
                when: this.logWhen(sent),
                title: _t("Sent by %s", this.logWho(sent)),
            });
        }
        const reminders = logs.filter((log) => log.action === "resent");
        if (reminders.length) {
            const last = reminders[reminders.length - 1];
            events.push({
                key: "resent",
                icon: "fa-bell-o",
                cls: "o_df_ev_sent",
                label: reminders.length > 1
                    ? _t("Reminders (%s)", reminders.length)
                    : _t("Reminder"),
                when: this.logWhen(last),
                title: _t("Last reminder sent by %s", this.logWho(last)),
            });
        }
        const employeeId = signer.data.employee_id && signer.data.employee_id[0];
        for (const action of ["sign", "refuse"]) {
            const log = logs.find((entry) => entry.action === action);
            if (!log) {
                continue;
            }
            // Someone may upload the signed file on the signer's behalf.
            const onBehalf = log.employee_id && log.employee_id[0] !== employeeId;
            events.push({
                key: action,
                icon: action === "sign" ? "fa-check" : "fa-times",
                cls: action === "sign" ? "o_df_ev_done" : "o_df_ev_refused",
                label: action === "sign" ? _t("Signed") : _t("Refused"),
                when: this.logWhen(log),
                by: onBehalf ? _t("uploaded by %s", this.logWho(log)) : "",
                title: _t("Recorded by %s", this.logWho(log)),
            });
        }
        // Signatures from before the log kept a reliable time only have a date.
        if (signer.data.state === "completed" && !events.some((ev) => ev.key === "sign")) {
            const date = this.signerDate(signer);
            if (date) {
                events.push({ key: "sign", icon: "fa-check", cls: "o_df_ev_done", label: _t("Signed"), when: date });
            }
        }
        return events;
    }

    /** Document-level milestones: created, sent, and how the flow ended. */
    get milestones() {
        const logs = this.logState.logs;
        const steps = [];
        const created = logs.find((log) => log.action === "create");
        steps.push(this.milestone("create", created));
        const sent = logs.find((log) => log.action === "sent");
        steps.push(this.milestone("sent", sent));
        const endActions = ["verified", "refuse", "canceled", "expired", "archived"];
        const ends = logs.filter((log) => endActions.includes(log.action));
        if (ends.length) {
            steps.push(this.milestone(ends[ends.length - 1].action, ends[ends.length - 1]));
        } else {
            steps.push(this.milestone("verified", false));
        }
        return steps;
    }

    milestone(action, log) {
        const visual = logVisual(action);
        return {
            key: action,
            icon: visual.icon,
            cls: log ? visual.cls : "o_df_log_pending",
            label: visual.label,
            who: log ? this.logWho(log) : "",
            when: log ? this.logWhen(log) : _t("Not yet"),
            done: Boolean(log),
        };
    }

    // --- the chain: author first, then the signers -------------------------

    /** The author's node: uploads the document and sends it for signature. */
    get authorStep() {
        const creator = this.record.data.creator_id;
        const sentByAuthor = !["draft", "new"].includes(this.documentState);
        const events = [];
        const created = this.logState.logs.find((log) => log.action === "create");
        if (created) {
            events.push({ key: "create", icon: "fa-plus", cls: "", label: _t("Created on"), when: this.logWhen(created) });
        }
        const sent = this.logState.logs.find((log) => log.action === "sent");
        if (sent) {
            const onBehalf = creator && sent.employee_id && sent.employee_id[0] !== creator[0];
            events.push({
                key: "sent",
                icon: "fa-paper-plane-o",
                cls: "o_df_ev_sent",
                label: _t("Sent on"),
                when: this.logWhen(sent),
                by: onBehalf ? _t("sent by %s", this.logWho(sent)) : "",
            });
        }
        return {
            key: "author",
            isAuthor: true,
            name: (creator && creator[1]) || _t("Unknown author"),
            avatar: this.employeeAvatarUrl(creator),
            role: _t("Author"),
            visual: sentByAuthor
                ? { icon: "fa-paper-plane-o", cls: "o_df_done", label: _t("Sent for signature") }
                : { icon: "fa-pencil", cls: "o_df_current", label: _t("Preparing the document") },
            events,
            done: sentByAuthor,
            // Until it is sent, the author is the one the flow waits on.
            current: ["draft", "new"].includes(this.documentState),
        };
    }

    get steps() {
        const steps = [this.authorStep];
        for (const signer of this.signers) {
            steps.push({
                key: `signer_${signer.id}`,
                isAuthor: false,
                name: this.signerName(signer),
                avatar: this.signerAvatarUrl(signer),
                role: this.signerRole(signer),
                visual: this.signerVisual(signer),
                events: this.signerEvents(signer),
                done: signer.data.state === "completed",
                refused: signer.data.state === "refused",
                current: this.isCurrent(signer),
            });
        }
        // The connector leading to a person shows whether the flow got there.
        for (const step of steps) {
            if (step.done) {
                step.connectorClass = "o_df_conn_done";
            } else if (step.refused) {
                step.connectorClass = "o_df_conn_refused";
            } else if (step.current) {
                step.connectorClass = "o_df_conn_active";
            } else {
                step.connectorClass = "";
            }
        }
        return steps;
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

    get confidentialityLabel() {
        // Only the restricted levels are flagged, like a lock on the kanban card.
        const labels = {
            confidential: _t("Confidential document"),
            strictly_confidential: _t("Strictly confidential document"),
        };
        return labels[this.props.record.data.confidentiality] || "";
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
        { name: "confidentiality", type: "selection" },
        { name: "write_date", type: "datetime" },
        { name: "creator_id", type: "many2one", relation: "hr.employee" },
    ],
};

registry.category("view_widgets").add("document_flow_timeline", documentFlowTimeline);
