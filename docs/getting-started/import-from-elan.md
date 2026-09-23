# Importing from ELAN

Import `.eaf` annotations while creating a new workspace:

1. Choose **New workspace**, enter a name/folder and select the destination protocol.
2. On the recordings step, add the required primary video and any additional sources.
3. Choose **Import EAF…** and select the file.
4. Map ELAN tiers to protocol lanes, skipping tiers you do not need. Resolve label mappings when prompted.
5. Continue to alignment or begin annotation.

RIME retains the imported intervals, protocol and import provenance in the native
workspace. It does not apply automatic rules during EAF import or require an old
session format. **Remove import** clears the pending selection before creation;
changing the protocol also clears it so mappings cannot silently target a different
schema.

Recordings remain external. Check temporal alignment and record synchronization
notes, including any preprocessing, before interpreting imported annotations.
