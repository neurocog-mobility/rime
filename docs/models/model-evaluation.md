# Model Evaluation

After running a model, RIME can evaluate its output against your gold-standard annotations.

## Opening the Model Evaluation panel

**View → Model Evaluation**


## What the panel computes

Evaluation compares model-detected events to annotated events in the corresponding lane.


| Metric | Description |
|---|---|
| Sensitivity | True positive rate (detected FOG / annotated FOG) |
| Specificity | True negative rate |
| F1 score | Harmonic mean of precision and recall |
| Event overlap | Per-episode overlap between detected and annotated events |

## Evaluation window

You can restrict evaluation to a specific task condition to compare model performance across walking contexts.

## Exporting evaluation results

Evaluation metrics are included in the session export. See [Export & Reports](../clinical-analysis/export.md).
