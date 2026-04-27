# What is CMF?

The **Common Model Format (CMF)** is a packaging standard that lets any detection model be loaded and run inside RIME — without custom integration code.

## The problem CMF solves

Today, each lab's FOG detection model is a standalone script. It reads data in one format, produces output in another, and cannot be connected to an annotation tool without significant engineering work.

```mermaid
flowchart TD
    A[Lab A annotates video] -->|manual scripts| B[Lab A trains FOG detector]
    B -->|standalone model| C[Cannot load into annotation tool]
    C -->|Lab B wants to test it| D[Lab B writes custom integration]
    D --> E[Lab B reformats data]
    E --> F[Lab B interprets output manually]
```

The result: models accumulate in papers but cannot be compared, reused, or evaluated against gold-standard annotations without significant effort.

## The CMF contract

A CMF package declares:

1. **What it needs** — which signal channels, at what sampling rate; or video
2. **What it produces** — probabilities, event intervals, or point events
3. **Where to display output** — which annotation lane and label
4. **How to run inference** — sliding window or whole-signal
5. **What parameters the user can adjust** — thresholds, window sizes

```mermaid
flowchart LR
    subgraph pkg [".rime package"]
        cfg[config.json]
        wrap[wrapper.py]
    end
    RIME -->|reads| cfg
    RIME -->|runs| wrap
    cfg -->|tells RIME| i["Inputs: channels, Hz, shape"]
    cfg -->|tells RIME| o["Outputs: probability / intervals / points"]
    cfg -->|tells RIME| d["Display: lane + label"]
```

## What a .rime package looks like

```
freeze-index.rime/
├── config.json      # the contract
└── wrapper.py       # the model
```

Any model that implements this contract can be loaded by RIME and run on any compatible session — no integration work required.

See [Loading a Model](loading-a-model.md) to get started.
