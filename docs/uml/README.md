# UML (Downloadable)

## Source of truth
- `docs/uml/phins_platform_overview.puml` — **multi-page** PlantUML covering the current broad platform architecture:
  - system context
  - component architecture (includes Investment + Banking/Custody)
  - domain model
  - key sequence (best-price health wallet checkout)
  - order state machine
- `docs/uml/health_marketplace_target.puml` — future-state PlantUML for the global health marketplace:
  - health marketplace system context
  - target component architecture
  - wallet-safe marketplace and external payer domain model
  - coverage-aware purchase, settlement, and reimbursement sequence
  - marketplace financial lifecycle state machine

## Render diagrams locally

### Option A — PlantUML (recommended)

```bash
plantuml -tsvg docs/uml/phins_platform_overview.puml -o rendered
plantuml -tpng docs/uml/phins_platform_overview.puml -o rendered
plantuml -tsvg docs/uml/health_marketplace_target.puml -o rendered
plantuml -tpng docs/uml/health_marketplace_target.puml -o rendered
```

Outputs will be written to `docs/uml/rendered/`.

### Option B — VS Code extension
- Install “PlantUML” extension, open the `.puml`, and use “Preview”.

