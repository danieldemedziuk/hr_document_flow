# HR Document flow

Serial signature circulation of HR documents for Odoo 17.

## Features

- **Document submission** – the author uploads a PDF and chooses the document type, signature type,
  confidentiality level and optional validity date.
- **Serial signing** – signers sign one after another, in the order of the list. Each signer is
  e-mailed when it is their turn, downloads the document, signs it and uploads the signed PDF into
  their own line; the next signer then receives the file signed so far. With *Single signature*
  one signature closes the flow.
- **Contacts in copy** – notified by e-mail about the flow.
- **Completion** – once the required signatures are collected the flow is verified, the author is
  notified, and the signed document is filed in *Document hub* (Administration / Inbox) with the
  flow's confidentiality level.
- **Signature progress** – a timeline on the form shows the author and every signer with their
  photo, what each of them did and when (received, reminded, signed, refused), and highlights the
  person the flow is waiting for.
- **Activity log** – a full, read-only history of the flow.
- **Reminders and expiry** – a daily cron reminds the current signer a configurable number of days
  before the validity date and expires overdue flows.

## Security

| Group   | Access |
|---------|--------|
| User    | Flows they created or have to sign, with their signers, contacts and log. |
| Officer | Additionally reads flows whose document type is visible to officers, except strictly confidential ones; can verify and archive. |
| Manager | Everything. |

The flow is enforced server-side, not only by the form:

- only the author (or a manager) sends or cancels a flow;
- only the signer whose turn it is uploads the signed file or refuses (a manager may upload on
  their behalf);
- the signature state of a line is set by the flow only, and signers cannot be changed once sent;
- the activity log is written by the server only.

## Dependencies

- `hr`
- `mail_template` – e-mail delivery
- `document_hub` – filing of the signed documents

## License

See the [LICENSE](LICENSE) file.
