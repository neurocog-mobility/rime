# Inter-Rater Reliability

RIME computes inter-rater reliability (IRR) scores directly from two annotation sets loaded in the same session.

## Opening the IRR panel

**View → IRR Panel**


## What RIME computes

| Metric | What it measures |
|---|---|
| Cohen's Kappa | Agreement corrected for chance (frame-level) |
| F1 / overlap | Event-level detection agreement |
| Episode count | Number of events per rater |
| Total duration | Summed duration of annotated events per rater |

## Interpreting the results

Kappa values above 0.60 are generally considered acceptable for FOG annotation studies, though thresholds vary by context. For a frame-level metric, values above 0.80 indicate near-perfect agreement. Episode-level F1 captures whether raters agree on when events occur, independent of exact boundary placement.

| Kappa | Interpretation |
|---|---|
| < 0.40 | Poor agreement |
| 0.40 – 0.60 | Moderate |
| 0.60 – 0.80 | Substantial |
| > 0.80 | Almost perfect |

## Lane and label selection

IRR is computed per lane and optionally per label. Use the lane/label selectors in the IRR panel to focus on specific annotation dimensions.

## After computing IRR

- Use [Review Layers](review-layers.md) to inspect disagreements on the timeline
- Resolve disagreements by discussion or adjudication
- Save a [Checkpoint](../annotation/checkpoints.md) once the final annotation is agreed

!!! note
    IRR should be computed on the independent annotation passes — before any review or resolution — to get a valid reliability estimate.
