"""Scientific-role projection of the exhaustive comparison, in Figure 1 direction."""
from collections import deque
from html import escape

from .record_comparison import _links, record_nodes


def project_comparison(diff, document_a, document_b):
    native = {s: record_nodes(d, diff['record_'+s])[1]
              for s, d in [('a', document_a), ('b', document_b)]}
    components = {c['component']: c for c in diff['components']}
    index = {s: {c['id_'+s]: k for k, c in components.items() if 'id_'+s in c}
             for s in native}
    core, edges, ports = {}, [], []
    for side, nodes in native.items():
        pending = [diff['record_'+side]]
        seen = set()
        while pending:
            identity = pending.pop()
            if identity in seen:
                continue
            seen.add(identity)
            key = index[side][identity]
            node = nodes[identity]
            core.setdefault(key, {'component': key, 'comparison': components[key], 'nodes': {}})['nodes'][side] = node
            ancillary = []
            for relation, role, target, attrs in _links(node):
                main = relation == 'prov:wasGeneratedBy' or (
                    relation == 'prov:used' and role in ('rime:annotations', 'rime:annotation_input'))
                if main:
                    pending.append(target)
                    edges.append(dict(side=side, source=key, target=index[side][target],
                                      relation=relation, role=role))
                else:
                    ancillary.append(dict(relation=relation, role=role, target=target, attributes=attrs))
            if ancillary:
                closure, todo = set(), [x['target'] for x in ancillary]
                while todo:
                    target = todo.pop()
                    if target not in closure:
                        closure.add(target)
                        todo.extend(t for _, _, t, _ in _links(nodes[target]))
                keys = sorted({index[side][x] for x in closure})
                states = {components[k]['status'] for k in keys}
                own_relations = components[key].get('relationships', [])
                if any(r['status'] in ('different', 'only_a', 'only_b') for r in own_relations
                       if r['target_component'] in keys):
                    states.add('different')
                status = ('different' if states & {'different', 'only_a', 'only_b'}
                          else 'unavailable' if 'unavailable' in states else 'equal')
                ports.append(dict(owner=key, side=side, components=keys, status=status,
                                  edges=ancillary, retained_nodes={x: nodes[x] for x in sorted(closure)}))
    # Topological rows align comparison counterparts, not JSON array positions.
    successors = {k: set() for k in core}
    indegree = {k: 0 for k in core}
    for edge in edges:
        if edge['target'] not in successors[edge['source']]:
            successors[edge['source']].add(edge['target'])
            indegree[edge['target']] += 1
    ready = deque(sorted(k for k in core if indegree[k] == 0))
    order = []
    while ready:
        key = ready.popleft()
        order.append(key)
        for target in sorted(successors[key]):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    if len(order) != len(core):
        raise ValueError('Ambiguous aligned topology; use the exhaustive comparison view.')
    return dict(projection_version='1.0', rows=[core[k] for k in order], edges=edges,
                supporting_groups=ports, numerical_comparison=diff['numerical_comparison'],
                alignment_issues=diff['alignment_issues'])


def row_label(row, side):
    node = row['nodes'].get(side)
    if node is None:
        return ['Not present']
    kind = next(t[5:] for t in node['@type'] if t.startswith('rime:'))
    titles = {'MeasurementResult': 'Measurement result', 'MeasurementCalculation': 'Measurement calculation',
              'AnnotationSet': 'Annotation set', 'AnnotationProduction': 'Annotation production',
              'AnnotationReview': 'Annotation review'}
    lines = [titles[kind]]
    data = node['rime:data']
    if kind == 'MeasurementResult':
        lines.append('Undefined' if data['value'] is None else f'{data["value"]:.6g}{data["unit"]}')
    elif kind == 'AnnotationSet':
        n = len(data['annotations'])
        lines.append(f'{n} annotation'+('' if n == 1 else 's'))
    elif kind in ('AnnotationProduction', 'AnnotationReview'):
        attrs = [a for a in row['comparison'].get('attributes', [])
                 if a['status'] in ('different', 'only_a', 'only_b') and side in a
                 and not isinstance(a[side], (list, dict))]
        # CMF settings are the primary scientific display; other differences remain
        # accessible in the complete comparison, not discarded from the data model.
        if 'execution_specification' in data:
            attrs = [a for a in attrs if a['path'].startswith('/rime:data/execution_specification/inference/')]
        for a in attrs[:4]:
            name = a['path'].split('/')[-1]
            value = a[side]
            if name.endswith('_ms') and isinstance(value, (int, float)):
                lines.append(f'{name[:-3].replace("_", " ")}: {value/1000:g} s')
            else:
                lines.append(f'{name.replace("_", " ")}: {str(value)[:45]}')
        if len(attrs) > 4:
            lines.append('Further differences in details')
    return lines


