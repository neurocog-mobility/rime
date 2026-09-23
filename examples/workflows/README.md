# Native workflow examples

The `generated/` folder contains synthetic evidence only: two 20-second videos,
a 100 Hz signal, a tiny threshold model and four editable workspaces. It covers
all three application flows without depending on a study dataset.

From the repository root:

```sh
.venv/bin/python -m rime_ui --open examples/workflows/generated/annotation.json
.venv/bin/python -m rime_ui --open examples/workflows/generated/suggestions.json
.venv/bin/python -m rime_ui --open examples/workflows/generated/review.json
.venv/bin/python -m rime_ui --open examples/workflows/generated/records/manual.rime
```

## Populated review example

[review-demo/](review-demo/README.md) contains two saved decisions with notes and
an unresolved pair of inputs. It uses the existing synthetic recordings and is
intended for testing review selection, editing, save/resume and measurement export.

```sh
.venv/bin/python -m rime_ui --open examples/workflows/review-demo/review.json
```

## Manual inspection

1. **Annotation:** play both views and the signal; edit an interval, undo/redo,
   adjust the secondary offset, save and reopen. Initial events cover 2–4 and
   7–9 seconds: duration 4 s, coverage 20%, count 2 over the 20-second observation.
2. **Model suggestions:** inspect the three pending proposals at 2–4, 7–9 and
   13–16 seconds. Accept, modify or reject them; save and reopen. Pending proposals
   do not contribute to measurements. Run `threshold.cmf` against the `value`
   channel to exercise model configuration and execution.
3. **Review:** inspect the saved union decision from two synthetic raters. Edit,
   remove or create decisions; try reusing an input and inspect the shared-input
   marker. Add an event absent from the inputs. Original inputs remain unchanged.
   The initial reviewer output covers 2–4.5 and 7–9.5 seconds: 5 s, 25%, count 2.
4. **Capture:** save records from either workspace, continue editing, and verify
   that the exported records retain the captured state. Open them independently.
5. **Inspector:** inspect nodes, recalculate and add a second record using Open.
   The `annotation_output`, `measurement_output_only` and `neither` pairs cover
   identical intervals, different intervals with equal counts, and different
   intervals with different counts. Remove either side and return to single view.

The raw second-rater workspace is `review-input-b.json`. It is retained to create
new reviews with `annotation.json`.

## Regenerate or reset

Use an empty destination so existing manual edits are preserved:

```sh
.venv/bin/python examples/workflows/create_examples.py /tmp/rime-workflow-examples
.venv/bin/python -m rime_ui --open /tmp/rime-workflow-examples/annotation.json
```

The generator executes only the tiny synthetic threshold model. It creates new
identities and references evidence in the chosen directory. No clinical inference
or participant data are involved.

Workspace file paths are relative to the JSON file. Copy `generated/` and
`review-demo/` together when moving these examples; the review demo shares the
generated media. Local real-data demos are excluded from the software repository.
