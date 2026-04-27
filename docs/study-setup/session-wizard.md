# Session Wizard

The Session Wizard creates a new RIME session by linking your raw data files (video, signals) to a session manifest.

## Starting the wizard

**File → New Session** opens the Session Wizard.


## Steps

### 1. Session metadata

- Participant ID
- Session date
- Condition / visit label
- Any custom fields defined by your study protocol

### 2. Video files

- Add one or more video files
- Assign camera labels (e.g. sagittal, frontal, overhead)
- Set the start time offset if video and signals are not time-aligned

### 3. Signal files

- Add CSV or compatible signal files
- See [Signal Configuration](signal-config.md) for channel mapping

### 4. Schema

- Select the protocol schema for this session

### 5. Review & save

- Confirm the session manifest
- Save as `session.json` — this is the file you open in RIME

## Importing from ELAN

If you have existing annotations in ELAN (`.eaf` files), use **File → Import from ELAN** after creating the session.

## The session.json file

The session manifest is a human-readable JSON file that records all data links (video paths, signal files, schema path) and session-level settings. You can move it alongside its linked files and open it directly with `rime --open session.json`.
