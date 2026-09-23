# Examples

From a source checkout, run these commands in the repository root:

```sh
rime --open examples/workflows/generated/annotation.json
rime --open examples/workflows/generated/suggestions.json
rime --open examples/workflows/review-demo/review.json
```

The examples use synthetic recordings. The review includes saved decisions, notes
and unresolved inputs.

For comparison, open:

```sh
rime --open examples/workflows/generated/records/measurement_output_only.a.rime
```

Then use **Open…** inside the inspector to add `measurement_output_only.b.rime`
from the same folder. The pair has different annotations but equal counts.

See the [workflow README](https://github.com/neurocog-mobility/rime/tree/main/examples/workflows)
for reset instructions. Public examples use synthetic evidence; local participant
data and manuscript files are excluded from the software repository.
