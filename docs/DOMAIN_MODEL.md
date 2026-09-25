# Domain Model

## Brand
Tenant/customer organization that owns products and product-unit identities.

## Product
Commercial model/SKU-level definition. A Product can have many Units.

## Unit
One physical instance of a Product. The Unit is the core aggregate for identity, registration and warranty.

## Serial
Human-readable or machine-issued identifier for a Unit. Serial format may be imported or generated.

## Verification Token
Opaque token encoded in QR/URL. It must not leak internal IDs and can support rotation/revocation rules.

## Channel Sale Reference
Optional link to Shopify, Amazon, POS, distributor or CSV-origin sale. Channel data is evidence/context, not identity authority.

## Registration
Association between a Unit and a customer-provided ownership/warranty registration event.

## Proof of Purchase
Protected artifact/metadata supporting registration or warranty dates.

## Warranty
Policy plus calculated state for a Unit: not-started, active, expired, void/revoked where explicitly supported.

## Verification Event
Timestamped public verification attempt with privacy-minimized metadata used for analytics and anomaly signals.

## Authenticity Signal
Derived observation such as unknown serial, revoked token or unusually repeated scans. Signals must not be represented as conclusive counterfeit proof without sufficient evidence.
