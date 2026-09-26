# Authenticity Signals

Issue: #14

Product Identity surfaces **operational anomaly signals**, not counterfeit verdicts.

## Why

A copied QR, a trade-show demo unit, a support technician, a VPN, travel, reseller testing or automated abuse can all create unusual scan patterns. The system therefore reports observable facts and configured thresholds instead of claiming to know why they occurred.

## MVP signals

### Repeat scan burst

Default rule:

- threshold: **6 scans**
- rolling window: **10 minutes**

Example explanation:

> Observed 6 scans within 10 minutes; configured threshold is 6. This is an operational anomaly, not proof of counterfeiting.

The signal is updated within the current time bucket rather than creating one alert per additional scan.

### Multi-country activity

Default rule:

- threshold: **2 countries**
- rolling window: **24 hours**

Country context is **disabled by default**.

It may be enabled only when Product Identity runs behind a trusted edge that overwrites the configured country header. Raw client IP addresses are not stored.

Country signals explicitly warn that travel, VPNs and network routing can explain the observation.

## Device context

The API records only a coarse device class derived from the browser client hint:

- mobile;
- desktop;
- unknown.

It does **not** persist:
- raw user-agent strings;
- IP addresses;
- browser fingerprints;
- advertising identifiers.

Device class is contextual evidence only and is not currently a standalone anomaly trigger.

## Merchant workflow

Signals start as `open`.

Authorized merchant users may mark them:
- `reviewed`;
- `dismissed`.

A review stores the reviewing user, timestamp and optional note. Dismissal is useful for known demo units, QA labs, retail displays or other legitimate high-scan contexts.

## Public behavior

Public verification remains factual:

- valid;
- revoked;
- unknown.

Authenticity signals are not returned to the public verification page in the MVP. This prevents a probabilistic signal from frightening a buyer or being presented as a physical counterfeit determination.

## Configuration

Environment variables:

- `PRODUCT_IDENTITY_VERIFICATION_REPEAT_SCAN_THRESHOLD`
- `PRODUCT_IDENTITY_VERIFICATION_REPEAT_SCAN_WINDOW_MINUTES`
- `PRODUCT_IDENTITY_VERIFICATION_COUNTRY_THRESHOLD`
- `PRODUCT_IDENTITY_VERIFICATION_COUNTRY_WINDOW_HOURS`
- `PRODUCT_IDENTITY_VERIFICATION_TRUST_EDGE_COUNTRY`
- `PRODUCT_IDENTITY_VERIFICATION_COUNTRY_HEADER`

Threshold changes should be driven by pilot evidence, not intuition.

## Limitations

These signals cannot prove physical authenticity.

Stronger physical guarantees would require additional controls such as tamper-evident labels, hidden one-time codes, secure NFC or manufacturing-chain attestations.
