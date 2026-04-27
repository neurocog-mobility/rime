# Importing from ELAN

If you have existing annotations in ELAN (`.eaf` files), RIME can import them into a new session while mapping ELAN tiers and labels to your RIME schema.

Open the import dialog via **Session → Import from ELAN** (`Ctrl+I`).


## 1. Source files

| Field | Description |
|---|---|
| ELAN file | The `.eaf` file to import |
| Output folder | Where the new RIME session will be created |

## 2. Tier mapping

RIME reads all tiers from the ELAN file and asks you to map each one to a lane in your schema, or skip it.

- Exact name matches are auto-mapped
- Tiers with no match are highlighted — assign them manually or set to **Skip**
- The annotation count for each tier is shown to help you decide

## 3. Label mapping

After tiers are mapped, RIME lists every unique label value and asks you to map each to a valid schema label.

- Auto-suggestion attempts to match by name
- Every label must be resolved — labels cannot be left unmapped (use **Skip** on the tier to exclude it entirely)

## 4. Media files

Add any video and signal files associated with this session — same as in the Session Wizard.

| Type | Formats |
|---|---|
| Video | `.mp4`, `.mov`, `.avi`, `.mkv` |
| Signals | `.csv` |

## 5. Post-import options

**Apply hierarchy rules after import** (on by default) — runs schema validation rules against all imported annotations immediately. Recommended unless you plan to review and clean up annotations manually first.

## 6. Import

Click **Import**. RIME creates `session.json` and `annotations.json` in the output folder and opens the session.

---

!!! note
    ELAN tier and label names are preserved in the import log but do not appear in RIME after mapping. If you need to revisit the original mapping, re-run the import from the same `.eaf` file.
