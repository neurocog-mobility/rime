# Loading a Model

## Requirements

- A `.rime` model package (see [What is CMF?](what-is-cmf.md))
- The session must have the signal channels the model requires

## Load a model

**Models → Load Model** (or the model loader button in the toolbar)


1. Browse to the `.rime` package folder or zip file
2. RIME reads the model's `config.json` and validates that the required signals are present in the session
3. The model appears in the **Model Runner** panel

## Run inference

In the **Model Runner** panel:

- Click **Run** to run the model on the current session
- Inference progress is shown in the panel
- Output is overlaid on the timeline in the configured lane


## Adjust model parameters

Click **Settings** in the Model Runner panel to adjust:

- Detection threshold
- Window size / stride
- Any model-specific parameters declared in `config.json`


## Included models

The RIME repository includes several example `.rime` packages in `models/`:

| Package | Description |
|---|---|
| `freeze-index.rime` | Freeze Index from accelerometer signal |
| `step-detector.rime` | Step detection from foot accelerometer |
| `walking-classifier.rime` | Walking vs. non-walking classifier |
| `movement-video.rime` | Movement detection from video |
