# Pairwise RIME record comparison

Implemented in `rime_core.record_comparison`, comparison version 1.0. The native
`.rime` format is unchanged. This compares retained information, not clinical
equivalence, causal effects, or a provenance similarity/distance score.

## Input and output

`compare_records(document_a, document_b, record_a=None, record_b=None)` accepts
validated `RimeDocument` objects. A root ID is required for any multi-record document.
Only the chosen measurement and its reachable dependencies are compared; unrelated
records and document-container timestamps are outside the record comparison.

The returned JSON-serializable object contains:

- `components`: aligned components with both identities, types, matching basis,
  attribute differences and qualified relationship differences. Unmatched components
  retain their entire original node.
- `alignment_issues`: unresolved repeated-role correspondences, with both candidate
  lists. No arbitrary pairing is manufactured.
- `numerical_comparison`: both result values/units, applicability reasons, signed
  difference **B minus A**, and absolute difference.

Attribute/relationship/component status is `equal`, `different`, `only_a`, `only_b`,
or `unavailable`. Every comparable attribute retains both supplied values, or explicit
presence flags if a side has no value. Paths identify fields within a node's data.
Annotation-array paths use `/annotations/by_id/<escaped ID>` rather than positions.
These are semantic paths, not literal pointers into the original array.

`identity_status` separately distinguishes `shared` identity from `distinct` identities.
Equal contents do not establish the same historical object. Conflicting retained
contents under the same ID are flagged by `identity_conflict`.

## Correspondence and equality

1. Pair the selected measurement roots; pair exact node identities in their closures.
2. Traverse aligned parents through generation, qualified input roles and agent
   associations. Pair unique corresponding relationship slots, including when the
   two slots contain different clinical types (the type difference remains explicit).
3. In repeated roles, unique non-null source SHA-256 matches can disambiguate source
   references. Remaining unique role/type slots can be paired. Filenames and list
   positions are never used to guess among ambiguous repeated inputs.
4. Leave remaining candidates unmatched and report ambiguity. `only_a`/`only_b`
   means no established counterpart under these rules, not proof that no counterpart
   could exist. Shared dependencies appear once per record closure.

Both declared node types and all retained `rime:data` attributes are compared.
Reference attributes are compared through the established node correspondence;
the original reference values remain available. A `used` relationship includes
its qualified role and mapping attributes. The redundant direct `used` edge and
its qualification are represented together, preserving all their information.

Graph order, relationship order, annotation order, contributor order, observation
interval order and review decision order do not establish correspondence or create
differences. Annotations with the same local ID can be compared inside paired sets;
this is not temporal episode matching or evidence of independent-rater agreement.
Different local IDs are retained separately. Review decisions are compared as an
unordered collection, including their input/output references; their stored order
does not imply a chronological editing history. Arbitrary parameter vectors remain
ordered atomic attributes. No clinical-label or timing harmonization is performed.

Known explicit unknown-provenance fields (`history`, `original_annotation_history`,
`responsibility`, `review_status`, `media_identity`, `original_author`,
`alignment_validation`, and mapping `status`) with value `unknown` are unavailable,
even when both sides contain the same marker. Null source hashes/authorship/media
identity are also unavailable. Missing attributes remain one-sided; absence is not
automatically unknown. Null event selectors, null calculation reasons, and known
`unreviewed` status are not missing provenance. Other free-text metadata are compared
literally rather than interpreted by a language model.

## Numerical applicability

Compare the complete retained calculation definitions. If they are equal and the
result units agree, subtract B minus A and return its absolute value. Native version
1.0 has one canonical unit for each supported operation; no conversion is needed or
silently applied. Different definitions/selectors/units produce `not_applicable` with
the differing definition paths and values. Undefined values also produce a reason.

Different observation periods or source recordings do not prohibit arithmetic when
the user's definition/unit condition is met. Their structural differences remain
visible; arithmetic applicability is not a claim of clinical comparability.

