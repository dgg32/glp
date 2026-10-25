"""Build the Japan (NDB Open Data) vocabularies and graphs; called by build_rdf.py, which loads them.

  vocab/jp-prefecture.ttl   the 47 prefectures (JIS X 0401 codes), labels from Wikidata (by ISO 3166-2 code)
  vocab/ndb-dimensions.ttl  sex-age bands (sex + 5-year band, broader: sex) and care settings (院外/院内/入院)
  vocab/jp-drug-class.ttl   the Japanese therapeutic categories (薬効分類) of the products, with SKOS mapping
                            links to the ATC-based therapeutic class scheme, computed from the products
  data/rdf/ndb-products.ttl 510 strength-level products (receipt code, YJ code, NHI price, generic and
                            originator flags, substances, indications) and their marketing authorization holders
  data/rdf/ndb-2024.ttl     the dispensed quantities as an RDF Data Cube: one dm:QuantitySlice per product x
                            care setting x dimension, one observation per cell (quantity, or masked)

Inputs: data/clean/ndb_*.csv (clean_ndb.py), scripts/substances.csv and therapeutic_classes.csv (resolve_*.py),
curated vocab/src/ndb_ingredients.csv, ndb_product_indications.csv and jp_manufacturers.csv.

Crosswalk rule (jp-drug-class.ttl). For an ATC-based class C and a Japanese category J, over the products
that contain a substance of C (or of a narrower class):
  all of them in J   -> J skos:narrowMatch C, for the broadest such C only (not also for its narrower classes)
  some of them in J  -> J skos:relatedMatch C, for the most specific such C only (no narrower class is split)
  and for 396, which is in scope completely: J skos:broadMatch C for the narrowest C holding all J products.
Category 249 is in scope only for its diabetes drugs, so no claim about all of 249 is made.

Usage: run build_rdf.py (this module has no main of its own).
"""
import csv
import hashlib
import json
import time
import unicodedata
import urllib.parse
import urllib.request
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, RDF, RDFS, SKOS, XSD

from build_skos import mirror_pref_labels, scheme_header, split

ROOT = Path(__file__).resolve().parent.parent
CLEAN = ROOT / "data" / "clean"
SRC = ROOT / "vocab" / "src"
RAW = ROOT / "data" / "raw"
BASE = "https://dgg32.github.io/glp/"
DM = Namespace(BASE + "ontology#")
D = Namespace(BASE + "data/")
DMSUB = Namespace(BASE + "vocab/substance/")
DMTC = Namespace(BASE + "vocab/therapeutic-class/")
DMIND = Namespace(BASE + "vocab/indication/")
PREF = Namespace(BASE + "vocab/prefecture/")
SEXAGE = Namespace(BASE + "vocab/sex-age/")
SETTING = Namespace(BASE + "vocab/care-setting/")
JPC = Namespace(BASE + "vocab/jp-drug-class/")
QB = Namespace("http://purl.org/linked-data/cube#")
SDMXA = Namespace("http://purl.org/linked-data/sdmx/2009/attribute#")
SDMXC = Namespace("http://purl.org/linked-data/sdmx/2009/code#")
WD = Namespace("http://www.wikidata.org/entity/")
RELEASE = "11"  # NDB Open Data release (FY2024 claims)
DATASET = D[f"ndb/{RELEASE}"]
NDB_PAGE = "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000177221_00017.html"
WIKIDATA = "https://query.wikidata.org/sparql"
USER_AGENT = "glp-diabetes-graph/0.1 (https://github.com/dgg32; label lookup by identifier)"

