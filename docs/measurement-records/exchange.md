# Native `.rime` exchange

The native reader and writer now use **RIME JSON-LD profile 1.1**. This exchange-version
number is independent of application v0.2. Previous experimental snapshot formats are
not accepted. The desktop exports native records from annotation and review workspaces and opens them in an independent inspector.

A document has an inline `@context`, document identity and creation time, `rime:records`
(result references), and `@graph` (shared named components). Every component has an
absolute URN identity. The document stores no media bytes, samples or local file paths.
The project vocabulary is `urn:rime:vocab:`; this is an identifier, not a hosted ontology.

The complete normative [closed contract](rime-specification.md) defines
methods, source subtypes, roles, cardinalities, responsibility and calculation rules.
The reader rejects profile 1.0; there is no compatibility adapter.

## Components and relationships

Named scientific components have exactly one PROV base type:

| Base type | RIME clinical types |
|---|---|
| `prov:Entity` | `rime:Source`, `rime:AnnotationSet`, `rime:ObservationPeriod`, `rime:CalculationDefinition`, `rime:MeasurementResult` |
| `prov:Activity` | `rime:AnnotationProduction`, `rime:AnnotationReview`, `rime:MeasurementCalculation` |
| `prov:Agent` | Person, group or computational model, declared in its attributes |

Relationships use `prov:used`, `prov:wasGeneratedBy`, and `prov:wasAssociatedWith`.
`prov:qualifiedUsage` supplies standard `prov:Usage` edge qualifications with
`prov:entity` and `prov:hadRole`. These anonymous qualification objects describe input
roles/mappings; they are not additional scientific stages or user-facing nodes.
The unqualified and qualified uses must agree.

Clinical attributes are ordinary JSON under `rime:data`, declared as a JSON-LD JSON
literal. Thus a standard RDF reader preserves interval arrays and procedure settings
without turning every interval, field or decision into a graph node. A RIME reader
validates and interprets those attributes. Generic RDF parsing alone does not validate
clinical calculations or certify full PROV conformance.

Each result references one calculation. Its required input roles are `rime:annotations`,
`rime:observation`, `rime:definition`; optional `rime:scope_annotations` retains a separate
set used to resolve observation time. Scope selections retain the selected annotation IDs
and `selected_annotations` rule. Both resolved intervals and selection must agree.
The definition captures operation, version, lane/label selector and unit. Calculation
version 1 fixes half-open millisecond intervals, union coverage, seconds for duration,
percentage over eligible time, and literal contributor count. An empty observation gives
an undefined value; no events within a nonempty observation gives zero. Review status is
separate. Point annotations are supported for count only.

The machine schema is shipped as
`packages/rime-core/src/rime_core/config/schemas/rime-1.1.schema.json`.
The native validator additionally checks references, allowed generator/input kinds,
acyclicity, reachability from results, timing, selections, contributor identities,
calculation components/value and review input/output references. Review decisions are
final scientific decisions, not interaction logs. Validation does not establish that a
reviewer's boundary choice is clinically correct, or reconstruct unknown history.

## API

```python
from rime_core.exchange import RimeDocument, read_document, write_document

# nodes use the documented JSON-LD shape; record_ids identify result entities.
document = RimeDocument.create(nodes, record_ids)
write_document("measurements.rime", document)
received = read_document("measurements.rime")
```

`entity`, `activity`, `agent` and `calculate` provide native construction helpers.
A `RimeDocument` validates on creation and retains an immutable serialized capture;
`nodes` and `to_dict()` return detached data. Saving validates before replacement and
writes atomically. Readers do not fetch contexts, load media or execute procedures.
The reader accepts this bounded JSON-LD profile, not arbitrary equivalent JSON-LD
compactions. It is not a generic PROV importer. Source hashes identify available original
files when supplied; missing media identity remains unknown. Source relinking in the record inspector is deferred. Records are not digitally signed or tamper-proof.

## Inspect now

The compact [software examples](https://github.com/neurocog-mobility/rime/tree/main/examples)
include editable native workflows and a synthetic import record. From the repository root:

```sh
.venv/bin/python -m rime_ui --open examples/measurement-record/example.rime
.venv/bin/python -I -S examples/measurement-record/read_rime.py examples/measurement-record/example.rime
uv run --with rdflib python examples/measurement-record/check_prov.py examples/measurement-record/example.rime
```

The synthetic import contains 10% coverage, 6 seconds covered duration, and one
FOG interval in a 60-second observation. No participant data are used.

The independent arithmetic script uses endpoint partitioning without importing RIME.
RDFLib checks the standard PROV entities, activities, agents, edges and roles, preservation
of JSON attributes, and a Turtle serialization round trip. These checks establish bounded
interoperability and arithmetic, not full PROV constraint validation or clinical validation.
## Pairwise comparison

Native records can be compared using `rime_core.record_comparison`. See the
[comparison contract and CLI](comparison.md). This operation leaves the file format
and inputs unchanged and does not calculate a provenance similarity/distance score.

A model package can be retained as one `rime:Source` Entity using
`source_kind: "model_package"`, an exact archive `sha256`, and a `manifest` of
constituent `file_name`/`sha256` pairs. `scope` declares what the snapshot includes;
`digest_scope` specifies the hashed representation. A capture may use a
post-execution deterministic archive of its four runtime artifacts. It does not
claim that the archive itself existed at execution time. Effective settings and
package-default overrides remain in the generating Activity. Individual manifest
entries participate in attribute comparison without becoming separate graph nodes.

Calculation and import have no Agent associations. Manual annotation and review use Person/Group Agents (or explicit unknown responsibility); computational annotation requires one Model Agent. Production methods and review methods are enumerated. Implementation descriptions belong in `metadata`, not arbitrary Activity-data fields.

