"""Independent RDF/PROV structure check. Run with: uv run --with rdflib ..."""
import json
from pathlib import Path
import sys
from rdflib import Dataset, Namespace, RDF, URIRef

PROV = Namespace('http://www.w3.org/ns/prov#')
RIME = Namespace('urn:rime:vocab:')

for filename in sys.argv[1:]:
    raw = json.loads(Path(filename).read_text())
    dataset = Dataset()
    dataset.parse(data=json.dumps(raw), format='json-ld')
    graph = dataset.graph(URIRef(raw['@id']))
    expected = {'prov:Entity': PROV.Entity, 'prov:Activity': PROV.Activity, 'prov:Agent': PROV.Agent}
    for base, rdf_type in expected.items():
        assert set(graph.subjects(RDF.type, rdf_type)) == {URIRef(n['@id']) for n in raw['@graph'] if base in n['@type']}
    for node in raw['@graph']:
        subject = URIRef(node['@id'])
        for key, predicate in [('prov:used', PROV.used), ('prov:wasAssociatedWith', PROV.wasAssociatedWith), ('prov:wasGeneratedBy', PROV.wasGeneratedBy)]:
            refs = node.get(key, [])
            if isinstance(refs, dict):
                refs = [refs]
            assert set(graph.objects(subject, predicate)) == {URIRef(r['@id']) for r in refs}
        assert json.loads(str(graph.value(subject, RIME.data))) == node['rime:data']
        for usage in graph.objects(subject, PROV.qualifiedUsage):
            assert (usage, RDF.type, PROV.Usage) in graph
            assert graph.value(usage, PROV.entity) in set(graph.objects(subject, PROV.used))
            assert graph.value(usage, PROV.hadRole) is not None
    # A standard serializer/parser round trip preserves all triples.
    from rdflib import Graph
    from rdflib.compare import isomorphic
    assert isomorphic(graph, Graph().parse(data=graph.serialize(format='turtle'), format='turtle'))
    print(f'{Path(filename).name}: {len(graph)} RDF triples; PROV nodes, edges, roles, attributes and Turtle round trip verified')
