# UML (Downloadable)

## Source of truth
- `docs/uml/phins_platform_overview.puml` — **multi-page** PlantUML covering the entire platform:
  - system context
  - component architecture (includes Investment + Banking/Custody)
  - domain model
  - key sequence (best-price health wallet checkout)
  - order state machine

## Render diagrams locally

### Option A — PlantUML (recommended)

```bash
plantuml -tsvg docs/uml/phins_platform_overview.puml -o rendered
plantuml -tpng docs/uml/phins_platform_overview.puml -o rendered
```

Outputs will be written to `docs/uml/rendered/`.

### Option B — VS Code extension
- Install “PlantUML” extension, open the `.puml`, and use “Preview”.

