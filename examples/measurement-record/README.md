# Synthetic measurement record

`example.rime` imports the supplied synthetic EAF annotations and contains three
measurements: 10% coverage, 6 seconds covered duration, and one FOG interval within
a 60-second observation. It contains no participant data or embedded media.

```sh
.venv/bin/python -m rime_ui --open examples/measurement-record/example.rime
python3 -I -S examples/measurement-record/read_rime.py examples/measurement-record/example.rime
```

`read_rime.py` recalculates results using standard-library endpoint partitioning,
independently of the RIME calculator. Optional RDF interoperability checks:

```sh
uv run --with rdflib python examples/measurement-record/check_prov.py examples/measurement-record/example.rime
```

`create_example.py` provides synthetic import, manual, model, verification,
adjudication and convergence graph constructors used by the software tests.
The [native workflow generator](../workflows/README.md) supplies the compact
editable example set and paired records for manual inspection.
