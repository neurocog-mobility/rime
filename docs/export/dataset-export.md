# Dataset export

Choose **File → Export dataset…** in an annotation or review workspace to export
the currently open workspace using the existing BIDS / Motion-BIDS dataset writers.

1. Choose a new or empty destination folder.
2. Enter participant and session IDs using letters and numbers, without `sub-` or
   `ses-` prefixes. Existing workspace identifiers prefill these fields.
3. Optionally include full sensor recordings and annotation-based signal clips.
4. Confirm that annotation and signal timing is aligned to Video 1, then choose
   **Export dataset**.

Annotations and dataset metadata are always included. Events and full recordings
are written as TSV files with JSON sidecars; signal clips are Parquet derivatives
using the retained annotation intervals without additional padding. Videos are not
copied. Full sensor export requires regular sampling at the configured rate; signal
clips preserve the loaded sample times relative to each annotation.

Annotation workspaces export retained annotations, excluding pending suggestions.
Review workspaces export the output of saved reviewer decisions, excluding
unresolved inputs and unsaved decision previews. The export uses a snapshot of the
current workspace and does not require saving the workspace file first.

Existing datasets are not overwritten or extended. Files are prepared in a temporary
folder and moved to the destination only after a successful export.

Dataset organization is separate from measurement-record export: `.rime` files do
not prescribe a BIDS directory layout. Use **Save records…** for measurement records.

See [saving and comparing measurements](../clinical-analysis/clinical-metrics.md).
