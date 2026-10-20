# The project in plain language

*Written 2026-10-14, after the data download step.*

## The big picture

You applied for a job at Boehringer Ingelheim, a German drug company. The job needs some skills you haven't shown publicly yet. So the project is a practice exercise: take free public data about **diabetes medicines and the doctors who prescribe them**, organize it with the tools that job uses, and write it up as a Medium article and a GitHub repo.

Think of it as building a small, well-labelled library about diabetes drugs to show employers you can do it.

## The data we downloaded

**1. Prescription data (from Medicare)**
Medicare is the US government health insurance for people over 65. Each year it publishes a huge table that says, roughly:

> "Dr. Smith in Hartford wrote 26 prescriptions for the drug Jardiance in 2024, and it cost $2,600 in total."

We only took **Connecticut** and only **type 2 diabetes drugs**. That's 22,034 rows. Each row is one doctor plus one drug, with totals for the year:
- how many prescriptions (claims)
- how many days of medicine
- the total cost
- how many patients

Sometimes a number is blank on purpose. If only 1 to 10 patients are involved, the government hides the number so nobody can work out who the patients are.

**2. Doctor details (from the NPI Registry)**
Every US doctor, nurse practitioner and so on has a 10-digit ID number called an **NPI**, a bit like a national ID for healthcare workers. We looked up all 3,896 prescribers to get their **specialty**: family doctor, heart doctor, diabetes specialist, and so on. 13 doctors couldn't be found, probably because they retired or their ID was closed.

**3. The specialty list (NUCC)**
This is the official US list of all 883 healthcare specialties, each with a code. For example, `207R00000X` means "Internal Medicine". It's a dictionary that turns the codes into names.

## The drugs, simply

All of these lower blood sugar, but in different ways. Doctors group them into families ("classes"):

| Family | Example brand | How to think of it |
|---|---|---|
| Metformin | Metformin | The cheap, standard first pill |
| SGLT2 inhibitors | **Jardiance** (Boehringer's) | Make you pass sugar out in urine |
| GLP-1 drugs | Ozempic, Mounjaro | The famous injections, which also cause weight loss |
| DPP-4 inhibitors | **Tradjenta** (Boehringer's) | Gentle pills that help insulin work |
| Sulfonylureas | Glipizide | Old, cheap pills that push out more insulin |
| Insulin glargine | Lantus | Long-acting insulin injection |
| Combinations | Synjardy | Two drugs in one pill |

Wegovy is the same medicine as Ozempic but is approved for weight loss, not diabetes. That's why its rows are marked separately.

## What the job words mean

All of these are ways of organizing data so that both computers and people understand it the same way.

- **Knowledge graph:** data stored as connected facts instead of a table, like "Dr. Smith → prescribes → Jardiance → belongs to → SGLT2 family." You already know this idea from Neo4j.
- **RDF:** a standard format for writing those facts. Every fact is a small sentence of three parts (subject, verb, object). Neo4j is one way to build a graph; RDF is the way the pharma industry tends to use.
- **Stardog:** a database that stores RDF, the way Neo4j stores your current graphs.
- **SPARQL:** the query language for RDF. It's the equivalent of Cypher in Neo4j.
- **OWL (the "ontology"):** the **rules of the world**. It defines what kinds of things exist and how they relate, such as "a Drug contains a Substance" or "a Doctor writes a Prescription." It can also derive new facts: if a doctor prescribes Jardiance, the computer can conclude "this is an SGLT2 prescriber" without being told.
- **SKOS:** a format for **vocabularies and family trees of terms**, such as Diabetes drugs → SGLT2 inhibitors → Jardiance. It also stores names in several languages (English, Japanese, Chinese), so searching for "SGLT2阻害薬" finds the same thing.
- **SHACL:** **quality-control rules** for the data, for example "an NPI must have exactly 10 digits" or "a prescription count can't be negative." The computer checks every record and lists those that break a rule. That's why the cleaning step kept the imperfect rows: later, SHACL will catch them, and that makes a good demo for the article.
- **IDMP-O:** an existing, industry-agreed ontology for medicines, made by a pharma group (Pistoia Alliance). Instead of inventing your own definitions, you connect yours to theirs, which is what a real company would expect.
- **Provenance / governance:** keeping track of **where each fact came from and when** ("this number came from Medicare's 2024 file, downloaded on 14 October"). It's needed so people can trust the data.

## Roadmap

1. ✅ **Collect the raw data**
2. ✅ **Tidy it into clean tables**
3. ⏭️ **Design the "rules of the world" (OWL)**
4. Turn the tables into RDF facts and load them into Stardog.
5. Add the drug family tree with Japanese and Chinese names (SKOS).
6. Add quality-control checks (SHACL) and show what they catch.
7. Ask business questions, such as "Do heart doctors prefer Jardiance or Ozempic?"
8. Optional: a chatbot that answers those questions in plain English or Japanese.
9. Write the article.

## One thing to remember

The data contains **real doctors' names**. Keeping it on your computer is fine, but anything published must hide the names and IDs. The project's `.gitignore` keeps `data/raw/` and `data/clean/` out of GitHub.