# Japan Standard Commodity Classification, the levels above the two categories in scope.
# en/zh are curated translations (pending native-speaker review); ja 249/396 come from the NDB files.
JP_CLASSES = [  # code, broader, ja, en, zh
    ("2", "", "個々の器官系用医薬品", "Drugs for individual organ systems", "各器官系统用药"),
    ("24", "2", "ホルモン剤（抗ホルモン剤を含む。）", "Hormone preparations (including antihormones)", "激素类药物（含抗激素药）"),
    ("249", "24", None, "Other hormone preparations (including antihormones)", "其他激素类药物（含抗激素药）"),
    ("3", "", "代謝性医薬品", "Metabolic drugs", "代谢类药物"),
    ("39", "3", "その他の代謝性医薬品", "Other metabolic drugs", "其他代谢类药物"),
    ("396", "39", None, "Antidiabetic agents", "糖尿病用药"),
]
CARE_SETTINGS = [  # id, broader, en, ja, zh, definition
    ("outpatient", "", "outpatient", "外来", "门诊", "Outpatient care, both dispensing routes."),
    ("outpatient-external", "outpatient", "outpatient, community pharmacy", "外来（院外）", "门诊（院外处方）",
     "Outpatient prescription filled at a community pharmacy (院外処方, the usual case in Japan)."),
    ("outpatient-internal", "outpatient", "outpatient, dispensed in-house", "外来（院内）", "门诊（院内处方）",
     "Outpatient prescription dispensed by the clinic or hospital itself (院内処方)."),
    ("inpatient", "", "inpatient", "入院", "住院", "Drugs used during a hospital stay."),
]
DIMENSION_PROPERTY = {"prefecture": DM.prefecture, "month": DM.month, "sex-age": DM.sexAgeGroup}


def read(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def new_graph():
    g = Graph()
    for p, ns in [("dm", DM), ("d", D), ("dmsub", DMSUB), ("dmtc", DMTC), ("dmind", DMIND), ("pref", PREF),
                  ("sexage", SEXAGE), ("setting", SETTING), ("jpc", JPC), ("qb", QB), ("sdmx-attribute", SDMXA),
                  ("sdmx-code", SDMXC), ("skos", SKOS), ("dcterms", DCTERMS), ("wd", WD)]:
        g.bind(p, ns)
    return g


def concept(g, node, scheme, cls, en, ja, zh, broader=None, notation=None):
    for t in (SKOS.Concept, cls):
        g.add((node, RDF.type, t))
    g.add((node, SKOS.inScheme, scheme))
    for lang, label in (("en", en), ("ja", ja), ("zh", zh)):
        g.add((node, SKOS.prefLabel, Literal(label, lang=lang)))
    if broader is not None:
        g.add((node, SKOS.broader, broader))
        g.add((broader, SKOS.narrower, node))
    else:
        g.add((node, SKOS.topConceptOf, scheme))
        g.add((scheme, SKOS.hasTopConcept, node))
    if notation:
        g.add((node, SKOS.notation, Literal(notation)))


# ---------------------------------------------------------------- vocabularies

def wikidata_prefectures():
    """ISO 3166-2 code (JP-01 ..) -> {item, en, ja, zh} from Wikidata, found by identifier (P300)."""
    values = " ".join(f'"JP-{i:02d}"' for i in range(1, 48))
    query = f"""SELECT ?iso ?item ?lang ?label WHERE {{
  VALUES ?iso {{ {values} }}
  ?item wdt:P300 ?iso .
  ?item rdfs:label ?label . BIND(lang(?label) AS ?lang) FILTER(?lang IN ("en", "ja", "zh-hans", "zh-cn"))
}}"""
    cache = RAW / "wikidata" / f"P300_{hashlib.sha256(query.encode()).hexdigest()[:16]}.json"
    if not cache.exists():
        req = urllib.request.Request(WIKIDATA + "?" + urllib.parse.urlencode({"query": query, "format": "json"}),
                                     headers={"User-Agent": USER_AGENT})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    body = json.load(resp)
                break
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(10 * (attempt + 1))
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(body, ensure_ascii=False, indent=1))
    out = {}
    for b in json.loads(cache.read_text())["results"]["bindings"]:
        p = out.setdefault(b["iso"]["value"], {"items": set()})
        p["items"].add(b["item"]["value"].rsplit("/", 1)[1])
        lang = {"zh-hans": "zh", "zh-cn": "zh"}.get(b["lang"]["value"], b["lang"]["value"])
        if lang not in p or b["lang"]["value"] == "zh-hans":
            p[lang] = b["label"]["value"]
    return out


