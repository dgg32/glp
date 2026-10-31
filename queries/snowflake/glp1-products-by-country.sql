-- GLP-1 receptor agonist products by country and Japanese therapeutic category. Snowflake twin of
-- queries/jp-glp1-by-japanese-category-reasoning.rq: there is no reasoner here, so IS_GLP1_PRODUCT is the OWL
-- definition of dm:GLP1Product compiled into SQL by scripts/build_osi.py (a substance in the GLP-1 class or a
-- narrower one, via the materialized skos:broader*). It never mentions 249 or 396, yet finds the products in both.
-- scripts/deploy_semantic_view.py checks that it gives the graph's numbers.
SELECT 'Japan' AS COUNTRY, c.PREF_LABEL_JA AS CATEGORY, COUNT(*) AS PRODUCTS, MIN(p.PRODUCT_NAME_JA) AS EXAMPLE
FROM GLP.SEMANTIC.JP_PRODUCT_PROFILE p
JOIN GLP.VOCAB.JP_DRUG_CLASS c ON c.JP_CLASS_CODE = p.JP_CLASS_CODE
WHERE p.IS_GLP1_PRODUCT
GROUP BY 1, 2
UNION ALL
SELECT 'US (Connecticut)', '-', COUNT(*), MIN(BRAND_NAME)
FROM GLP.SEMANTIC.PRODUCT_PROFILE
WHERE IS_GLP1_PRODUCT
ORDER BY 1, 2;
