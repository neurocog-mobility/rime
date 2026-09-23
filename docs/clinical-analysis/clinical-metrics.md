# Save and compare measurements

The **Measurements** section shows protocol-defined results. Click a value to inspect
its calculation and contributors. Duration and percentage display two decimals;
count is an integer.

1. **Configure…** selects measures and the observation period: **Protocol period**, **Time range**, or **From annotations**.
2. **Save records…** writes the selected measures to one `.rime` document, with a separate result root per measure. Later workspace edits do not alter that file.
3. Open the document through **File → Open…** or `rime --open measurements.rime`.
4. Select a measurement, inspect nodes using **Details**, or **Verify calculation** without recordings.
5. Use **Open…** inside the inspector to add a second document. Select a measurement from each; **Expand all** and **Fit** frame the comparison.

For GP-FOG, Tasks annotations define the default observation period. Empty eligible
time is undefined. Zero events within nonempty time gives zero, not proof of complete
review or clinical absence. Pending suggestions and unresolved review inputs do not
contribute. Save the workspace separately to resume editing.

See [comparison semantics](../measurement-records/comparison.md) or try a
[comparison example](../examples.md).
