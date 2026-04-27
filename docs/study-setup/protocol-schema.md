# Protocol & Schema

The schema defines the annotation structure for your study — which lanes exist, what labels are valid, and what rules govern annotation behaviour. It is configured once per study and shared across all sessions.

## What the schema controls

- **Annotation lanes** — the horizontal rows on the timeline (e.g. FOG, Gait Phase, Context)
- **Labels** — valid label values within each lane
- **Hierarchy** — L1–L5 nesting relationships between lanes
- **Rules** — automatic side-effects and violation checks (see [Rules & Violations](../annotation/rules-and-violations.md))

## Viewing the schema

**View → Schema Browser** opens the schema inspector.

## Schema file format

```json
{
  "lanes": [
    {
      "id": "fog",
      "label": "FOG",
      "level": 1,
      "labels": ["FOG", "Trembling-in-Place", "Akinesia"]
    }
  ],
  "rules": []
}
```

## Creating a schema for a new study

Place the schema JSON file anywhere accessible on disk. Reference it in the Session Wizard when creating a session — RIME stores the path in `session.json`. The bundled GP-FOG schema (`gpfog_schema.json`) serves as a complete working example.

!!! note
    Schema design decisions affect all downstream analysis. Align on label definitions with all annotators before beginning data collection.
