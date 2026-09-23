"""Native graph exchange: malformed graphs, arithmetic, immutability and real import."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from rime_core.exchange import DocumentError, RimeDocument, calculate, read_document, write_document

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('graph_examples', ROOT/'examples/measurement-record/create_example.py')
examples = importlib.util.module_from_spec(spec)
spec.loader.exec_module(examples)


def test_synthetic_import_roundtrip_and_independent_calculation(tmp_path):
    doc = examples.imported()
    path = tmp_path/'real.rime'
    write_document(path, doc)
    assert read_document(path).to_dict() == doc.to_dict()
    proc = subprocess.run([sys.executable, '-I', '-S', str(ROOT/'examples/measurement-record/read_rime.py'), str(path)], capture_output=True, text=True, check=True)
    assert [r['value'] for r in json.loads(proc.stdout)] == pytest.approx([10, 6, 1])
    assert '/Users/' not in path.read_text()
    assert len([n for n in doc.nodes.values() if 'rime:AnnotationSet' in n['@type']]) == 1


@pytest.mark.parametrize('review', [False, True])
def test_capture_detaches_mutable_inputs_and_survives_reformatting(tmp_path, review):
    doc = examples.synthetic(review)
    raw = doc.to_dict()
    raw['@graph'].clear()
    assert doc.nodes
    path = tmp_path/'test.rime'
    write_document(path, doc)
    path.write_text(json.dumps(doc.to_dict(), sort_keys=True, indent=4))
    assert read_document(path).to_dict() == doc.to_dict()


@pytest.mark.parametrize('damage', ['cycle', 'missing', 'type', 'value', 'components', 'contributors', 'duplicate', 'unrelated', 'role', 'context', 'decision', 'scope', 'pending', 'version'])
def test_reject_corruption(damage):
    raw = examples.imported().to_dict() if damage == 'scope' else examples.synthetic(True).to_dict()
    graph = raw['@graph']
    result = next(n for n in graph if 'rime:MeasurementResult' in n['@type'])
    calc = next(n for n in graph if 'rime:MeasurementCalculation' in n['@type'])
    if damage == 'cycle':
        production = next(n for n in graph if 'rime:AnnotationProduction' in n['@type'])
        output = next(n for n in graph if n.get('prov:wasGeneratedBy') == {'@id': production['@id']})
        production['prov:used'].append({'@id': output['@id']})
        production['prov:qualifiedUsage'].append({'@type': 'prov:Usage', 'prov:entity': {'@id': output['@id']}, 'prov:hadRole': {'@id': 'rime:input'}})
    elif damage == 'missing':
        calc['prov:used'][0]['@id'] = 'urn:missing'
    elif damage == 'type':
        calc['prov:used'][0]['@id'] = next(n['@id'] for n in graph if 'prov:Agent' in n['@type'])
    elif damage == 'value':
        result['rime:data']['value'] = 99
    elif damage == 'components':
        result['rime:data']['covered_ms'] = 99
    elif damage == 'contributors':
        result['rime:data']['contributors'] = []
    elif damage == 'duplicate':
        graph.append(copy.deepcopy(graph[0]))
    elif damage == 'unrelated':
        graph.append({'@id': 'urn:other', '@type': ['prov:Agent'], 'rime:data': {'name': 'other', 'kind': 'person'}})
    elif damage == 'role':
        calc['prov:qualifiedUsage'][0]['prov:hadRole']['@id'] = 'rime:wrong'
    elif damage == 'context':
        raw['@context'] = 'https://example.org/context'
    elif damage == 'decision':
        next(n for n in graph if 'rime:AnnotationReview' in n['@type'])['rime:data']['decisions'][0]['outputs'] = ['missing']
    elif damage == 'scope':
        next(n for n in graph if 'rime:ObservationPeriod' in n['@type'])['rime:data']['intervals'] = [[0, 10000]]
    elif damage == 'pending':
        next(n for n in graph if n['@id'] == examples.identity('reviewed'))['rime:data']['status'] = 'proposed'
    else:
        raw['rime:version'] = '0.2'
    with pytest.raises(DocumentError):
        RimeDocument.from_dict(raw)


def test_bad_input_does_not_overwrite_and_failed_save_is_atomic(tmp_path, monkeypatch):
    from rime_core import exchange
    path = tmp_path/'saved.rime'
    doc = examples.synthetic()
    write_document(path, doc)
    original = path.read_bytes()
    with pytest.raises(DocumentError):
        write_document(path, [])
    def fail(*args):
        raise OSError('failure')
    monkeypatch.setattr(exchange.os, 'replace', fail)
    with pytest.raises(OSError):
        write_document(path, doc)
    assert path.read_bytes() == original
    assert not list(tmp_path.glob('.rime-export-*'))


def test_parser_limits(tmp_path, monkeypatch):
    from rime_core import exchange
    path = tmp_path/'bad.rime'
    for text in ['{"x":1,"x":2}', '{"x":NaN}', '{"format":"rime-document","version":"0.2"}']:
        path.write_text(text)
        with pytest.raises(DocumentError):
            read_document(path)
    path.write_text('123456')
    monkeypatch.setattr(exchange, 'MAX_DOCUMENT_BYTES', 2)
    with pytest.raises(DocumentError, match='size limit'):
        read_document(path)


def test_coverage_overlap_count_points_and_empty_observation():
    annotations = [examples.annotation('a', 0, 10000), examples.annotation('b', 5000, 15000)]
    for operation, expected, unit in [('covered_duration', 15, 's'), ('percentage_coverage', 75, '%'), ('count', 2, 'count')]:
        definition = dict(operation=operation, version='1', unit=unit, lane='FOG', label='FOG')
        assert calculate(annotations, [[0, 20000]], definition)['value'] == expected
        assert calculate(annotations, [], definition)['value'] is None
        assert calculate([], [[0, 20000]], definition)['value'] == 0
    points = [dict(examples.annotation(str(t), t, t), event_type='point') for t in (0, 10000, 20000)]
    assert calculate(points, [[0, 20000]], definition)['value'] == 2


def test_random_overlap_calculations_match_independent_partition(tmp_path):
    import random
    spec = importlib.util.spec_from_file_location('independent', ROOT/'examples/measurement-record/read_rime.py')
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    rng = random.Random(915)
    for index in range(20):
        raw = examples.synthetic().to_dict()
        annotations = next(n for n in raw['@graph'] if 'rime:AnnotationSet' in n['@type'])['rime:data']
        annotations['annotations'] = [examples.annotation(str(i), *sorted(rng.sample(range(60000), 2))) for i in range(12)]
        definition = next(n for n in raw['@graph'] if 'rime:CalculationDefinition' in n['@type'])['rime:data']
        observation = next(n for n in raw['@graph'] if 'rime:ObservationPeriod' in n['@type'])['rime:data']
        observation['intervals'] = [[0, 22000], [10000, 30000], [40000, 59000]]
        result = next(n for n in raw['@graph'] if 'rime:MeasurementResult' in n['@type'])
        result['rime:data'] = calculate(annotations['annotations'], observation['intervals'], definition)
        path = tmp_path/f'{index}.rime'
        write_document(path, RimeDocument.from_dict(raw))
        assert reader.verify_document(path)[0]['verified']
