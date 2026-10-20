"""Convert the cleaned tables into RDF, one file (= one named graph) per source, in data/rdf/.

  products.ttl        51 medicinal products: CMS brand + generic names, substances, indications
                      (scripts/drugs.csv and scripts/products.csv, resolved via RxNorm and FDA labels)
  cms-partd-2024.ttl  prescribers (pseudonymized) and their 2024 prescription aggregates
  npi-registry.ttl    prescriber -> NUCC specialty links
  drugsfda.ttl        manufacturers: Drugs@FDA application holders, grouped into companies by their
                      GLEIF ultimate parent (scripts/resolve_organizations.py)
  provenance.ttl      PROV-O description of every loaded graph (scripts/provenance.py): source snapshots
                      with releases, curated inputs, content hashes, generating step
  manifest.csv        file -> named graph IRI, for loading into Stardog (includes ontology and vocab)

Privacy by design: no names and no NPIs are written. Prescribers are identified by
HMAC-SHA256(PSEUDONYM_KEY, NPI)[:16]; the key lives in .env and never leaves this machine.

Usage: .venv/bin/python scripts/build_rdf.py
"""
import csv
import hashlib
import hmac
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from rdflib import Graph, Literal, Namespace, URIRef

import provenance
from rdflib.namespace import DCTERMS, RDF, RDFS, SKOS, XSD

ROOT = Path(__file__).resolve().parent.parent
CLEAN = ROOT / "data" / "clean"
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "rdf"
BASE = "https://dgg32.github.io/glp/"
DM = Namespace(BASE + "ontology#")
D = Namespace(BASE + "data/")
DMSUB = Namespace(BASE + "vocab/substance/")
DMSP = Namespace(BASE + "vocab/specialty/")
DMIND = Namespace(BASE + "vocab/indication/")
GRAPH = Namespace(BASE + "graph/")
PROV = Namespace("http://www.w3.org/ns/prov#")
DATA_YEAR = "2024"
NOW = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

SOURCES = {
    "cms-partd-2024": "https://data.cms.gov/data-api/v1/dataset/d5aa71a8-dcc0-4570-8bcf-bd39deac69fe/data",
    "npi-registry": "https://npiregistry.cms.hhs.gov/api/?version=2.1",
    "drugsfda": "https://api.fda.gov/drug/drugsfda.json",
}


def load_key():
    key = os.environ.get("PSEUDONYM_KEY")
    env = ROOT / ".env"
    if not key and env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("PSEUDONYM_KEY="):
                key = line.split("=", 1)[1].strip()
    if not key:
        sys.exit("PSEUDONYM_KEY is not set (see .env.example)")
    return key.encode()


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def new_graph():
    g = Graph()
    for p, ns in [("dm", DM), ("d", D), ("dmsub", DMSUB), ("dmsp", DMSP), ("dmind", DMIND),
                  ("prov", PROV), ("dcterms", DCTERMS)]:
        g.bind(p, ns)
    return g


def add_number(g, s, p, value, datatype):
    if value not in ("", None):
        g.add((s, p, Literal(value, datatype=datatype)))


def drugsfda_sponsors(fda_brand):
    cache = RAW / "drugsfda" / f"{slug(fda_brand)}.json"
    if not cache.exists():
        query = urllib.parse.urlencode({"search": f'products.brand_name:"{fda_brand}"', "limit": 20})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(f"{SOURCES['drugsfda']}?{query}", timeout=60) as resp:
                    body = json.load(resp)
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 404:  # openFDA answers "no matches" with 404
                    body = {"results": []}
                    break
                time.sleep(5 * (attempt + 1))
            except OSError:  # URLError, timeouts, DNS failures
                time.sleep(5 * (attempt + 1))
        else:
            raise RuntimeError(f"Drugs@FDA lookup failed for {fda_brand!r}")
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(body, indent=1))
    body = json.loads(cache.read_text())
    return sorted({(r["sponsor_name"], r["application_number"]) for r in body.get("results", [])})


