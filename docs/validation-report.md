# SHACL validation report

*Generated 2026-10-25 by `scripts/validate.py` against Stardog database `glp` with [shapes/diabetes-market-shapes.ttl](../shapes/diabetes-market-shapes.ttl). Full report: `data/validation/report-2026-10-25.ttl`.*

**0 violations, 17 warnings, 130 info.**

| Severity | Count | Rule | Examples (focus node → value) |
|---|---:|---|---|
| Warning | 13 | No NUCC specialty (prescriber not found in the NPI Registry). | `data/hcp/763c20292647bf9c`; `data/hcp/1a9d4a3afcc42a91`; `data/hcp/38e456acca1f250e` |
| Warning | 3 | Zero total drug cost. | `data/rx/2024/eb93146da0790f67/glipizide` → `0.0`; `data/rx/2024/547572ece2c22116/metformin-hcl` → `0.0`; `data/rx/2024/65feccd696f1a9fd/glimepiride` → `0.0` |
| Warning | 1 | Product has more than one manufacturer (application holder) on record. | `data/product/byetta` |
| Info | 130 | Primary specialty is 'Student in an Organized Health Care Education/Training Program'; use the CMS prescriber type for analysis. | `data/hcp/cc28a1eaa3fb2133` → `vocab/specialty/390200000X`; `data/hcp/27bf1405d644acfe` → `vocab/specialty/390200000X`; `data/hcp/149c8895ab5f447d` → `vocab/specialty/390200000X` |
