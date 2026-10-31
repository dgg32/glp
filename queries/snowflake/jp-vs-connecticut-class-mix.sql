-- Japan (NDB FY2024, yen at NHI prices) vs Connecticut (Medicare Part D 2024, gross USD): each class's share of the
-- country's diabetes drug value, single-ingredient products. Snowflake twin of queries/jp-vs-connecticut-class-mix.rq:
-- the two countries meet in the shared class tree (VOCAB.THERAPEUTIC_CLASS, materialized as *.PRODUCT_CLASS), and
-- each country's total is its top class, which every product reaches once. Shares, not amounts.
-- scripts/deploy_semantic_view.py checks that it gives the graph's numbers.
WITH value AS (
  SELECT 'Japan' AS COUNTRY, pc.CLASS_ID, t.TOTAL_QUANTITY * p.NHI_PRICE AS VALUE
  FROM GLP.JP.NATIONAL_TOTAL t
  JOIN GLP.JP.PRODUCT p ON p.PRODUCT_ID = t.PRODUCT_ID
  JOIN GLP.JP.PRODUCT_CLASS pc ON pc.PRODUCT_ID = t.PRODUCT_ID
  WHERE NOT t.IS_MASKED AND NOT p.IS_COMBINATION
  UNION ALL
  SELECT 'Connecticut', pc.CLASS_ID, rx.TOTAL_DRUG_COST
  FROM GLP.US.PRESCRIPTION rx
  JOIN GLP.US.PRODUCT p ON p.PRODUCT_ID = rx.PRODUCT_ID
  JOIN GLP.US.PRODUCT_CLASS pc ON pc.PRODUCT_ID = rx.PRODUCT_ID
  WHERE NOT p.IS_COMBINATION
),
share AS (
  SELECT COUNTRY, CLASS_ID,
         SUM(VALUE) / SUM(SUM(IFF(CLASS_ID = 'DrugsUsedInDiabetes', VALUE, 0))) OVER (PARTITION BY COUNTRY) AS SHARE
  FROM value GROUP BY COUNTRY, CLASS_ID
)
SELECT c.PREF_LABEL_EN AS CLASS_NAME, c.PREF_LABEL_JA AS CLASS_NAME_JA,
       ROUND(100 * COALESCE(MAX(IFF(s.COUNTRY = 'Japan', s.SHARE, NULL)), 0), 1) AS JAPAN_PCT,
       ROUND(100 * COALESCE(MAX(IFF(s.COUNTRY = 'Connecticut', s.SHARE, NULL)), 0), 1) AS CONNECTICUT_PCT
FROM GLP.VOCAB.THERAPEUTIC_CLASS c
LEFT JOIN share s ON s.CLASS_ID = c.CLASS_ID
WHERE c.CLASS_ID IN ('Insulin', 'Biguanide', 'Sulfonylurea', 'Thiazolidinedione', 'DPP4Inhibitor',
                     'AlphaGlucosidaseInhibitor', 'Glinide', 'Glimin', 'SGLT2Inhibitor', 'GLP1ReceptorAgonist')
GROUP BY 1, 2
ORDER BY JAPAN_PCT DESC;
