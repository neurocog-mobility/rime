"""Native RIME 1.1 profile: PROV-O in self-contained JSON-LD.

No legacy snapshot conversion, remote contexts, media loading or code execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import tempfile
from functools import lru_cache
from jsonschema import Draft202012Validator
from uuid import uuid4

FORMAT = 'rime-document'
VERSION = '1.1'
PROV = 'http://www.w3.org/ns/prov#'
# Project-controlled vocabulary identifier; does not imply a hosted ontology.
RIME = 'urn:rime:vocab:'
CONTEXT = {'prov': PROV, 'rime': RIME, 'rime:data': {'@type': '@json'}}
MAX_OBJECTS = 4096
MAX_DOCUMENT_BYTES = 64 * 1024 * 1024
ENTITY_TYPES = {'Source', 'AnnotationSet', 'ObservationPeriod', 'CalculationDefinition', 'MeasurementResult'}
ACTIVITY_TYPES = {'AnnotationProduction', 'AnnotationReview', 'MeasurementCalculation'}
UNITS = {'covered_duration': 's', 'percentage_coverage': '%', 'count': 'count'}


class DocumentError(ValueError):
    """The document violates the bounded RIME exchange profile."""


def require(condition, message):
    if not condition:
        raise DocumentError(message)


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')


def _unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f'Duplicate JSON key: {key}')
        result[key] = value
    return result


def _invalid(value):
    raise DocumentError(f'Non-finite JSON number: {value}')


def _parse(raw):
    return json.loads(raw, object_pairs_hook=_unique, parse_constant=_invalid)


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _spans(value):
    require(isinstance(value, list), 'Intervals must be an array.')
    for span in value:
        require(isinstance(span, list) and len(span) == 2 and all(_number(x) for x in span)
                and span[0] < span[1], 'Expected finite half-open intervals with start < end.')
    return value


def _union(spans):
    merged = []
    for start, end in sorted(_spans(spans)):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(end, merged[-1][1])
        else:
            merged.append([start, end])
    return merged


def calculate(annotations, observation, definition):
    """Pure interval calculation; milliseconds, union coverage, literal entry count."""
    operation = definition['operation']
    require(operation in UNITS and definition['version'] == '1', 'Unsupported calculation/version.')
    require(definition['unit'] == UNITS[operation], 'Incorrect definition unit.')
    eligible = _union(observation)
    pieces, contributors = [], []
    for annotation in annotations:
        if annotation['lane'] != definition['lane'] or definition['label'] not in (None, annotation['label']):
            continue
        start, end = annotation['start_ms'], annotation['end_ms']
        if annotation['event_type'] == 'point':
            require(operation == 'count', 'Point annotations require count.')
            if any(s <= start < e for s, e in eligible):
                contributors.append(annotation['id'])
        else:
            clipped = [[max(start, s), min(end, e)] for s, e in eligible if max(start, s) < min(end, e)]
            if clipped:
                contributors.append(annotation['id'])
                pieces.extend(clipped)
    covered = _union(pieces)
    numerator = math.fsum(e-s for s, e in covered)
    denominator = math.fsum(e-s for s, e in eligible)
    value = None if denominator == 0 else {'covered_duration': numerator/1000,
        'percentage_coverage': 100*numerator/denominator, 'count': len(contributors)}[operation]
    return {'value': value, 'unit': UNITS[operation], 'covered_ms': numerator,
            'eligible_ms': denominator, 'contributors': sorted(contributors),
            'reason': 'empty_observation' if denominator == 0 else None}


def entity(identity, kind, data, generated_by=None):
    node = {'@id': identity, '@type': ['prov:Entity', 'rime:'+kind], 'rime:data': data}
    if generated_by:
        node['prov:wasGeneratedBy'] = {'@id': generated_by}
    return node


def activity(identity, kind, inputs, data, agents=()):
    """inputs: (role, entity ID, optional mapping attributes) tuples.

    Qualified Usage describes an edge, not an additional scientific stage.
    """
    inputs = list(inputs)
    uses = []
    for role, target, *attributes in inputs:
        use = {'@type': 'prov:Usage', 'prov:entity': {'@id': target},
               'prov:hadRole': {'@id': 'rime:'+role}}
        if attributes:
            use['rime:data'] = attributes[0]
        uses.append(use)
    return {'@id': identity, '@type': ['prov:Activity', 'rime:'+kind], 'rime:data': data,
            'prov:used': [{'@id': target} for target in dict.fromkeys(u[1] for u in inputs)],
            'prov:qualifiedUsage': uses, 'prov:wasAssociatedWith': [{'@id': a} for a in agents]}


def agent(identity, name, kind='person'):
    require(kind in ('person', 'group', 'model'), 'Unknown agent kind.')
    return {'@id': identity, '@type': ['prov:Agent'], 'rime:data': {'name': name, 'kind': kind}}


@lru_cache(maxsize=1)
def _schema():
    return Draft202012Validator(json.loads((Path(__file__).parent / 'config/schemas/rime-1.1.schema.json').read_text()))


def _validate(payload):
    error = next(_schema().iter_errors(payload), None)
    if error is not None:
        raise DocumentError(f'Invalid RIME structure at {error.json_path}: {error.message}')
    require(set(payload) == {'@context', '@id', '@type', 'rime:version', 'rime:createdAt', 'rime:records', '@graph'},
            'Expected a native RIME JSON-LD document; snapshot formats are unsupported.')
    require(payload['@context'] == CONTEXT, 'Unsupported context. Remote contexts are not loaded.')
    require(payload['@type'] == 'rime:Document' and payload['rime:version'] == VERSION, 'Unsupported format/version.')
    require(isinstance(payload['@id'], str) and payload['@id'].startswith('urn:uuid:'), 'Invalid document identity.')
    require(datetime.fromisoformat(payload['rime:createdAt']).tzinfo is not None, 'Timezone required.')
    graph = payload['@graph']
    require(isinstance(graph, list) and 0 < len(graph) <= MAX_OBJECTS, 'Invalid object count.')
    nodes, groups, edges = {}, {}, {}
    for node in graph:
        identity, types, data = node['@id'], node['@type'], node['rime:data']
        require(isinstance(identity, str) and identity.startswith('urn:') and len(identity) > 4,
                'Node identities must be absolute URNs.')
        require(identity not in nodes and identity != payload['@id'], 'Duplicate identity.')
        require(isinstance(types, list) and len(set(types)) == len(types), 'Invalid node types.')
        require(isinstance(data, dict), 'Expected object attributes.')
        base = [t for t in types if t in ('prov:Entity', 'prov:Activity', 'prov:Agent')]
        require(len(base) == 1, 'Each node needs exactly one fundamental type.')
        base = base[0]
        domain = [t.removeprefix('rime:') for t in types if t.startswith('rime:')]
        if base == 'prov:Agent':
            require(types == ['prov:Agent'] and set(node) == {'@id', '@type', 'rime:data'}, 'Invalid agent.')
            require(data.get('kind') in ('person', 'group', 'model') and bool(data.get('name')), 'Invalid agent attributes.')
        else:
            require(len(types) == 2 and len(domain) == 1 and domain[0] in
                    (ENTITY_TYPES if base == 'prov:Entity' else ACTIVITY_TYPES), 'Unknown clinical type.')
            allowed = {'@id', '@type', 'rime:data'} | ({'prov:wasGeneratedBy'} if base == 'prov:Entity' else
                {'prov:used', 'prov:qualifiedUsage', 'prov:wasAssociatedWith'})
            require(set(node) <= allowed, 'Unexpected node fields.')
        nodes[identity], groups[identity], edges[identity] = node, base, []

    def ref(owner, value, expected):
        require(isinstance(value, dict) and set(value) == {'@id'}, 'Invalid reference.')
        target = value['@id']
        require(target in nodes and groups[target] == expected, 'Missing or wrong-type reference.')
        edges[owner].append(target)
        return target

    def kind(node):
        return next(t[5:] for t in node['@type'] if t.startswith('rime:'))

    uses = {}
    for identity, node in nodes.items():
        data, group = node['rime:data'], groups[identity]
        if group == 'prov:Entity':
            if 'prov:wasGeneratedBy' in node:
                generator = ref(identity, node['prov:wasGeneratedBy'], 'prov:Activity')
                expected_roles = {'AnnotationSet': {'AnnotationProduction', 'AnnotationReview'},
                                  'MeasurementResult': {'MeasurementCalculation'}}
                require(kind(node) in expected_roles and kind(nodes[generator]) in expected_roles[kind(node)], 'Invalid generator for entity kind.')
            elif kind(node) == 'AnnotationSet':
                require(data.get('history') == 'unknown', 'Annotation origin must be recorded or explicitly unknown.')
            if kind(node) in ('AnnotationSet', 'ObservationPeriod'):
                require(isinstance(data.get('timeline'), str) and data['timeline'], 'Explicit timeline required.')
            if kind(node) == 'AnnotationSet':
                require(data.get('status') in ('retained', 'proposed'), 'Annotation state required.')
                require(data.get('review_status') in ('unknown', 'incomplete', 'complete', 'unreviewed'), 'Review status required.')
                seen = set()
                for a in data['annotations']:
                    require(isinstance(a['id'], str) and a['id'] not in seen, 'Duplicate annotation identity.')
                    seen.add(a['id'])
                    require(isinstance(a['lane'], str) and isinstance(a['label'], str), 'Invalid selector.')
                    require(_number(a['start_ms']) and _number(a['end_ms']), 'Invalid annotation time.')
                    require(a['event_type'] in ('point', 'interval') and
                            (a['start_ms'] == a['end_ms'] if a['event_type'] == 'point' else a['start_ms'] < a['end_ms']),
                            'Invalid annotation bounds/type.')
            elif kind(node) == 'ObservationPeriod':
                _spans(data['intervals'])
            elif kind(node) == 'Source':
                name = data['file_name']
                require(isinstance(name, str) and name and '/' not in name and '\\' not in name,
                        'Source descriptions use filenames, not local paths.')
                digest = data.get('sha256')
                require(digest is None or (isinstance(digest, str) and len(digest) == 64 and
                        all(c in '0123456789abcdef' for c in digest)), 'Invalid source digest.')
        elif group == 'prov:Activity':
            targets = [ref(identity, r, 'prov:Entity') for r in node['prov:used']]
            require(len(targets) == len(set(targets)), 'Duplicate used edge.')
            for r in node['prov:wasAssociatedWith']:
                ref(identity, r, 'prov:Agent')
            qualified = []
            for use in node['prov:qualifiedUsage']:
                require(set(use) <= {'@type', 'prov:entity', 'prov:hadRole', 'rime:data'} and
                        use['@type'] == 'prov:Usage', 'Invalid usage qualification.')
                target = use['prov:entity']['@id']
                require(set(use['prov:entity']) == {'@id'} and target in targets, 'Qualified usage lacks matching used edge.')
                role = use['prov:hadRole']['@id']
                require(set(use['prov:hadRole']) == {'@id'} and role.startswith('rime:'), 'Invalid input role.')
                qualified.append((role[5:], target))
                mapping = use.get('rime:data', {}).get('mapping')
                if mapping is not None:
                    require(mapping.get('status') in ('known', 'unknown'), 'Invalid mapping status.')
                    if mapping['status'] == 'known':
                        require(_number(mapping.get('offset_ms')) and mapping.get('method') in
                                ('manual_offset', 'import'), 'Invalid constant mapping.')
            require({t for _, t in qualified} == set(targets) and len(qualified) == len(set(qualified)), 'Invalid input qualifications.')
            uses[identity] = qualified
            if kind(node) == 'AnnotationProduction':
                require(bool(data.get('method')) and bool(targets), 'Production requires method and sources/inputs.')

    from .record_contract import validate_connections
    validate_connections(nodes, uses, require)

    # Iterative traversal avoids recursion limits on valid shared graphs.
    roots = payload['rime:records']
    require(isinstance(roots, list) and bool(roots), 'At least one record required.')
    root_ids = [r['@id'] for r in roots]
    require(len(root_ids) == len(set(root_ids)), 'Duplicate record root.')
    colors = {}
    for root in roots:
        root_id = root['@id']
        require(set(root) == {'@id'} and root_id in nodes and 'rime:MeasurementResult' in nodes[root_id]['@type'], 'Invalid result root.')
        stack = [(root_id, False)]
        while stack:
            current, leaving = stack.pop()
            if leaving:
                colors[current] = 2
            elif colors.get(current) == 1:
                raise DocumentError('Cycle in derivation.')
            elif colors.get(current) != 2:
                colors[current] = 1
                stack.append((current, True))
                stack.extend((target, False) for target in edges[current])
    require(set(colors) == set(nodes), 'Document contains unrelated nodes.')
    for identity, node in nodes.items():
        if 'rime:MeasurementResult' in node['@type']:
            require(identity in root_ids, 'Every measurement result must be a record root.')
            calc = nodes[node['prov:wasGeneratedBy']['@id']]
            require('rime:MeasurementCalculation' in calc['@type'], 'Result requires a measurement calculation.')
            inputs = uses[calc['@id']]
            require(all(sum(r == role for r, _ in inputs) == 1 for role in ('annotations', 'definition', 'observation')) and
                    all(r in ('annotations', 'definition', 'observation', 'scope_annotations') for r, _ in inputs) and
                    sum(r == 'scope_annotations' for r, _ in inputs) <= 1, 'Calculation requires three named inputs and optional scope annotations.')
            selected = {r: nodes[t] for r, t in inputs}
            for role, expected in [('annotations', 'AnnotationSet'), ('observation', 'ObservationPeriod'), ('definition', 'CalculationDefinition')]:
                require('rime:'+expected in selected[role]['@type'], 'Wrong calculation input kind.')
            ann, obs, definition = (selected[r]['rime:data'] for r in ('annotations', 'observation', 'definition'))
            require(ann['timeline'] == obs['timeline'] and ann['status'] == 'retained', 'Timeline mismatch or pending measurement basis.')
            require('scope_annotations' not in selected or 'selection' in obs, 'Scope input requires observation selection.')
            if 'selection' in obs:
                selection = obs['selection']
                scope = selected.get('scope_annotations', selected['annotations'])
                require('rime:AnnotationSet' in scope['@type'] and scope['rime:data']['timeline'] == obs['timeline'], 'Invalid scope annotation set.')
                require(selection['annotation_set'] == scope['@id'], 'Scope must reference a declared input set.')
                require(selection.get('rule') == 'selected_annotations', 'Unsupported scope selection rule.')
                chosen = [a for a in scope['rime:data']['annotations'] if a['id'] in selection['annotation_ids']]
                require(len(chosen) == len(set(selection['annotation_ids'])) == len(selection['annotation_ids']), 'Invalid scope selection.')
                require(all(a['event_type'] == 'interval' for a in chosen), 'Scope requires intervals.')
                require(_union([[a['start_ms'], a['end_ms']] for a in chosen]) == _union(obs['intervals']), 'Scope intervals disagree with selection.')
            expected = calculate(ann['annotations'], obs['intervals'], definition)
            actual = node['rime:data']
            require(set(actual) == set(expected), 'Unexpected or missing result fields.')
            for field, value in expected.items():
                require((_number(actual[field]) and math.isclose(actual[field], value, rel_tol=1e-12, abs_tol=1e-9))
                        if _number(value) else actual[field] == value, 'Result disagrees with calculation: '+field)
        elif 'rime:AnnotationReview' in node['@type']:
            input_sets = {t: nodes[t]['rime:data']['annotations'] for _, t in uses[identity]
                          if 'rime:AnnotationSet' in nodes[t]['@type']}
            outputs = [n for n in graph if n.get('prov:wasGeneratedBy') == {'@id': identity}]
            require(all(nodes[t]['rime:data']['timeline'] == outputs[0]['rime:data']['timeline'] for t in input_sets) if outputs else False, 'Review timeline mismatch.')
            require(bool(input_sets) and len(outputs) == 1 and 'rime:AnnotationSet' in outputs[0]['@type'], 'Review requires input sets and one output set.')
            require(outputs[0]['rime:data']['status'] == 'retained', 'Review output must be retained.')
            decisions = node['rime:data']['decisions']
            require(not any(d['action'] == 'unresolved' for d in decisions) or outputs[0]['rime:data']['review_status'] != 'complete', 'Unresolved review cannot be complete.')
            output_ids = []
            for decision in decisions:
                require(bool(_spans(decision['extent'])), 'Review decision requires extent.')
                require(decision['action'] in ('accept', 'modify', 'reject', 'reject_remaining', 'union', 'intersection', 'mean', 'custom', 'no_event', 'unresolved'), 'Unknown review decision.')
                for r in decision['inputs']:
                    require(r['entity'] in input_sets and r['annotation'] in {a['id'] for a in input_sets[r['entity']]}, 'Invalid decision input.')
                if decision['action'] in ('reject', 'reject_remaining', 'no_event', 'unresolved'):
                    require(not decision['outputs'], 'Non-retention decision has outputs.')
                output_ids.extend(decision['outputs'])
            require(len(output_ids) == len(set(output_ids)) and set(output_ids) ==
                    {a['id'] for a in outputs[0]['rime:data']['annotations']}, 'Decision/output mismatch.')


@dataclass(frozen=True)
class RimeDocument:
    """Validated immutable capture; accessors return detached data, never mutable state."""
    _json: str

    def __post_init__(self):
        try:
            payload = _parse(self._json)
            require(len(self._json.encode('utf-8')) <= MAX_DOCUMENT_BYTES, 'Document exceeds size limit.')
            _validate(payload)
        except (KeyError, TypeError, ValueError, OverflowError, RecursionError) as exc:
            raise DocumentError(str(exc)) from exc

    @classmethod
    def create(cls, nodes, records):
        return cls.from_dict({'@context': CONTEXT, '@id': 'urn:uuid:'+str(uuid4()), '@type': 'rime:Document',
            'rime:version': VERSION, 'rime:createdAt': datetime.now(timezone.utc).isoformat(),
            'rime:records': [{'@id': r} for r in records], '@graph': list(nodes)})

    @classmethod
    def from_dict(cls, payload):
        return cls(json_bytes(payload).decode('utf-8'))

    def to_dict(self):
        return _parse(self._json)

    @property
    def records(self):
        return tuple(r['@id'] for r in self.to_dict()['rime:records'])

    @property
    def nodes(self):
        return {n['@id']: n for n in self.to_dict()['@graph']}


def write_document(path, document):
    """Validate and atomically save a native graph. Old captures are not accepted."""
    require(isinstance(document, RimeDocument), 'Export requires a native RimeDocument graph.')
    path = Path(path).expanduser().resolve()
    require(path.suffix.lower() == '.rime', 'Use the .rime extension.')
    data = json_bytes(document.to_dict())
    fd, temporary = tempfile.mkstemp(prefix='.rime-export-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return document


def read_document(path):
    try:
        with Path(path).open('rb') as handle:
            raw = handle.read(MAX_DOCUMENT_BYTES + 1)
        require(len(raw) <= MAX_DOCUMENT_BYTES, 'Document exceeds size limit.')
        return RimeDocument(raw.decode('utf-8'))
    except (OSError, ValueError) as exc:
        raise DocumentError(f'Cannot open RIME document: {exc}') from exc