def build_prefectures(report):
    g = new_graph()
    scheme = URIRef(BASE + "vocab/prefecture")
    scheme_header(g, scheme, {"en": "Prefectures of Japan", "ja": "都道府県", "zh": "日本都道府县"},
                  "The 47 prefectures with their JIS X 0401 codes, as NDB Open Data reports them. Labels from Wikidata "
                  "(CC0), found by ISO 3166-2 code.", ["https://www.wikidata.org/wiki/Property:P300"])
    wd = wikidata_prefectures()
    for i in range(1, 48):
        code, iso = f"{i:02d}", f"JP-{i:02d}"
        p = wd.get(iso)
        if not p or len(p["items"]) != 1 or not all(p.get(l) for l in ("en", "ja", "zh")):
            raise SystemExit(f"Wikidata: no unique item with en/ja/zh labels for {iso}: {p}")
        node = PREF[code]
        en = p["en"].removesuffix(" Prefecture")
        concept(g, node, scheme, DM.Prefecture, en, p["ja"], p["zh"], notation=code)
        g.add((node, DCTERMS.identifier, Literal(iso)))
        g.add((node, SKOS.exactMatch, WD[next(iter(p["items"]))]))
        short = p["ja"] if p["ja"] == "北海道" else p["ja"].rstrip("都道府県")  # 東京都 -> 東京, as people say it
        if short != p["ja"]:
            g.add((node, SKOS.altLabel, Literal(short, lang="ja")))
        if en != p["en"]:
            g.add((node, SKOS.altLabel, Literal(p["en"], lang="en")))
    report["prefectures"] = 47
    return mirror_pref_labels(g)


def build_dimensions(report):
    g = new_graph()
    scheme = URIRef(BASE + "vocab/sex-age")
    scheme_header(g, scheme, {"en": "Sex and age bands (NDB Open Data)", "ja": "性・年齢階級（NDBオープンデータ）",
                              "zh": "性别与年龄组（NDB开放数据）"},
                  "Sex combined with the 21 five-year age bands of NDB Open Data (0-4 ... 95-99, 100+). Each band has "
                  "its sex as broader concept, so queries can roll up by sex.", [NDB_PAGE])
    sexes = {"M": ("male", "男性", "男性"), "F": ("female", "女性", "女性")}
    for sex, (en, ja, zh) in sexes.items():
        concept(g, SEXAGE[sex], scheme, DM.SexAgeGroup, en, ja, zh)
        for lo in range(0, 101, 5):
            node = SEXAGE[f"{sex}{lo}"]
            band = (f"{lo}-{lo + 4} years", f"{lo}～{lo + 4}歳", f"{lo}-{lo + 4}岁") if lo < 100 else \
                   ("100 years and over", "100歳以上", "100岁及以上")
            concept(g, node, scheme, DM.SexAgeGroup, f"{en}, {band[0]}", f"{ja} {band[1]}", f"{zh} {band[2]}",
                    broader=SEXAGE[sex], notation=f"{sex}{lo}")
            g.add((node, DM.minAge, Literal(lo, datatype=XSD.integer)))
    scheme = URIRef(BASE + "vocab/care-setting")
    scheme_header(g, scheme, {"en": "Care settings (NDB Open Data)", "ja": "診療区分（NDBオープンデータ）",
                              "zh": "诊疗类别（NDB开放数据）"},
                  "Where a drug was prescribed and dispensed, as NDB Open Data splits its tables.", [NDB_PAGE])
    for cid, broader, en, ja, zh, definition in CARE_SETTINGS:
        concept(g, SETTING[cid], scheme, DM.CareSetting, en, ja, zh, broader=SETTING[broader] if broader else None)
        g.add((SETTING[cid], SKOS.definition, Literal(definition, lang="en")))
    report["sex_age_concepts"] = 2 + 2 * 21
    return mirror_pref_labels(g)