def build_products(drugs, products, report):
    g = new_graph()
    claims = read_csv(CLEAN / "partd_claims.csv")
    brand_generic = {r["brnd_name"]: r["gnrc_name"] for r in claims}
    product_info = {p["brnd_name"]: p for p in products}
    missing = set(brand_generic) - set(product_info)
    if missing:
        sys.exit(f"brands missing from scripts/products.csv (rerun resolve_products.py): {sorted(missing)}")
    for brand, generic in sorted(brand_generic.items()):
        node = D["product/" + slug(brand)]
        drug = drugs[generic]
        g.add((node, RDF.type, DM.MedicinalProduct))
        g.add((node, RDFS.label, Literal(brand, lang="en")))
        g.add((node, DM.cmsGenericName, Literal(generic)))
        g.add((node, DM.isCombinationProduct, Literal(drug["is_combination"] == "true")))
        for sub in drug["substances"].split("|"):
            g.add((node, DM.hasActiveSubstance, DMSUB[sub]))
        for ind in product_info[brand]["indications"].split("|"):
            g.add((node, DM.hasIndication, DMIND[ind]))
    report["products"] = len(brand_generic)
    return g


def build_manufacturers(products, sponsors, ja_zh, report):
    """Companies from scripts/organizations.csv (GLEIF ultimate parents of the Drugs@FDA sponsors)."""
    g = new_graph()
    company_of = {r["sponsor_name"]: r["organization"] for r in sponsors}
    by_org = {}
    for r in sponsors:
        by_org.setdefault(r["organization"], []).append(r)
    for org, rows in sorted(by_org.items()):
        node = D["organization/" + org]
        g.add((node, RDF.type, DM.Organization))
        g.add((node, RDFS.label, Literal(rows[0]["legal_name"], lang="en")))
        l = ja_zh[org]  # from scripts/fetch_wikidata_labels.py: Wikidata or curated
        for lang in ("ja", "zh"):
            g.add((node, RDFS.label, Literal(l[f"pref_{lang}"], lang=lang)))
        if l["wikidata"]:
            g.add((node, RDFS.seeAlso, URIRef("http://www.wikidata.org/entity/" + l["wikidata"])))
        if rows[0]["lei"]:
            g.add((node, DCTERMS.identifier, Literal(rows[0]["lei"])))
            g.add((node, RDFS.seeAlso, URIRef("https://search.gleif.org/#/record/" + rows[0]["lei"])))
        for r in rows:  # GLEIF names of the applicant entities and the Drugs@FDA spellings, for search
            if r["applicant_name"] and r["applicant_name"].lower() != r["legal_name"].lower():
                g.add((node, SKOS.altLabel, Literal(r["applicant_name"], lang="en")))
            g.add((node, SKOS.hiddenLabel, Literal(r["sponsor_name"], lang="en")))
    linked = 0
    for p in products:
        if not p["fda_brand"]:
            continue  # multi-source generic: no single manufacturer
        orgs = {company_of[sponsor] for sponsor, _ in drugsfda_sponsors(p["fda_brand"])}
        if not orgs:
            report.setdefault("manufacturer_problems", []).append(f"{p['brnd_name']}: none found")
            continue
        if len(orgs) > 1:  # e.g. Byetta: original Amylin application plus a newer AstraZeneca one
            report.setdefault("several_application_holders", []).append(f"{p['brnd_name']}: {sorted(orgs)}")
        for org in sorted(orgs):
            g.add((D["product/" + slug(p["brnd_name"])], DM.manufacturedBy, D["organization/" + org]))
        linked += 1
    report["products_with_manufacturer"] = linked
    return g


