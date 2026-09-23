# Review demonstration

Open from the repository root:

```sh
.venv/bin/python -m rime_ui --open examples/workflows/review-demo/review.json
```

This is an illustrative adjudication of **synthetic annotations and recordings**,
not a clinical reference or a record of real researchers' decisions. It reuses
`../generated/evidence/` (no additional media copies).

- **Decision 1:** union of A's 2–4 s and B's 2.2–4.5 s intervals, with a saved note.
- **Decision 2:** custom output 7.2–9.1 s, with an illustrative discussion note.
- **Unresolved inputs:** A's 13–16 s and B's 14–16 s intervals.
- Initial saved output: **4.40 s**, **22.00%**, **2 intervals** over 20 s.
  Unresolved inputs do not contribute to these results.

Select a saved decision to inspect its inputs, output and note; use **Edit** to
change it. Use **New decision**, check the two unresolved inputs, choose an
operation, and save. Try **New annotation** for an interval absent from both inputs.
Use File → Save review to persist changes, reopen it, and use **Save records…**
to inspect exported measurement derivations. `input-a.json` and `input-b.json`
are also available for creating a fresh review through the setup dialog.

To generate a fresh copy without overwriting manual work:

```sh
.venv/bin/python examples/workflows/create_review_example.py /tmp/rime-review-demo
```

Source paths are relative to each workspace JSON. Keep this folder beside
`generated/` when moving it; no path editing is required.
