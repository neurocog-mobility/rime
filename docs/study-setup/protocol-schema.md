# Clinical protocol

The protocol JSON defines a study's annotation lanes, labels, relationships and rules, and
its available measurement outcomes. It is shared across workspaces and retained with each
annotation set. No separate outcome file is needed.

## What it controls

- Annotation lanes and labels on the timeline.
- Hierarchy, automatic effects and violation checks.
- Named outcomes: their calculation, event selection and optional eligible-time selection.

Load a protocol JSON during workspace setup. Click a measurement value in the
workspace to inspect its calculation and contributing annotations.

## Minimal example

```json
{
  "name": "Walking study",
  "version": "1",
  "lanes": [
    {"name": "Tasks", "level": 1, "color": "#4a90a4", "labels": ["Walk"], "allow_overlap": false},
    {"name": "FOG", "level": 2, "color": "#d36161", "labels": ["FOG"], "allow_overlap": false}
  ],
  "groups": [],
  "rules": [],
  "measurements": [
    {
      "id": "fog_count",
      "name": "FOG episode count",
      "version": "1",
      "calculation": "count",
      "calculation_version": "1",
      "events": {"lane": "FOG", "label": "FOG"},
      "scope": {"lane": "Tasks", "label": "Walk"}
    }
  ]
}
```

The implemented calculations are `covered_duration`, `percentage_coverage`, and `count`.
`label: null` selects all labels in a lane. `scope: null` uses the entire observation period. Outcome IDs must be unique within the protocol, selectors must name existing
lanes, and duration/percentage and scope selections require interval lanes. Count can also
select point lanes. An omitted or empty `measurements` array leaves annotation work available
without adding implicit outcomes.

Outcome `version` identifies the study's definition; `calculation_version` identifies the
backend arithmetic contract. Both default to `"1"`. The calculation returns its own unit;
protocol authors do not supply a unit or executable formula. Update the outcome version when
changing its meaning or selections. Saved records retain their effective definitions.

## Use a study protocol

Select a JSON file in the Workspace Wizard. RIME retains its contents with the annotation set,
so reopening does not require the original file. The bundled `gpfog_schema.json` is a complete
working example with all three outcomes. Agree on annotation meanings with the study team;
for an episode count, one retained annotation must represent one episode.

See [measurement semantics](../measurement-records/specification.md) and
[rules and violations](../annotation/rules-and-violations.md).