def class_tree():
    """ATC-based class id -> set of itself and its broader classes."""
    broader = {c["id"]: c["broader"] for c in read(ROOT / "scripts" / "therapeutic_classes.csv")}
    out = {}
    for cid in broader:
        chain, c = set(), cid
        while c:
            chain.add(c)
            c = broader[c]
        out[cid] = chain
    return out, broader


def build_jp_classes(products, substances_of, class_of, report):
    g = new_graph()
    scheme = URIRef(BASE + "vocab/jp-drug-class")
    scheme_header(g, scheme, {"en": "Japanese therapeutic categories (薬効分類)", "ja": "薬効分類", "zh": "日本药效分类"},
                  "The therapeutic categories of the Japan Standard Commodity Classification that the diabetes drugs in "
                  "NDB Open Data are filed under, with SKOS mapping links to the ATC-based therapeutic class scheme. "
                  "The mappings are computed from the products (scripts/build_ndb.py), not asserted by hand.",
                  [NDB_PAGE, "https://www.soumu.go.jp/toukei_toukatsu/index/seido/syouhin/2index.htm"])
    names = {p["ndb_class"]: p["ndb_class_name"] for p in products}
    for code, broader, ja, en, zh in JP_CLASSES:
        concept(g, JPC[code], scheme, DM.JapaneseDrugClass, en, ja or names[code], zh,
                broader=JPC[broader] if broader else None, notation=code)
        if ja or code == "249":
            g.add((JPC[code], SKOS.editorialNote, Literal(
                "English and Chinese labels curated, pending native-speaker review." if not ja else
                "Japanese label from the Japan Standard Commodity Classification; English and Chinese curated, "
                "pending native-speaker review.", lang="en")))
    g.add((JPC["249"], SKOS.scopeNote, Literal(
        "Only its diabetes drugs are in this graph: insulins (YJ 2492) and the GLP-1 / GIP-GLP-1 receptor agonists "
        "(YJ 2499), which ATC files under A10 but Japan under other hormone preparations.", lang="en")))

    tree, broader_of = class_tree()
    members = defaultdict(set)  # ATC-based class -> receipt codes of products containing one of its substances
    for p in products:
        for s in substances_of[p["receipt_code"]]:
            for c in tree[class_of[s]]:
                members[c].add(p["receipt_code"])
    jp_of = {p["receipt_code"]: p["ndb_class"] for p in products}
    by_jp = defaultdict(set)
    for code, jp in jp_of.items():
        by_jp[jp].add(code)
    children = defaultdict(set)
    for c, b in broader_of.items():
        if b:
            children[b].add(c)
    mappings = []
    for jp, jp_products in sorted(by_jp.items()):
        def full(c):
            return bool(members[c]) and members[c] <= jp_products
        def split_(c):
            return bool(members[c] & jp_products) and not full(c)
        for c in sorted(members):
            if full(c) and not (broader_of[c] and full(broader_of[c])):
                mappings.append((jp, "narrowMatch", c))
            elif split_(c) and not any(split_(k) for k in children[c]):
                mappings.append((jp, "relatedMatch", c))
        if jp == "396":  # in scope completely: the narrowest ATC-based class that holds all of 396
            holding = [c for c in members if jp_products <= members[c]]
            mappings.append((jp, "broadMatch", min(holding, key=lambda c: len(members[c]))))
    for jp, rel, c in mappings:
        g.add((JPC[jp], SKOS[rel], DMTC[c]))
        n, total = len(members[c] & by_jp[jp]), len(members[c])
        g.add((JPC[jp], SKOS.editorialNote, Literal(
            f"{rel} {c}: {n} of the {total} products containing a substance of {c} are filed under {jp}"
            + (f"; {len(by_jp[jp])} products in {jp} in all." if rel == "broadMatch" else "."), lang="en")))
    report["crosswalk"] = [f"{jp} {rel} {c} ({len(members[c] & by_jp[jp])}/{len(members[c])})" for jp, rel, c in mappings]
    return mirror_pref_labels(g)


