# Importing from ELAN

Import `.eaf` annotations while creating a new workspace:

1. Choose **New workspace**, enter a name/folder and select the destination protocol.
2. On the recordings step, add the required primary video and any additional sources.
3. Choose **Import EAF…** and select the file.
4. Map ELAN tiers to protocol lanes, skipping tiers you do not need. Optionally enable **Generate protocol-based suggestions for imported annotations**. Resolve label mappings when prompted.
5. Continue to alignment or begin annotation.

RIME retains the imported intervals, protocol and import provenance in the native
workspace. Protocol-based suggestions are off by default. When enabled, they appear
as pending suggestions for acceptance, modification or rejection; imported annotations
remain unchanged. The selection is saved with the import provenance.
**Remove import** clears the pending selection before creation;
changing the protocol also clears it so mappings cannot silently target a different
schema.

Recordings remain external. Check temporal alignment and record synchronization
notes, including any preprocessing, before interpreting imported annotations.
