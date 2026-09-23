# Create a workspace

1. Choose **New workspace** on Start or **File → New workspace…**.
2. Enter a name and save folder. Select a protocol or **Load…** a protocol JSON; optionally enter Participant, Visit and Trial. Click **Next**.
3. Add a required primary video, an optional second view, and signal CSV files. Confirm signal timing and display channels when prompted.
4. Optionally **Import EAF…**, mapping its tiers and labels to protocol lanes.
5. Enter synchronization notes, including any synchronization done before import. Choose whether to **Align sources before annotating**.
6. Click **Continue to alignment** or **Begin annotation**.

The primary video defines the reference timeline. **Alignment…** previews constant
offset changes live; notes and offsets describe your mapping, not independent
verification. Drift correction requires preprocessing.

The workspace references external recordings. Use **File → Save workspace** to
save edits and reopen its JSON to resume. **Details…** edits the name, annotator
and existing research context.

Next: [annotate](../annotation/workflow.md), [review](../quality-assurance/review-layers.md),
or [save measurements](../clinical-analysis/clinical-metrics.md).
