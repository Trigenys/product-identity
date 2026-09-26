# Proof-of-Purchase Storage

Issue: #13

Purchase evidence is sensitive customer data. Product Identity therefore treats proof files as private application data rather than public product assets.

## Accepted files

MVP uploads are limited to:
- PDF (`application/pdf`);
- JPEG (`image/jpeg`);
- PNG (`image/png`).

The API validates both the declared content type and the file signature (magic bytes). SVG, HTML and arbitrary binary uploads are rejected.

Maximum file size: **8 MiB**.

## Upload authorization

The QR verification token is not an upload credential.

After a successful product registration, the API returns a dedicated high-entropy proof-upload grant derived from the registration identity using a separate secret. The browser keeps this grant only in session storage for the current customer flow.

The grant:
- is not embedded in the QR URL;
- is not returned by public verification;
- does not authorize reading the proof;
- is scoped to one registration.

## Storage

Production uses an S3-compatible private bucket (AWS S3, Cloudflare R2 or another compatible provider).

Object keys use internal organization/registration identifiers plus a random object name. The customer's original filename is never used as the storage key.

The bucket must not have public-read access.

Product Identity stores only metadata in PostgreSQL:
- private object key;
- original filename;
- content type;
- byte size;
- SHA-256 digest;
- merchant review state;
- upload/review/deletion timestamps;
- retention deadline.

## Merchant access

An authorized merchant member may view proof metadata.

Actual document access is issued as a short-lived pre-signed GET URL. Default lifetime: **300 seconds**; application configuration is clamped to 60–900 seconds.

Public verification never returns:
- proof metadata;
- proof object keys;
- proof URLs;
- registrant PII.

## Review

Proof state is one of:
- `pending`;
- `accepted`;
- `rejected`.

Review records the reviewing merchant user and timestamp.

A review decision is evidence for a merchant workflow; it does not itself change the immutable product identity.

## Deletion

Deletion is logically authoritative in PostgreSQL first. Once `deleted_at` is set and committed, the application no longer generates access to the proof.

Physical object deletion follows immediately.

If object-storage deletion fails, the file can remain as a private orphan but is still inaccessible through Product Identity. Cleanup can retry independently. This favors privacy/access revocation over cross-system atomicity that object storage cannot provide.

A deleted registration proof may later be re-uploaded with the same valid registration grant, creating a new private object and resetting review state.

## Retention

Default proof retention is **730 days** from upload and is configurable.

`purge_expired_proofs` is the retention hook: it marks expired proofs deleted and removes their private objects. A scheduler/worker will invoke this hook as part of production operations; the domain behavior is implemented and test-covered here.

Retention duration must eventually be configurable per legal/business policy before jurisdictions with stricter requirements are claimed as supported.

## Malware considerations

The MVP deliberately narrows accepted formats and blocks SVG/HTML, but magic-byte validation is not malware scanning.

If file support expands or threat/risk evidence justifies it, malware scanning/quarantine is required before making additional formats available.
