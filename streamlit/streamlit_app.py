"""Streamlit in Snowflake app over the GLP database: one drug vocabulary, two countries.

Paste into a Streamlit app in Snowsight (Workspaces > streamlit_app.py). Reads GLP.VOCAB, GLP.US and GLP.JP only;
every statement is a fixed SELECT, and the one user choice that reaches SQL (the substance) is a bound parameter.

Tabs:
  1. Drug class tree   the shared SKOS class tree, labels in the chosen language, substances coloured by dataset
  2. Class mix         each class's share of the diabetes drug value, Connecticut vs Japan
  3. One substance     the same substance in both datasets: Connecticut claims and cost, Japan's monthly value
"""
import altair as alt
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Diabetes drugs: Connecticut and Japan", layout="wide")

conn = st.connection("snowflake")
session = conn.session()


@st.cache_data(ttl=3600, show_spinner=False)
def run(sql: str, params: tuple = ()) -> pd.DataFrame:
    return session.sql(sql, params=list(params)).to_pandas()


# --- Language: every label below comes from the SKOS vocabularies, not from the app ---
LANGS = {"English": "EN", "日本語": "JA", "中文": "ZH"}
lang = LANGS[st.sidebar.radio("Labels / ラベル / 标签", list(LANGS))]
label = f"PREF_LABEL_{lang}"  # column name from a fixed list, never user text

st.sidebar.markdown(
    "**Data**  \n"
    "Connecticut: Medicare Part D 2024, mostly people 65+, gross cost in USD.  \n"
    "Japan: NDB Open Data FY2024 (Apr 2024 – Mar 2025), value = quantity × NHI price, in yen. "
    "Masked small cells are left out, so Japanese figures are lower bounds."
)

st.title("Diabetes drugs: Connecticut and Japan")
st.caption("One drug class vocabulary shared by both datasets. Switch the label language in the sidebar.")

tab_tree, tab_mix, tab_substance = st.tabs(["Drug class tree", "Class mix", "One substance"])

# --- 1. Class tree --------------------------------------------------------------------------------------
with tab_tree:
    classes = run(f"""
        SELECT CLASS_ID, NOTATION, BROADER_CLASS_ID, COALESCE({label}, PREF_LABEL_EN) AS LABEL
        FROM GLP.VOCAB.THERAPEUTIC_CLASS""")
    substances = run(f"""
        SELECT s.SUBSTANCE_ID, s.CLASS_ID, COALESCE(s.{label}, s.PREF_LABEL_EN) AS LABEL,
               EXISTS (SELECT 1 FROM GLP.US.PRODUCT_SUBSTANCE u WHERE u.SUBSTANCE_ID = s.SUBSTANCE_ID) AS IN_US,
               EXISTS (SELECT 1 FROM GLP.JP.PRODUCT_SUBSTANCE j WHERE j.SUBSTANCE_ID = s.SUBSTANCE_ID) AS IN_JP
        FROM GLP.VOCAB.SUBSTANCE s""")

    show_substances = st.checkbox("Show substances", value=True)

    def q(text: str) -> str:
        return text.replace("\\", "\\\\").replace('"', '\\"')

    dot = [
        "digraph G {",
        "rankdir=LR; bgcolor=transparent;",
        'node [shape=box, style="rounded,filled", fillcolor="#eef2ff", color="#6366f1", fontname="Helvetica"];',
        'edge [color="#94a3b8"];',
    ]
    for c in classes.itertuples():
        text = f"{c.NOTATION}\\n{q(c.LABEL)}" if c.NOTATION else q(c.LABEL)
        dot.append(f'"{c.CLASS_ID}" [label="{text}"];')
        if c.BROADER_CLASS_ID:
            dot.append(f'"{c.BROADER_CLASS_ID}" -> "{c.CLASS_ID}";')
    if show_substances:
        colours = {(True, True): "#bbf7d0", (True, False): "#bfdbfe", (False, True): "#fecaca"}
        for s in substances.itertuples():
            fill = colours.get((bool(s.IN_US), bool(s.IN_JP)), "#e5e7eb")
            dot.append(f'"s_{s.SUBSTANCE_ID}" [label="{q(s.LABEL)}", shape=ellipse, '
                       f'fillcolor="{fill}", color="#9ca3af", fontsize=11];')
            dot.append(f'"{s.CLASS_ID}" -> "s_{s.SUBSTANCE_ID}";')
    dot.append("}")

    if show_substances:
        st.markdown("🟩 in both datasets  🟦 Connecticut data only  🟥 Japan data only")
    st.graphviz_chart("\n".join(dot), use_container_width=True)

