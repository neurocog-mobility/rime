# Inter-rater reliability

The current reference application provides a [review workspace](review-layers.md),
not a dedicated IRR panel. Review decisions and `.rime` record comparisons are not
reliability scores.

For programmatic analyses, `rime_core.irr` contains interval-agreement helpers.
Define the annotation selector, observation period and temporal resolution for
your analysis, and use the independent inputs before adjudication. Keep that
analysis separate from the final reviewer output.

The [record comparison](../measurement-records/comparison.md) inspects retained
components and result differences. It does not establish clinical equivalence or
replace a study's reliability analysis.
