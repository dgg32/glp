"""Write Stardog Mapping Syntax 2 (SMS2) from an R2RML mapping.

Stardog Studio reads a virtual graph's mapping as SMS2 and ignores mappings.syntax=R2RML, so the standard
R2RML file (checked against Snowflake by check_mapping.py) stays the source and the SMS2 file is generated
from it. Covers the R2RML this project uses: rr:sqlQuery, a template subject with rr:class, and predicate-object
maps whose object is a constant IRI, a template IRI, or a column with an optional rr:language or rr:datatype.

Usage: python scripts/r2rml_to_sms2.py mapping/glp.r2rml.ttl > mapping/glp.sms
"""
import re
import sys
from pathlib import Path

from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import RDF

RR = Namespace("http://www.w3.org/ns/r2rml#")


def var(name):
    return "?" + name


def template(t):
    return f'template("{t}")'


def mapping(g, tm, prefixes):
    def short(iri):
        for p, ns in prefixes:
            if str(iri).startswith(str(ns)) and p:
                return f"{p}:{str(iri)[len(str(ns)):]}"
        return f"<{iri}>"

    sql = " ".join(str(g.value(g.value(tm, RR.logicalTable), RR.sqlQuery)).split())
    subject_map = g.value(tm, RR.subjectMap)
    to, binds = [], [f"BIND({template(g.value(subject_map, RR.template))} AS ?subject)"]
    for c in sorted(g.objects(subject_map, RR["class"])):
        to.append(f"?subject a {short(c)} .")
    for i, pom in enumerate(sorted(g.objects(tm, RR.predicateObjectMap)), 1):
        predicates = sorted(g.objects(pom, RR.predicate))
        if (constant := g.value(pom, RR.object)) is not None:
            obj = short(constant)
        else:
            om = g.value(pom, RR.objectMap)
            obj = f"?o{i}"
            if (t := g.value(om, RR.template)) is not None:
                binds.append(f"BIND({template(t)} AS {obj})")
            elif (lang := g.value(om, RR.language)) is not None:
                binds.append(f'BIND(strlang({var(g.value(om, RR.column))}, "{lang}") AS {obj})')
            elif (dt := g.value(om, RR.datatype)) is not None:
                binds.append(f"BIND(strdt({var(g.value(om, RR.column))}, {short(dt)}) AS {obj})")
            else:
                obj = var(g.value(om, RR.column))
        to += [f"?subject {short(p)} {obj} ." for p in predicates]
    lines = [f"MAPPING <{tm}>", "FROM SQL {", f"  {sql}", "}", "TO {"]
    lines += [f"  {t}" for t in to] + ["}", "WHERE {"] + [f"  {b}" for b in binds] + ["}"]
    return "\n".join(lines)


def main(path):
    g = Graph().parse(path)
    # the prefixes the file declares (rdflib adds its own defaults), except R2RML's and the triples maps' names
    declared = re.findall(r"^@prefix\s+([\w-]+):\s*<([^>]+)>", Path(path).read_text(), re.M)
    prefixes = [(p, URIRef(ns)) for p, ns in declared if p not in {"rr", "map"}]
    out = [f"# Generated from {Path(path).name} by scripts/r2rml_to_sms2.py; edit the R2RML file, not this one.", ""]
    out += [f"PREFIX {p}: <{ns}>" for p, ns in sorted(prefixes)] + [""]
    out.append("\n\n;\n\n".join(mapping(g, tm, prefixes) for tm in sorted(g.subjects(RDF.type, RR.TriplesMap))))
    print("\n".join(out))


if __name__ == "__main__":
    main(sys.argv[1])