# --- 2. Class mix ---------------------------------------------------------------------------------------
with tab_mix:
    st.markdown(
        "Each class's share of the country's diabetes drug value, single-ingredient products only. "
        "Shares, not amounts: yen and gross US dollars are not comparable."
    )
    mix = run(f"""
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
                 SUM(VALUE) / SUM(SUM(IFF(CLASS_ID = 'DrugsUsedInDiabetes', VALUE, 0)))
                   OVER (PARTITION BY COUNTRY) AS SHARE
          FROM value GROUP BY COUNTRY, CLASS_ID
        )
        SELECT COALESCE(c.{label}, c.PREF_LABEL_EN) AS CLASS_NAME, s.COUNTRY, ROUND(100 * s.SHARE, 1) AS PCT
        FROM GLP.VOCAB.THERAPEUTIC_CLASS c
        JOIN share s ON s.CLASS_ID = c.CLASS_ID
        WHERE c.CLASS_ID IN ('Insulin', 'Biguanide', 'Sulfonylurea', 'Thiazolidinedione', 'DPP4Inhibitor',
                             'AlphaGlucosidaseInhibitor', 'Glinide', 'Glimin', 'SGLT2Inhibitor',
                             'GLP1ReceptorAgonist')""")
    order = (mix[mix.COUNTRY == "Japan"].sort_values("PCT", ascending=False).CLASS_NAME.tolist()
             + mix[~mix.CLASS_NAME.isin(mix[mix.COUNTRY == "Japan"].CLASS_NAME)].CLASS_NAME.unique().tolist())
    chart = (
        alt.Chart(mix)
        .mark_bar()
        .encode(
            y=alt.Y("CLASS_NAME:N", sort=order, title=None),
            x=alt.X("PCT:Q", title="% of diabetes drug value"),
            yOffset="COUNTRY:N",
            color=alt.Color("COUNTRY:N", title=None,
                            scale=alt.Scale(domain=["Connecticut", "Japan"], range=["#3b82f6", "#ef4444"])),
            tooltip=["CLASS_NAME", "COUNTRY", "PCT"],
        )
        .properties(height=480)
    )
    st.altair_chart(chart, use_container_width=True)

# --- 3. One substance -----------------------------------------------------------------------------------
with tab_substance:
    both = substances[substances.IN_US & substances.IN_JP].sort_values("LABEL")
    names = dict(zip(both.LABEL, both.SUBSTANCE_ID))
    default = list(names.values()).index("tirzepatide") if "tirzepatide" in names.values() else 0
    chosen = st.selectbox("Substance (in both datasets)", list(names), index=default)
    substance_id = names[chosen]

    us = run("""
        SELECT p.BRAND_NAME AS PRODUCT, SUM(rx.TOTAL_CLAIMS) AS CLAIMS, SUM(rx.TOTAL_DRUG_COST) AS COST_USD
        FROM GLP.US.PRESCRIPTION rx
        JOIN GLP.US.PRODUCT p ON p.PRODUCT_ID = rx.PRODUCT_ID
        JOIN GLP.US.PRODUCT_SUBSTANCE ps ON ps.PRODUCT_ID = rx.PRODUCT_ID
        WHERE ps.SUBSTANCE_ID = ?
        GROUP BY 1 ORDER BY 3 DESC""", (substance_id,))
    jp_month = run("""
        SELECT q.MONTH, SUM(q.QUANTITY * p.NHI_PRICE) / 1e8 AS VALUE_OKU_YEN
        FROM GLP.JP.QUANTITY q
        JOIN GLP.JP.PRODUCT p ON p.PRODUCT_ID = q.PRODUCT_ID
        JOIN GLP.JP.PRODUCT_SUBSTANCE ps ON ps.PRODUCT_ID = q.PRODUCT_ID
        WHERE q.BREAKDOWN = 'month' AND NOT q.IS_MASKED AND ps.SUBSTANCE_ID = ?
        GROUP BY 1 ORDER BY 1""", (substance_id,))
    jp_products = run("""
        SELECT p.PRODUCT_NAME AS PRODUCT, COALESCE(o.NAME_JA, o.NAME_EN) AS HOLDER,
               SUM(t.TOTAL_QUANTITY * p.NHI_PRICE) / 1e8 AS VALUE_OKU_YEN
        FROM GLP.JP.NATIONAL_TOTAL t
        JOIN GLP.JP.PRODUCT p ON p.PRODUCT_ID = t.PRODUCT_ID
        JOIN GLP.JP.PRODUCT_SUBSTANCE ps ON ps.PRODUCT_ID = t.PRODUCT_ID
        LEFT JOIN GLP.JP.ORGANIZATION o ON o.ORGANIZATION_ID = p.ORGANIZATION_ID
        WHERE ps.SUBSTANCE_ID = ? AND NOT t.IS_MASKED
        GROUP BY 1, 2 ORDER BY 3 DESC""", (substance_id,))

    left, right = st.columns(2)
    with left:
        st.subheader("Connecticut, 2024")
        c1, c2 = st.columns(2)
        c1.metric("Claims", f"{us.CLAIMS.sum():,.0f}")
        c2.metric("Gross cost", f"${us.COST_USD.sum() / 1e6:,.1f}M")
        st.dataframe(us, hide_index=True, use_container_width=True,
                     column_config={"COST_USD": st.column_config.NumberColumn("Cost (USD)", format="$%.0f")})
    with right:
        st.subheader("Japan, FY2024")
        st.metric("Value", f"{jp_products.VALUE_OKU_YEN.sum():,.1f} 億円")
        line = (
            alt.Chart(jp_month)
            .mark_line(point=True, color="#ef4444")
            .encode(x=alt.X("MONTH:T", title=None, axis=alt.Axis(format="%Y-%m")),
                    y=alt.Y("VALUE_OKU_YEN:Q", title="億円 (100 million yen)"),
                    tooltip=[alt.Tooltip("MONTH:T", format="%Y-%m"),
                             alt.Tooltip("VALUE_OKU_YEN:Q", format=",.1f")])
            .properties(height=260)
        )
        st.altair_chart(line, use_container_width=True)
        st.dataframe(jp_products, hide_index=True, use_container_width=True,
                     column_config={"VALUE_OKU_YEN": st.column_config.NumberColumn("Value (億円)", format="%.1f")})

    st.caption("Products that contain the substance, including combination products. "
               "Japan lists each strength as its own product.")
