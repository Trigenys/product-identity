# PERT — Product Identity

Product Identity is managed as a dependency-driven program. Market validation runs in parallel with foundational engineering; expansion features are explicitly gated by evidence.

## Network

```mermaid
flowchart LR
  A["#1 A — ICP / JTBD / kill criteria"]
  B["#2 B — 60-brand prospect dataset"]
  C["#3 C — Discovery interviews"]
  D["#4 D — Smoke-test landing"]
  E["#5 E — Acquisition smoke test"]
  F["#6 F — Architecture baseline"]
  G["#7 G — Threat model"]
  H["#8 H — Tenant/auth foundation"]
  I["#9 I — Serialization core"]
  J["#10 J — CSV + QR assets"]
  K["#11 K — Public verification"]
  L["#12 L — Registration + warranty"]
  M["#13 M — Proof of purchase"]
  N["#14 N — Anomaly signals"]
  O["#15 O — Merchant registry"]
  P["#16 P — Shopify connector"]
  Q["#17 Q — Shopify setup UX"]
  R["#18 R — Channel adapter contract"]
  S["#19 S — Metering / entitlements"]
  T["#20 T — Observability / recovery"]
  U["#21 U — Security hardening"]
  V["#22 V — Design-partner beta"]
  W["#23 W — Prospect outreach system"]
  X["#24 X — App Store / SEO assets"]
  Y["#25 Y — Paid acquisition experiment"]
  Z["#26 Z — Go / pivot / kill"]

  A --> B --> C
  A --> D --> E
  A --> F
  F --> G
  F --> H
  F --> I
  G --> I
  H --> I
  I --> J
  I --> K
  G --> K
  K --> L
  H --> L
  L --> M
  G --> M
  K --> N
  G --> N
  I --> O
  L --> O
  F --> P
  H --> P
  I --> P
  P --> Q
  O --> Q
  J --> Q
  F --> R
  I --> R
  H --> S
  I --> S
  L --> S
  H --> T
  I --> T
  G --> U
  K --> U
  M --> U
  P --> U
  T --> U
  C --> V
  J --> V
  K --> V
  L --> V
  O --> V
  P --> V
  U --> V
  B --> W
  C --> W
  D --> W
  P --> X
  Q --> X
  V --> X
  E --> Y
  V --> Y
  W --> Y
  V --> Z
  Y --> Z
```

## Critical path

The principal delivery path is:

**#1 A → #2 B → #3 C → #6 F → #8 H → #9 I → #11 K → #12 L → #16 P → #21 U → #22 V → #26 Z**

The precise critical path may move as estimates are refined, but no roadmap expansion may bypass the validation gates.

## Parallel tracks

**Demand:** #1 → #2 → #3, with #4 → #5 running as a parallel landing/acquisition test.

**Trust:** #6 → #7 → #11/#12/#13/#16 → #21.

**Distribution:** #16 → #17 → #24, with #23 building founder-led prospecting from discovery evidence.

**Economics:** #19 establishes metering; #22 supplies real usage/support evidence; #25 measures paid acquisition; #26 makes the commercial decision.

## Gate policy

- No RMA/helpdesk expansion before #22/#26 evidence.
- No Amazon connector before Shopify pilot evidence.
- No DPP/compliance claims without a separate legal/compliance workstream.
- No paid scale campaign before activation and retention are measurable.
- Negative market evidence can stop or reshape the technical critical path.