# ---------------------------------------------------------------- data

def build_products(products, substances_of, indications_of, report):
    g = new_graph()
    makers = {m["manufacturer_ja"]: m for m in read(SRC / "jp_manufacturers.csv")}
    used = set()
    for p in products:
        node = D["product/jp/" + p["receipt_code"]]
        g.add((node, RDF.type, DM.MedicinalProduct))
        name = p["name_ja"]
        g.add((node, RDFS.label, Literal(name, lang="ja")))
        if (nfkc := unicodedata.normalize("NFKC", name)) != name:  # ジャディアンス錠１０ｍｇ -> ジャディアンス錠10mg
            g.add((node, SKOS.hiddenLabel, Literal(nfkc, lang="ja")))
        g.add((node, DM.receiptCode, Literal(p["receipt_code"])))
        g.add((node, DM.yjCode, Literal(p["yj_code"])))
        g.add((node, DM.nhiPrice, Literal(Decimal(p["nhi_price"]), datatype=XSD.decimal)))
        g.add((node, DM.dispensingUnit, Literal(p["unit_ja"])))
        g.add((node, DM.isGeneric, Literal(p["ndb_generic"] == "1")))
        g.add((node, DM.isOriginator, Literal(p["originator"] == "true")))
        g.add((node, DM.routeOfAdministration, Literal(p["route"])))
        g.add((node, DM.inJapaneseDrugClass, JPC[p["ndb_class"]]))
        subs = substances_of[p["receipt_code"]]
        g.add((node, DM.isCombinationProduct, Literal(len(subs) > 1)))
        for s in subs:
            g.add((node, DM.hasActiveSubstance, DMSUB[s]))
        for i in indications_of[p["receipt_code"]]:
            g.add((node, DM.hasIndication, DMIND[i]))
        if p["manufacturer_ja"]:  # empty for unified-name listings (統一名収載), which have no single holder
            m = makers[p["manufacturer_ja"]]
            g.add((node, DM.manufacturedBy, D["organization/jp/" + m["id"]]))
            used.add(p["manufacturer_ja"])
    for name in sorted(used):
        m = makers[name]
        org = D["organization/jp/" + m["id"]]
        g.add((org, RDF.type, DM.Organization))
        g.add((org, RDFS.label, Literal(name.replace("　", " "), lang="ja")))
        g.add((org, RDFS.label, Literal(m["label_en"], lang="en")))
        g.add((org, SKOS.hiddenLabel, Literal(name, lang="ja")))  # as spelled in the price list
        if m["group_organization"]:
            g.add((org, DM.partOfCorporateGroup, D["organization/" + m["group_organization"]]))
    report["jp_products"] = len(products)
    report["jp_organizations"] = len(used)
    report["jp_products_without_manufacturer"] = sum(not p["manufacturer_ja"] for p in products)
    return g


