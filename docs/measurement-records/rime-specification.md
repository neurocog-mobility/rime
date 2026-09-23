# RIME measurement record specification — closed contract 1.1

**RIME — Reproducible Interval-derived Measurement Exchange.**

This document is the normative contract for the native reader, writer, comparison
operation and reference application. Profile **1.1** supersedes the permissive 1.0
prototype; it is distinct from application version v0.2. There is no compatibility
adapter. The wire schema is
[the JSON Schema](https://github.com/neurocog-mobility/rime/blob/main/packages/rime-core/src/rime_core/config/schemas/rime-1.1.schema.json);
[record_contract.py](https://github.com/neurocog-mobility/rime/blob/main/packages/rime-core/src/rime_core/record_contract.py) enforces
cross-node constraints. The schema and semantic validator must both pass.

## 1. Purpose and record boundary

A record is one interval-derived measurement and the retained basis for interpreting
and recalculating it. It is rooted at one MeasurementResult Entity. Its complete
record is the dependency closure reachable through the three relations below. A
plain-JSON `.rime` document holds one or more such roots and their shared components.
Media bytes, workspace state and an interface-action log are not required contents.

RIME records fixed scientific states. A changed annotation state receives a new
Entity identity. Production and review capture final states and decisions, not
individual clicks, boundary drags, playback, undo operations or workspace saves.
Only scientific objects used in the retained derivation belong in its graph.

## 2. Closed node vocabulary

There are three PROV classes and eleven permitted RIME kinds. Agent kinds are encoded
in `rime:data.kind`; Entity and Activity kinds are encoded as a second `@type`.

| Class | RIME kind / serialized value | Required contents |
|---|---|---|
| Entity | Source reference / `rime:Source` | `source_kind`, filename, checksum or explicit unavailable checksum |
| Entity | Annotation set / `rime:AnnotationSet` | Stable annotation IDs, lane and label, interval/point type, boundaries, timeline, retained/proposed state, review status |
| Entity | Observation period / `rime:ObservationPeriod` | Timeline and resolved observation intervals; selected annotation IDs and selection rule when annotation-derived |
| Entity | Calculation definition / `rime:CalculationDefinition` | Operation, version, clinical lane/label selector and unit |
| Entity | Measurement result / `rime:MeasurementResult` | Value, unit, eligible and covered duration, contributing annotation IDs and undefined-result reason where applicable |
| Activity | `rime:AnnotationProduction` | Enumerated method, description, clinical-definition declaration; effective execution specification for computational production |
| Activity | `rime:AnnotationReview` | Enumerated review method and final structured decisions |
| Activity | `rime:MeasurementCalculation` | The specified calculation inputs; optional implementation metadata |
| Agent | Person / `person` | Name or retained pseudonymous designation |
| Agent | Group / `group` | Responsible team designation |
| Agent | Computational model / `model` | Responsible model designation |

Source subtypes are exactly `recording`, `annotation_file`, `model_package`.
Recordings declare modality `video` or `signal`. A model package retains a manifest
of unique constituent filenames/checksums, the snapshot scope, and the exact hashed
representation. A constituent file is not independently promoted to an Entity merely
because it is a file. Record a separate object only when independently consumed or
produced by the allowed scientific activity. Package metadata/defaults do not replace
its effective execution settings.

The model acting as annotator is an Agent; its fixed package is an Entity. RIME or
another application is not an annotation Agent merely because it hosts the workflow.
Application versions, execution libraries and import tooling belong in metadata.

The relevant protocol contents are retained with the annotation procedure's clinical
definition and the calculation definition. Clinical-definition attributes may name
the protocol and version. There is no Protocol node and a protocol is not an Agent.

## 3. Closed relation vocabulary

| Relation | Direction | Meaning |
|---|---|---|
| `prov:used` | Activity → Entity | The declared scientific input, qualified by a permitted input role |
| `prov:wasGeneratedBy` | Entity → Activity | The operation that established the fixed output |
| `prov:wasAssociatedWith` | Activity → Agent | Responsibility for scientific annotation production or review |

The graph is acyclic, identities are unique within a document, and all graph
references resolve locally. Each Activity has exactly one retained output Entity
of its permitted kind. Each annotation set has exactly one generating production or
review Activity, or no generating Activity with `history: "unknown"`. Every result
has exactly one generating calculation. Source references, observation periods and
calculation definitions have no generating Activity in this profile. Agents have no
outgoing relations. Results are document roots; no unrelated nodes are allowed.

Shared ancestors may serve multiple Activities. Graph depth is not a scientific
constraint: a shared object need not occupy the same display layer as every user.
Local repeated display references may preserve one identity without inventing nodes.

## 4. Complete activity connection matrix

Only these combinations are permitted. `1+` means at least one; `0..1` means optional
and at most one. Multiple labels/lanes can be retained in a single annotation set.

| Activity | `method` | Permitted inputs (role: kind and count) | Output | Agent rule |
|---|---|---|---|---|
| Annotation production | `manual` | `recording`: recording Source, 1+ | One AnnotationSet | One or more Person/Group Agents, or explicit unknown responsibility |
| Annotation production | `computational` | `recording`: recording Source, 1+; `model_package`: model-package Source, exactly 1; `scope_annotations`: AnnotationSet, 0..1 | One AnnotationSet | Exactly one Model Agent |
| Annotation production | `import` | `import_file`: annotation-file Source, exactly 1 | One AnnotationSet | No Agent association |
| Annotation review | `verification` | `annotation_input`: AnnotationSet, 1+; `recording`: recording Source, 0+ | One retained AnnotationSet | One or more Person/Group Agents, or explicit unknown responsibility |
| Annotation review | `adjudication` | `annotation_input`: AnnotationSet, 2+; `recording`: recording Source, 0+ | One retained AnnotationSet | One or more Person/Group Agents, or explicit unknown responsibility |
| Measurement calculation | No method field | `annotations`: retained AnnotationSet, exactly 1; `observation`: ObservationPeriod, exactly 1; `definition`: CalculationDefinition, exactly 1; `scope_annotations`: AnnotationSet, 0..1 | One MeasurementResult | No Agent association |

The eight input-role tokens in this table are the entire permitted input-role
vocabulary. Their serialized `prov:hadRole` values have prefix `rime:`. Roles cannot
be freely coined, nor can an allowed role be used with the wrong Entity subtype.
The output and cardinality rules apply to every Activity, not just the root's inputs.

Imported historical authorship is metadata, not responsibility for the import.
An unknown author does not become the importing software. A known earlier scientific
production/review can instead be retained as that earlier Activity when available.

Scope annotations are an explicitly declared extra input, not an arbitrary shortcut.
For calculation they are permitted only when selected annotations define observation
time. Their IDs, selection rule and resolved intervals must agree. If the event set
also supplies scope, it is referenced directly without creating a second set.
For computational production the scope set is retained and shares the output timeline.
Its use and the effective execution specification describe the execution boundary.

## 5. Methods, decisions, temporal mappings and responsibility

Production methods are exactly `manual`, `computational`, `import`. Review methods
are exactly `verification`, `adjudication`; these are values, not new node types.

Every production has a clinical-definition declaration with `status: "known"` and
retained descriptive content, or `status: "unknown"`. A known definition can also
carry its identifier/version and protocol identifier/version. Unknown content is not
silently inferred from a familiar label. Computational production must retain an
`execution_specification` object; other production methods may not use that field.
A computational `configuration_id` is optional. Parameter keys and values follow the
retained computational procedure (CMF where applicable); they are not graph roles.
Generic validation checks the graph contract, not the correctness of an arbitrary
model implementation or whether its description is clinically adequate.

Review decisions are exactly `accept`, `modify`, `reject`, `reject_remaining`,
`union`, `intersection`, `mean`, `custom`, `no_event`, `unresolved`. Each retains
input set/annotation references, output annotation IDs, a nonempty temporal extent,
and an optional note. Outputs must account for the reviewed set exactly, without
duplicate output assignments. Reject/no-event/unresolved decisions have no outputs.
Unresolved decisions cannot accompany a `complete` review status. Recorded arithmetic
boundary rules are not automatically evidence of clinical consensus. Validation checks
referential and temporal consistency, not the clinical correctness of decisions.

Every recording use includes an explicit mapping status `known` or `unknown`.
A known mapping has a finite `offset_ms` and method `manual_offset` or `import`:
**record timeline time = source-relative time + offset**. Source timestamp conversion
and alignment-validation descriptions may accompany that use. Nonconstant errors
require correction before capture; they are not represented as constant offsets.

New workspace setup and the annotation workspace's alignment dialog accept synchronization notes for each
source, including sources synchronized before import with no additional offset.
Researchers can describe the prior synchronization method, tools, timing cues and
checks. These notes persist with the workspace and accompany recording usage as
`alignment_validation` in captured records. They are researcher declarations, not
an automated validation of alignment. Computational runs retain the notes present
at execution time.
Mapping attributes are permitted only on recording or import-file uses. No interactive
registration event or timing-adjustment Agent is created.

Manual production and review identify known Person/Group Agents or declare
`responsibility: "unknown"`, never both. Computational production identifies its
Model Agent. Calculation and import have neither associated Agents nor unknown-Agent
placeholders. Unknown authorship/history belongs to the affected retained information.

## 6. Calculation contract

All annotation and observation coordinates are finite milliseconds on an explicitly
identified common timeline. Intervals are half-open `[start, end)` with start < end;
point annotations have equal start/end. Observation intervals are unioned, including
overlap/touching, before use. Selected event intervals are clipped to that union.

| Operation (version `1`) | Unit | Rule |
|---|---|---|
| `covered_duration` | `s` | Duration of the union of clipped selected intervals, divided by 1000 |
| `percentage_coverage` | `%` | 100 × covered duration / eligible observation duration |
| `count` | `count` | Number of selected annotation entries contributing inside the observation; each entry counts once |

Count does not infer episode identity or merge distinct entries. A point contributes
when its time is inside an eligible half-open observation interval. Points cannot
supply duration/percentage calculations. An interval touching only an observation
boundary does not contribute. Empty observation yields `value: null` and
`reason: "empty_observation"` for all three operations; nonempty observation with no
selected events yields zero. Output includes covered/eligible milliseconds and sorted
contributor IDs. The reader verifies the retained value against these inputs.

Annotation states are `retained` or `proposed`; review states are `unknown`,
`unreviewed`, `incomplete`, `complete`. Proposed annotations cannot silently become
measurement inputs. Retained annotations may remain unreviewed/incomplete; the status
is preserved and does not constitute clinical validation. Review is not compulsory.

## 7. Fixed fields, extensible scientific data and missing history

Top-level node and Activity-data keys are closed by the machine schema. Additional
clinical labels, participant/context values, model parameters and implementation
information live in their designated fields: clinical definition, research context,
execution specification and metadata. These fields do not introduce graph nodes,
input roles, responsibility associations or substitute for required scientific inputs.
Import historical details and execution-environment details are metadata. There is no
catch-all Activity method or additional graph-edge type.

Missing provenance is explicit. An imported annotation's original history may be
unknown while the import itself is known. A file checksum may be unavailable; this
prevents claiming verified identity. The arithmetic basis is always present. These
rules permit recalculation without media, but do not promise that a detector can be
rerun without its recordings, package and required environment.

## 8. Exchange, overlay and presentation

The encoding is bounded PROV-O in JSON-LD: inline fixed context, `@graph`, URN node
identities, `rime:version: "1.1"`, timezone-aware capture time and explicit root IDs.
Qualified Usage describes the role and timing attributes of `used`, not a fourth
scientific relationship or Activity. Native readers accept only profile 1.1.

Comparison aligns roots and corresponding typed input roles; identity and unique
source digests disambiguate where possible. Ambiguity is retained, not guessed by
array position. Statuses are shared, equal, changed, A-only, B-only and unavailable.
Conflicting contents under one identity are changed. Distinct equal components may
share a displayed node while retaining both originals and A/B edge membership.
Unknown provenance is never promoted to known equality. Each original record can be
recovered from its side of the overlay. No aggregate similarity/distance is defined.

Every graph node in a publication figure is an actual Entity, Activity or Agent (or
an explicitly identified repeated reference). No mixed `Inputs` node is permitted.
A model-package Entity is one coherent fixed object, not arbitrary visual grouping.
Short labels and status colours can simplify the figure without changing relations.
