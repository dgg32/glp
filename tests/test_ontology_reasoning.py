"""Reasoning smoke test: does the ontology infer SGLT2/GLP-1 prescribers on toy data?

Uses the same toy data as the Stardog smoke test (tests/stardog_smoke/toy-data.ttl),
reasoned over locally with OWL 2 RL (owlrl).

Usage: .venv/bin/python tests/test_ontology_reasoning.py
"""
from pathlib import Path

import owlrl
from rdflib import Graph, Namespace, RDF

ROOT = Path(__file__).resolve().parent.parent
DM = Namespace("https://dgg32.github.io/glp/ontology#")
D = Namespace("https://dgg32.github.io/glp/data/")

g = Graph()
g.parse(ROOT / "ontology" / "diabetes-market.ttl")
g.parse(ROOT / "ontology" / "imports" / "idmp-o-1.4.0-extract.ttl")
g.parse(ROOT / "tests" / "stardog_smoke" / "toy-data.ttl")
print("asserted triples:", len(g))
owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(g)

for dr in ("drA", "drB", "drC", "drD"):
    types = sorted(t.split("#")[-1] for t in g.objects(D[dr], RDF.type) if str(t).startswith(str(DM)))
    print(dr, types)
print("drA writes (inferred from prescribedBy):", [p.split("/")[-1] for p in g.objects(D.drA, DM.writes)])
print("Mounjaro substances:", [s.split("/")[-1] for s in g.objects(D.Mounjaro, DM.hasActiveSubstance)])
print("tirzepatide classes:", sorted(c.split("/")[-1] for c in g.objects(D.tirzepatide, DM.inTherapeuticClass)))

types = {dr: set(g.objects(D[dr], RDF.type)) for dr in ("drA", "drB", "drC")}
assert (D.drA, DM.writes, D.rx1) in g, "writes should be inferred from prescribedBy"
assert DM.SGLT2Prescriber in types["drA"], "combination product should make drA an SGLT2 prescriber"
assert DM.GLP1Prescriber in types["drB"], "IDMP-O role chain + SKOS roll-up should make drB a GLP-1 prescriber"
assert not {DM.SGLT2Prescriber, DM.GLP1Prescriber} & types["drC"], "metformin-only drC should be neither"
print("all assertions passed")