def build_quantities(report):
    g = new_graph()
    g.add((DATASET, RDF.type, QB.DataSet))
    g.add((DATASET, RDFS.label, Literal(f"NDB Open Data, release {RELEASE}: prescription drug quantities, FY2024 "
                                        "(April 2024 - March 2025), diabetes drugs", lang="en")))
    g.add((DATASET, RDFS.label, Literal(f"第{RELEASE}回NDBオープンデータ 処方薬（糖尿病治療薬）", lang="ja")))
    g.add((DATASET, DCTERMS.source, URIRef(NDB_PAGE)))
    g.add((DATASET, DCTERMS.license, Literal("NDB Open Data, Ministry of Health, Labour and Welfare (MHLW). Free to use "
                                             "with the source cited (NDB Open Data FAQ).", lang="en")))
    keys = {}
    for dim, prop in DIMENSION_PROPERTY.items():
        key = D[f"ndb/key/{dim}"]
        keys[dim] = key
        g.add((key, RDF.type, QB.SliceKey))
        g.add((key, RDFS.label, Literal(f"breakdown by {dim}", lang="en")))
        g.add((key, QB.componentProperty, prop))
    for s in read(CLEAN / "ndb_slices.csv"):
        code, setting, dim = s["receipt_code"], s["setting"], s["dimension"]
        node = D[f"ndb/{RELEASE}/slice/{code}/{setting}/{dim}"]
        g.add((DATASET, QB.slice, node))
        g.add((node, RDF.type, DM.QuantitySlice))
        g.add((node, DM.aboutProduct, D["product/jp/" + code]))
        g.add((node, DM.careSetting, SETTING[setting]))
        g.add((node, QB.sliceStructure, keys[dim]))
        if s["total_masked"] == "true":
            g.add((node, SDMXA.confStatus, SDMXC["confStatus-C"]))
        else:
            g.add((node, DM.totalQuantity, Literal(Decimal(s["total"]), datatype=XSD.decimal)))
    value = {"prefecture": lambda k: PREF[k], "month": lambda k: Literal(k, datatype=XSD.gYearMonth),
             "sex-age": lambda k: SEXAGE[k]}
    n = 0
    for c in read(CLEAN / "ndb_cells.csv"):
        code, _, setting, dim = c["slice"].split("/")
        slice_node = D[f"ndb/{RELEASE}/slice/{code}/{setting}/{dim}"]
        obs = D[f"ndb/{RELEASE}/obs/{code}/{setting}/{c['key']}"]
        g.add((slice_node, QB.observation, obs))
        g.add((obs, DIMENSION_PROPERTY[dim], value[dim](c["key"])))
        if c["masked"] == "true":
            g.add((obs, SDMXA.confStatus, SDMXC["confStatus-C"]))
        else:
            g.add((obs, DM.quantity, Literal(Decimal(c["quantity"]), datatype=XSD.decimal)))
        n += 1
    report["ndb_observations"] = n
    return g


def build(report):
    """{graph name: (path relative to ROOT, Graph)} in loading order."""
    products = read(CLEAN / "ndb_products.csv")
    ingredients = {r["yj7"]: r for r in read(SRC / "ndb_ingredients.csv")}
    overrides = read(SRC / "ndb_product_indications.csv")
    class_of = {s["substance"]: s["therapeutic_class"] for s in read(ROOT / "scripts" / "substances.csv")}
    substances_of, indications_of = {}, {}
    for p in products:
        y = ingredients.get(p["yj_code"][:7])
        if y is None:
            raise SystemExit(f"YJ ingredient {p['yj_code'][:7]} ({p['name_ja']}) missing from vocab/src/ndb_ingredients.csv")
        if p["ingredient_ja"] and p["ingredient_ja"] != y["ingredient_ja"]:
            raise SystemExit(f"{p['name_ja']}: 成分名 {p['ingredient_ja']!r} != curated {y['ingredient_ja']!r}")
        substances_of[p["receipt_code"]] = split(y["substances"])
        indications_of[p["receipt_code"]] = split(next((o["indications"] for o in overrides
                                                        if p["name_ja"].startswith(o["name_prefix"])), y["indications"]))
    return {
        "vocab/jp-prefecture": ("vocab/jp-prefecture.ttl", build_prefectures(report)),
        "vocab/ndb-dimensions": ("vocab/ndb-dimensions.ttl", build_dimensions(report)),
        "vocab/jp-drug-class": ("vocab/jp-drug-class.ttl",
                                build_jp_classes(products, substances_of, class_of, report)),
        "ndb-products": ("data/rdf/ndb-products.ttl", build_products(products, substances_of, indications_of, report)),
        "ndb-2024": ("data/rdf/ndb-2024.ttl", build_quantities(report)),
    }
