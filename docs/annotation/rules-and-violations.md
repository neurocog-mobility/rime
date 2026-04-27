# Rules & Violations

RIME's rule engine enforces annotation consistency automatically, based on rules declared in the protocol schema.

## What rules do

Rules fire when an annotation is created or modified. They can:

- **Auto-create side-effect annotations** in other lanes (e.g. marking a task boundary automatically when a FOG event is placed)
- **Flag violations** when an annotation breaks a protocol constraint (e.g. a FOG label placed outside a valid walking bout)

## Violation dialog

When a violation is detected, a dialog appears describing the issue and offering resolution options.

- **Auto-fix** — RIME resolves the violation automatically (available for some rule types)
- **Dismiss** — override the rule and keep the annotation as-is
- **Cancel** — undo the annotation that triggered the violation

## Side effects

Side-effect annotations are auto-created and visually distinguished from manually placed annotations.

## Defining rules in the schema

Rules are declared in the schema JSON under the `rules` key. Each rule specifies a trigger (`create`), a source lane, an action (e.g. `auto_create`, `must_be_subset_of`), and a target lane. See the bundled `gpfog_schema.json` for a complete example.

!!! note
    Rules are advisory by default. The annotator always has the option to dismiss a violation.
