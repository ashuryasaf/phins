Supply Division — Integration Overview

Purpose

The Supply Division connects policyholders and case teams with external service providers worldwide: medical practitioners (doctors), legal advisors (lawyers), and specialised health equipment vendors (equipment).

Key Concepts

- Provider record (`Supply Provider` table) stores contact details, provider type (Doctor / Lawyer / Equipment), regions of operation, on-call availability, and service details.
- On-Call Requests: Case handlers or customers may request an on-call service from a provider. The `Supply Division Management` codeunit exposes `RequestOnCall(ProviderID)` which validates the provider and (in a real deployment) sends a notification via email/SMS/webhook.
- Regional Search: `SearchProvidersByRegion(Region)` returns provider IDs operating in a given region.

Integration Points

- External APIs / Webhooks: Connect provider records to external scheduling systems. Store provider webhook URLs in the table (optional extension).
- Messaging: Integrate with an SMTP gateway, SMS provider, or an instant-notification system to send on-call requests.
- Authorization: Ensure only authorized roles (case managers, underwriters, claims adjusters) can trigger `RequestOnCall`.

Deployment Notes

- The AL code in `src/` provides a minimal in-platform implementation. For production, implement secure external integrations in a codeunit (events or Azure Functions) and record provider credentials securely.
- Consider consent and data protection for sharing personal contact information across international borders.

Next steps

- Add webhook/endpoint fields to `Supply Provider` (done).
- Add synchronization with partner APIs to fetch provider availability (skeleton added via `SyncProviderAvailability` and `TriggerWebhook`).
- Add a portal page for providers to register and manage their availability (card page added: `Supply Provider Card`).

Details on new features

- Webhooks: Each provider may store a `Webhook URL` which the system will call with JSON payloads to request availability syncs or deliver on-call requests. The codeunit `Supply Division Management` includes `TriggerWebhook` (HTTP POST) and `SyncProviderAvailability` that triggers a sync and updates `Last Synced` on success.
- Availability & Scheduling: `Availability` is stored as free-text / JSON. For production you should standardize this (iCal, RFC-5545, or a defined JSON schema) and implement robust sync and time-zone aware scheduling.
- Provider Card: Providers can be viewed and edited in `Supply Provider Card` (page id 50108). The list page `Supply Providers List` was extended with actions to sync availability and open the card.

Security & Production Notes

- Authentication: Webhook calls should be authenticated (HMAC, bearer tokens, mutual TLS). The current codeunit is a minimal example and does not include authentication headers.
- Retries & Monitoring: Implement retry/backoff for transient failures and record webhook delivery status and errors for operational visibility.
- Consent & Privacy: Ensure the provider has consented to receiving requests and that any personal data is processed according to applicable regulations (GDPR, HIPAA where relevant).