def support_label(group):
    lines, other_roles = [], set()
    for edge in group['edges']:
        node = group['retained_nodes'][edge['target']]
        data, role = node['rime:data'], edge['role']
        if role == 'rime:observation':
            spans = data['intervals']
            text = (f'{spans[0][0]/1000:g}–{spans[0][1]/1000:g} s'
                    if len(spans) == 1 else f'{len(spans)} intervals')
            lines.append('Observation period: '+text)
        elif role == 'rime:definition':
            lines.append('Definition: '+data['operation'].replace('_', ' '))
        elif edge['relation'] == 'prov:wasAssociatedWith':
            other_roles.add('agent')
        else:
            other_roles.add(role.removeprefix('rime:').replace('_', ' '))
    if other_roles:
        lines.append(' · '.join(sorted(other_roles)))
    return lines


def clinical_mermaid(view, label_a='Record A', label_b='Record B'):
    def q(value):
        return escape(str(value), quote=True)

    lines = ['flowchart TB', '  %% Vertical provenance; dotted cross-links compare retained contents.']
    ids = {(r['component'], s): f'{s}{i}' for i, r in enumerate(view['rows']) for s in ('a', 'b')}
    for side, title in [('a', label_a), ('b', label_b)]:
        lines += [f'  subgraph {side}["{side.upper()} · {q(title)}"]', '    direction TB']
        for row in view['rows']:
            nid = ids[(row['component'], side)]
            lines.append(f'    {nid}["'+ '<br/>'.join(q(x) for x in row_label(row, side))+'"]')
        lines.append('  end')
    for edge in view['edges']:
        label = 'was generated by' if edge['relation'] == 'prov:wasGeneratedBy' else 'used'
        lines.append(f'  {ids[(edge["source"], edge["side"])]} -->|"{label}"| {ids[(edge["target"], edge["side"])]}')
    for row in view['rows']:
        status = row['comparison']['status']
        label = {'equal': '= contents', 'different': '≠ contents', 'unavailable': '? provenance unavailable',
                 'only_a': 'A only', 'only_b': 'B only'}[status]
        lines.append(f'  {ids[(row["component"], "a")]} -.-|"{label}"| {ids[(row["component"], "b")]}')
    for i, row in enumerate(view['rows']):
        groups = {g['side']: g for g in view['supporting_groups'] if g['owner'] == row['component']}
        if not groups:
            continue
        shared = (set(groups) == {'a', 'b'} and groups['a']['components'] == groups['b']['components']
                  and all(g['status'] != 'different' for g in groups.values())
                  and support_label(groups['a']) == support_label(groups['b']))
        for sides in [('a', 'b')] if shared else [(s,) for s in groups]:
            g = groups[sides[0]]
            nid = f'support{i}'+''.join(sides)
            title = 'Supporting inputs — shared' if shared else 'Supporting inputs — '+g['status']
            text = [title, *support_label(g)]
            if g['status'] == 'unavailable':
                text.append('Some historical provenance unavailable')
            lines.append(f'  {nid}["'+'<br/>'.join(q(x) for x in text)+'"]')
            for s in sides:
                lines.append(f'  {ids[(row["component"], s)]} -->|"inputs / responsibility"| {nid}')
            lines.append(f'  class {nid} support;')
    num = view['numerical_comparison']
    text = (f'Absolute measurement difference: {num["absolute_difference"]:.6g} '
            + ('percentage points' if num['unit_a'] == '%' else num['unit_a'])
            if num['status'] == 'applicable' else 'Numerical comparison not applicable')
    lines += [f'  summary["{q(text)}"]',
              '  classDef entity fill:#DBE8F4,stroke:#87949E,color:#111;',
              '  classDef activity fill:#F2D3CF,stroke:#87949E,color:#111;',
              '  classDef support fill:#F4F4F4,stroke:#999,color:#111;',
              '  classDef changed stroke:#B24A35,stroke-width:3px;',
              '  classDef unknown stroke-dasharray:5 3;']
    for row in view['rows']:
        for side in row['nodes']:
            nid = ids[(row['component'], side)]
            style = 'activity' if 'prov:Activity' in row['nodes'][side]['@type'] else 'entity'
            lines.append(f'  class {nid} {style};')
            if row['comparison']['status'] == 'different':
                lines.append(f'  class {nid} changed;')
            elif row['comparison']['status'] == 'unavailable':
                lines.append(f'  class {nid} unknown;')
    return '\n'.join(lines)+'\n'
