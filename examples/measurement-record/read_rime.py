#!/usr/bin/env python3
"""Independent arithmetic check for native RIME JSON-LD (standard library only).

This checks the three calculation inputs using endpoint partitioning, not the
native interval-union implementation. It is not a full RIME or PROV validator.
"""
import json
import math
from pathlib import Path
import sys


def verify_document(path):
    document = json.loads(Path(path).read_text())
    nodes = {n['@id']: n for n in document['@graph']}
    verified = []
    for ref in document['rime:records']:
        result = nodes[ref['@id']]
        activity = nodes[result['prov:wasGeneratedBy']['@id']]
        inputs = {u['prov:hadRole']['@id']: nodes[u['prov:entity']['@id']]['rime:data'] for u in activity['prov:qualifiedUsage']}
        ann, obs, definition = (inputs['rime:'+r] for r in ('annotations', 'observation', 'definition'))
        spans = obs['intervals']
        annotations = [a for a in ann['annotations'] if a['lane'] == definition['lane'] and definition['label'] in (None, a['label'])]
        points = sorted({x for span in spans for x in span} | {a[k] for a in annotations for k in ('start_ms', 'end_ms')})
        covered, eligible = 0, 0
        contributors = set()
        for start, end in zip(points, points[1:]):
            midpoint = (start+end)/2
            if not any(s <= midpoint < e for s, e in spans):
                continue
            eligible += end-start
            matching = [a for a in annotations if a['event_type'] == 'interval' and a['start_ms'] <= midpoint < a['end_ms']]
            if matching:
                covered += end-start
                contributors.update(a['id'] for a in matching)
        if definition['operation'] == 'count':
            contributors.update(a['id'] for a in annotations if a['event_type'] == 'point' and any(s <= a['start_ms'] < e for s, e in spans))
        value = None if not eligible else {'covered_duration': covered/1000, 'percentage_coverage': 100*covered/eligible, 'count': len(contributors)}[definition['operation']]
        actual = result['rime:data']
        if not ((actual['value'] is None if value is None else math.isclose(actual['value'], value, rel_tol=0, abs_tol=1e-9)) and
                actual['contributors'] == sorted(contributors) and math.isclose(actual['eligible_ms'], eligible, rel_tol=0, abs_tol=1e-6) and
                math.isclose(actual['covered_ms'], covered, rel_tol=0, abs_tol=1e-6)):
            raise ValueError('Calculation mismatch: '+ref['@id'])
        verified.append(dict(id=ref['@id'], value=value, unit=actual['unit'], covered_ms=covered, eligible_ms=eligible, contributors=sorted(contributors), verified=True))
    return verified


if __name__ == '__main__':
    print(json.dumps(verify_document(sys.argv[1]), indent=2))