Temporal disagreement and IoU are deliberately absent from this generic operation.
Applications may calculate interval-comparison metrics separately.

## Command line

```sh
.venv/bin/python -m rime_core.record_comparison record-a.rime record-b.rime --output comparison.json
```

For multi-record files, supply `--record-a <root ID>` and/or `--record-b <root ID>`.
This command and the Python API do not modify their inputs or require media files.

## Comparison graph view and Mermaid export

`rime_core.comparison_view.build_comparison_view(diff, document_a, document_b)`
produces the UI-independent graph view. `to_mermaid(view, ...)` renders that same
view as Mermaid; there is no exemplar-specific topology or manually assembled
"shared source/model" node. Source files remain the actual recorded entities.

The rendering rules are:

1. One view node represents an aligned pair only when its local retained contents
   and all its retained dependency branches can be shared. Distinct identities with
   equal retained bases are labelled accordingly, not called the same historical event.
2. Otherwise retain A and B nodes separately. A node with equal local contents but
   differing dependencies is labelled **equal content, different lineage**. Thus equal
   results do not reconnect different execution histories into a misleading common path.
3. Common identity with the same explicit unknown markers may be drawn once, with
   its unavailable provenance still marked. Unknown information is not asserted equal
   or complete. One-sided components stay on their respective sides.
4. Every original relation is retained on the correct side. Solid display arrows run
   from inputs/agents to activities and activities to outputs (the reverse of the
   stored dependency direction). Each view edge retains its original PROV relation,
   qualified role, owner/target identities and attributes for inspection.
5. Numerical differences are separate comparison annotations, not provenance nodes.
   Any temporal disagreement/IoU label is supplied separately from the sensitivity
   analysis. No execution-field count is rendered as a distance.

Every view node retains its comparison component, original IDs, full source nodes,
attribute differences and display state. The desktop provides a clickable record inspector and comparison view; see
[the application workflow](../clinical-analysis/clinical-metrics.md). Mermaid labels use type-based summaries, six
significant digits for numbers, and up to four changed scalar activity attributes.
Long labels are abbreviated only for display; complete values/paths remain in the
`.view.json` output. Ambiguous correspondence remains visible in `alignment_issues`.

The original records, generic diff contract, sensitivity outputs and exemplar selection
are unchanged by this rendering layer.

## Full record overlay

`rime_core.record_overlay.overlay_records(a, b, record_a=None, record_b=None)`
compares selected measurement closures and returns a layout-independent overlay.
It includes every retained entity, activity, agent and relationship. No scientific
role, file type, or activity chain is selected for inclusion by the renderer.

Aligned Entities and Agents collapse when their local types and data compare equal.
Activities additionally require matching directly used input contents, roles,
usage attributes and multiplicity. Otherwise the Activities remain separate and
are marked changed, even when their own attributes match. Equal input Entities
may have different earlier histories; this allows genuine convergence of content
without requiring entire ancestral graphs to match. A collapsed node is a display equivalence
group, not a newly asserted provenance entity. Original identities, payloads and
A/B membership remain attached. Unknown provenance is never promoted to equality:
identical unknown payloads may share a display node only for the same identity,
and remain marked unavailable. Identity conflicts remain separate. Ambiguous
alignment remains explicit in the comparator output.

Edges collapse only when their displayed endpoints, relation, role and normalized
qualified attributes agree. Multiplicity and each side's original relationship
attributes are retained. Follow one side consistently through every fork and merge;
an unlabelled traversal could combine unrelated pieces of A and B. If collapsing
would create a cycle, the operation disables collapse and reports the reason.

`recover_record(overlay, side)` recovers the selected root and exact original node
payloads, including relationship representations. It does not reproduce unrelated
records or document-level packaging. `to_mermaid(overlay)` emits the full graph
with native PROV arrow direction and automatic layout; it does not hide inputs.

The native inspector retains both original records in its overlay model.
