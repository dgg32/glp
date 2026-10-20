"""Extract the IDMP-O terms our ontology references (MIREOT-style) instead of loading all of IDMP-O.

For every IDMP-O IRI used in ontology/diabetes-market.ttl, copy its type, labels,
definition and named superclasses/superproperties from the public IDMP-O release.
IDMP-O's copyright and MIT license notice are carried over, as the license requires.

Usage: .venv/bin/python scripts/extract_idmp_terms.py [--version 1.4.0]
"""
import argparse
from pathlib import Path

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, OWL, RDF, RDFS, SKOS

ROOT = Path(__file__).resolve().parent.parent
IDMP = "https://spec.pistoiaalliance.org/idmp/ontology/"
PROV = Namespace("http://www.w3.org/ns/prov#")
COPY = [RDF.type, RDFS.label, SKOS.definition, RDFS.subClassOf, RDFS.subPropertyOf]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="1.4.0")
    args = ap.parse_args()

    ours = Graph().parse(ROOT / "ontology" / "diabetes-market.ttl")
    used = sorted({t for triple in ours for t in triple
                   if isinstance(t, URIRef) and str(t).startswith(IDMP)
                   and not str(t).endswith("/")})  # skip module IRIs cited in isDefinedBy

    src_path = (ROOT / "data" / "raw" / "idmp-o" / "IDMP-O" / args.version
                / "IdentificationOfMedicinalProductsOntology.rdf")
    src = Graph().parse(src_path, format="xml")
    src_ont = next(src.subjects(RDF.type, OWL.Ontology))

    out = Graph()
    for prefix, ns in ours.namespaces():
        out.bind(prefix, ns)
    ont = URIRef(f"https://dgg32.github.io/glp/ontology/imports/idmp-o-{args.version}-extract")
    out.add((ont, RDF.type, OWL.Ontology))
    out.add((ont, DCTERMS.title, Literal(f"IDMP-O {args.version} extract (terms used by the Diabetes Drug Market Ontology)", lang="en")))
    out.add((ont, PROV.wasDerivedFrom, src.value(src_ont, OWL.versionIRI) or src_ont))
    for p in (DCTERMS.license, DCTERMS.rights, URIRef("http://www.omg.org/techprocess/ab/SpecificationMetadata/copyright")):
        for v in src.objects(src_ont, p):
            out.add((ont, p, v))

    missing = []
    for term in used:
        if (term, None, None) not in src:
            missing.append(term)
            continue
        for p in COPY:
            if p == RDFS.label and (term, RDFS.label, None) in ours:
                continue  # our MIREOT declaration already labels it; a second, untagged copy would duplicate it
            for o in src.objects(term, p):
                if isinstance(o, URIRef) or isinstance(o, Literal):  # skip anonymous restrictions
                    out.add((term, p, o))
        out.add((term, RDFS.isDefinedBy, src_ont))

    out_path = ROOT / "ontology" / "imports" / f"idmp-o-{args.version}-extract.ttl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.serialize(out_path, format="turtle")
    print(f"{len(used)} IDMP-O terms referenced, {len(used) - len(missing)} extracted, "
          f"{len(out)} triples -> {out_path.relative_to(ROOT)}")
    for m in missing:
        print("  not found in source:", m)


if __name__ == "__main__":
    main()
