
# HR Document flow

## Overview

HR Document flow is a module for Odoo 12 that streamlines the document circulation process within an organization. It allows users to upload documents that need signatures, select the type of document and signature, and send it for approval to multiple recipients. Additionally, the module supports adding CC (carbon copy) recipients who will be notified via email for each signature update.

## Key Features

- **Document Submission**: Users can upload documents directly into the Odoo system for further approval.
- **Document Classification**: Select the type of document (e.g., contract, agreement, policy) and the required type of signature (e.g., digital, wet).
- **Approval Flow**: Choose individuals who are required to sign the document from a predefined list of users.
- **CC Recipients**: Option to add CC recipients who will receive notifications for each signature via email.
- **Signature Tracking**: Track the status of document signatures and receive notifications upon completion.
  
## Installation

To install the HR Document flow module in your Odoo 12 instance:

1. Download or clone this repository into your Odoo custom addons directory:
   ```bash
   git clone https://github.com/danieldemedziuk/hr_document_flow.git
   ```
2. Update the app list from the Odoo interface.
3. Search for **HR Document flow** and click **Install**.

## Usage

1. Navigate to the **Document flow** app in Odoo.
2. Click **Create** to upload a new document for signature.
3. Fill out the necessary details, including:
   - Name
   - Document type
   - Signature type
   - List of recipients for signing
   - Optional: Add CC recipients for signature updates
4. Submit the document for approval.
5. Track the progress of the document’s signatures and receive email notifications as the signatures are completed.

## Dependencies

This module requires the following Odoo core modules to be installed:
- **hr**
- **mail**
- **document**
  
## Compatibility

- Odoo 12
- HR and Document Management modules

## License

This module is licensed under the MIT License. See the [LICENSE](LICENSE) file for more details.

## Contribution

Feel free to contribute to this module by submitting a pull request or reporting issues.

---

**Author:** [DanielDemedziuk]  
**Version:** 12.0.0.1  
**Support:** daniel.demedziuk@gmail.com