def build_claims(key, report):
    g = new_graph()
    claims = read_csv(CLEAN / "partd_claims.csv")
    pseudonyms = {}

    def hcp(npi):
        if npi not in pseudonyms:
            pseudonyms[npi] = hmac.new(key, npi.encode(), hashlib.sha256).hexdigest()[:16]
        return D["hcp/" + pseudonyms[npi]]

    seen_hcp = set()
    for r in claims:
        doctor = hcp(r["prscrbr_npi"])
        if doctor not in seen_hcp:
            seen_hcp.add(doctor)
            g.add((doctor, RDF.type, DM.HealthcareProfessional))
            g.add((doctor, DM.pseudonymousId, Literal(pseudonyms[r["prscrbr_npi"]])))
            g.add((doctor, DM.cmsPrescriberType, Literal(r["prscrbr_type"])))
            g.add((doctor, DM.city, Literal(r["prscrbr_city"])))
            g.add((doctor, DM.state, Literal(r["prscrbr_state_abrvtn"])))
        rx = D[f"rx/{DATA_YEAR}/{pseudonyms[r['prscrbr_npi']]}/{slug(r['brnd_name'])}"]
        g.add((rx, RDF.type, DM.Prescription))
        g.add((rx, DM.prescribedBy, doctor))  # dm:writes is inferred (ontology 0.2.0)
        g.add((rx, DM.forProduct, D["product/" + slug(r["brnd_name"])]))
        g.add((rx, DM.dataYear, Literal(DATA_YEAR, datatype=XSD.gYear)))
        add_number(g, rx, DM.totalClaims, r["tot_clms"], XSD.integer)
        add_number(g, rx, DM.total30DayFills, r["tot_30day_fills"], XSD.decimal)
        add_number(g, rx, DM.totalDaySupply, r["tot_day_suply"], XSD.integer)
        add_number(g, rx, DM.totalDrugCost, r["tot_drug_cst"], XSD.decimal)
        add_number(g, rx, DM.totalBeneficiaries, r["tot_benes"], XSD.integer)
        g.add((rx, DM.beneficiaryCountSuppressed, Literal(r["tot_benes_suppressed"] == "true")))

    if len(set(pseudonyms.values())) != len(pseudonyms):
        sys.exit("pseudonym collision: use more hex characters")
    report["prescribers"] = len(seen_hcp)
    report["prescriptions"] = len(claims)
    return g, pseudonyms


def build_specialties(pseudonyms, report):
    g = new_graph()
    linked = set()
    for t in read_csv(CLEAN / "npi_taxonomies.csv"):
        if t["npi"] not in pseudonyms:
            continue
        doctor = D["hcp/" + pseudonyms[t["npi"]]]
        g.add((doctor, DM.hasSpecialty, DMSP[t["taxonomy_code"]]))
        if t["is_primary"] == "true":
            g.add((doctor, DM.hasPrimarySpecialty, DMSP[t["taxonomy_code"]]))
        linked.add(t["npi"])
    report["prescribers_with_specialty"] = len(linked)
    return g


def main():
    key = load_key()
    OUT.mkdir(parents=True, exist_ok=True)
    drugs = {r["gnrc_name"]: r for r in read_csv(ROOT / "scripts" / "drugs.csv")}
    products = read_csv(ROOT / "scripts" / "products.csv")
    sponsors = read_csv(ROOT / "scripts" / "organizations.csv")
    org_ja_zh = {r["concept"]: r for r in read_csv(ROOT / "scripts" / "labels_ja_zh.csv") if r["kind"] == "organization"}
    report = {}

    claims_graph, pseudonyms = build_claims(key, report)
    graphs = {
        "products": build_products(drugs, products, report),
        "cms-partd-2024": claims_graph,
        "npi-registry": build_specialties(pseudonyms, report),
        "drugsfda": build_manufacturers(products, sponsors, org_ja_zh, report),
    }
    written = {}
    for name, g in graphs.items():
        path = OUT / f"{name}.ttl"
        g.serialize(path, format="turtle")
        written[name] = (path, len(g))
    # Loading manifest: data graphs plus ontology (schema graph, for reasoning) and vocabularies.
    manifest = [("ontology/diabetes-market.ttl", "tag:stardog:api:context:schema"),
                ("ontology/imports/idmp-o-1.4.0-extract.ttl", "tag:stardog:api:context:schema")]
    for v in ("therapeutic-class", "substance", "indication", "nucc-specialty"):
        manifest.append((f"vocab/{v}.ttl", str(GRAPH[f"vocab/{v}"])))
    for name, (path, _) in written.items():
        manifest.append((str(path.relative_to(ROOT)), str(GRAPH[name])))
    manifest.append(("shapes/diabetes-market-shapes.ttl", str(GRAPH["shapes"])))  # SHACL contract
    provenance.build(manifest, NOW).serialize(OUT / "provenance.ttl", format="turtle")  # describes all of the above
    manifest.append(("data/rdf/provenance.ttl", str(GRAPH["provenance"])))
    with open(OUT / "manifest.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["file", "graph"])
        w.writerows(manifest)

    total = 0
    for file, _ in manifest:
        n = len(Graph().parse(ROOT / file))
        total += n
        print(f"{n:>8,}  {file}")
    print(f"{total:>8,}  total triples to load")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
