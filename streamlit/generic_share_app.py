"""Streamlit in Snowflake app: Japan's generic share by month, and the metformin definition trap.

Paste into a second Streamlit app in Snowsight (Workspaces > generic_share_app.py). Reads GLP.VOCAB and GLP.JP only;
every statement is a fixed SELECT with no user input in it (the substance choice filters the result in pandas).

From October 2024, patients in Japan pay part of the price gap when they choose an off-patent brand that has a
generic (長期収載品の選定療養). The month tables of NDB Open Data FY2024 show the reaction in the same month.

Tabs:
  1. Generic share by month  oral tablets dispensed by community pharmacies, per substance, with the October 2024
                             rule marked; a toggle counts generics priced like their originator, which NDB's flag
                             leaves out
  2. The metformin trap      metformin tablets by status: originator, flagged generic, generic priced like the
                             originator (not flagged)
"""
import altair as alt
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Generic share in Japan", layout="wide")

conn = st.connection("snowflake")
session = conn.session()


@st.cache_data(ttl=3600, show_spinner=False)
def run(sql: str) -> pd.DataFrame:
    return session.sql(sql).to_pandas()


# --- Language: substance names come from the SKOS vocabulary, not from the app ---
LANGS = {"English": "EN", "日本語": "JA", "中文": "ZH"}
lang = LANGS[st.sidebar.radio("Labels / ラベル / 标签", list(LANGS))]
label = f"PREF_LABEL_{lang}"  # column name from a fixed list, never user text

st.sidebar.markdown(
    "**Data**  \n"
    "NDB Open Data FY2024 (Apr 2024 – Mar 2025), oral single-ingredient products, outpatient prescriptions "
    "dispensed by community pharmacies (外来・院外). Quantities are tablets. Masked small cells are left out.  \n\n"
    "**Generic** is NDB's flag: a generic priced like its originator is not flagged."
)

RULE_START = pd.Timestamp("2024-10-01")

# One row per substance and month: all tablets, tablets flagged generic, tablets of non-originator products.
# Every substance with a flagged generic, plus metformin, whose generics are almost all unflagged.
monthly = run(f"""
    SELECT s.SUBSTANCE_ID, COALESCE(s.{label}, s.PREF_LABEL_EN) AS SUBSTANCE, q.MONTH,
           SUM(q.QUANTITY) AS TABLETS,
           SUM(IFF(p.IS_GENERIC, q.QUANTITY, 0)) AS FLAGGED_GENERIC,
           SUM(IFF(NOT p.IS_ORIGINATOR, q.QUANTITY, 0)) AS NON_ORIGINATOR,
           SUM(IFF(p.IS_ORIGINATOR, q.QUANTITY, 0)) AS ORIGINATOR
    FROM GLP.JP.QUANTITY q
    JOIN GLP.JP.PRODUCT p ON p.PRODUCT_ID = q.PRODUCT_ID
    JOIN GLP.JP.PRODUCT_SUBSTANCE ps ON ps.PRODUCT_ID = q.PRODUCT_ID
    JOIN GLP.VOCAB.SUBSTANCE s ON s.SUBSTANCE_ID = ps.SUBSTANCE_ID
    WHERE q.BREAKDOWN = 'month' AND NOT q.IS_MASKED AND q.CARE_SETTING_ID = 'outpatient-external'
      AND p.ROUTE = 'oral' AND NOT p.IS_COMBINATION
      AND s.SUBSTANCE_ID IN (
        SELECT ps2.SUBSTANCE_ID FROM GLP.JP.PRODUCT_SUBSTANCE ps2
        JOIN GLP.JP.PRODUCT p2 ON p2.PRODUCT_ID = ps2.PRODUCT_ID
        WHERE p2.IS_GENERIC AND p2.ROUTE = 'oral' AND NOT p2.IS_COMBINATION
        UNION SELECT 'metformin')
    GROUP BY 1, 2, 3
    ORDER BY 1, 3""")
monthly["MONTH"] = pd.to_datetime(monthly["MONTH"])

st.title("Generic share in Japan, FY2024")
st.caption("From October 2024, patients pay extra when they choose an off-patent brand over its generic "
           "(長期収載品の選定療養). The monthly data shows the reaction in the same month.")

tab_share, tab_trap = st.tabs(["Generic share by month", "The metformin trap"])

# --- 1. Generic share by month --------------------------------------------------------------------------
with tab_share:
    names = (monthly.groupby(["SUBSTANCE_ID", "SUBSTANCE"]).TABLETS.sum()
             .reset_index().sort_values("TABLETS", ascending=False))
    by_id = dict(zip(names.SUBSTANCE_ID, names.SUBSTANCE))
    default_ids = ["metformin", "glimepiride", "voglibose", "miglitol", "repaglinide", "pioglitazone",
                   "mitiglinide", "gliclazide"]
    chosen = st.multiselect("Substances", list(by_id.values()),
                            default=[by_id[i] for i in default_ids if i in by_id])
    corrected = st.toggle("Also count generics priced like their originator (not flagged by NDB)", value=False)

    data = monthly[monthly.SUBSTANCE.isin(chosen)].copy()
    numerator = "NON_ORIGINATOR" if corrected else "FLAGGED_GENERIC"
    data["GENERIC_PCT"] = (100 * data[numerator] / data.TABLETS).round(1)

    lines = (
        alt.Chart(data)
        .mark_line(point=True)
        .encode(
            x=alt.X("MONTH:T", title=None, axis=alt.Axis(format="%Y-%m")),
            y=alt.Y("GENERIC_PCT:Q", title="Generic share of tablets (%)", scale=alt.Scale(domain=[0, 100])),
            color=alt.Color("SUBSTANCE:N", title=None),
            strokeDash=alt.condition(alt.datum.SUBSTANCE_ID == "metformin", alt.value([6, 3]), alt.value([1, 0])),
            tooltip=["SUBSTANCE", alt.Tooltip("MONTH:T", format="%Y-%m"), "GENERIC_PCT"],
        )
    )
    rule = (
        alt.Chart(pd.DataFrame({"MONTH": [RULE_START], "TEXT": ["Brand surcharge starts / 選定療養開始"]}))
        .mark_rule(color="#6b7280", strokeDash=[4, 4])
        .encode(x="MONTH:T")
    )
    rule_label = rule.mark_text(align="left", dx=4, dy=-8, color="#6b7280").encode(
        text="TEXT:N", y=alt.value(12))
    st.altair_chart((lines + rule + rule_label).properties(height=460), use_container_width=True)

    # September -> October change per substance
    sep = data[data.MONTH == RULE_START - pd.offsets.MonthBegin(1)].set_index("SUBSTANCE").GENERIC_PCT
    oct_ = data[data.MONTH == RULE_START].set_index("SUBSTANCE").GENERIC_PCT
    mar = data[data.MONTH == data.MONTH.max()].set_index("SUBSTANCE").GENERIC_PCT
    table = pd.DataFrame({"Sep 2024 (%)": sep, "Oct 2024 (%)": oct_, "Mar 2025 (%)": mar})
    table["Sep → Oct (points)"] = (table["Oct 2024 (%)"] - table["Sep 2024 (%)"]).round(1)
    st.dataframe(table.sort_values("Sep → Oct (points)", ascending=False), use_container_width=True)

    st.caption("Metformin (dashed) stays at 0.2% with NDB's flag. Switch on the toggle to see its real generic "
               "share. Tablets are comparable within one substance, not across substances.")

# --- 2. The metformin trap ------------------------------------------------------------------------------
with tab_trap:
    st.markdown(
        "NDB flags a drug as generic only if it is priced below the original. Most metformin generics cost "
        "the same as the originator Metgluco (メトグルコ, ¥10.10 a tablet), so they are not flagged. "
        "A dashboard built on the flag would claim that nobody in Japan takes generic metformin."
    )
    met = monthly[monthly.SUBSTANCE_ID == "metformin"].copy()
    met["UNFLAGGED_GENERIC"] = met.NON_ORIGINATOR - met.FLAGGED_GENERIC
    parts = {"ORIGINATOR": "Originator (Metgluco)",
             "UNFLAGGED_GENERIC": "Generic priced like the originator (not flagged)",
             "FLAGGED_GENERIC": "Generic (flagged by NDB)"}
    long = met.melt(id_vars="MONTH", value_vars=list(parts), var_name="STATUS", value_name="UNITS")
    long["STATUS"] = long.STATUS.map(parts)
    long["PCT"] = (100 * long.UNITS / long.groupby("MONTH").UNITS.transform("sum")).round(1)

    area = (
        alt.Chart(long)
        .mark_area()
        .encode(
            x=alt.X("MONTH:T", title=None, axis=alt.Axis(format="%Y-%m")),
            y=alt.Y("PCT:Q", stack="normalize", title="Share of metformin tablets",
                    axis=alt.Axis(format="%")),
            color=alt.Color("STATUS:N", title=None, sort=list(parts.values()),
                            scale=alt.Scale(range=["#9ca3af", "#22c55e", "#ef4444"])),
            order=alt.Order("STATUS:N"),
            tooltip=["STATUS", alt.Tooltip("MONTH:T", format="%Y-%m"), "PCT"],
        )
        .properties(height=380)
    )
    st.altair_chart(area + rule, use_container_width=True)

    total = long.groupby("STATUS").UNITS.sum()
    c1, c2, c3 = st.columns(3)
    for col, key in zip((c1, c2, c3), parts.values()):
        col.metric(key, f"{100 * total[key] / total.sum():.1f}%")
    st.caption("Metformin moves by only about one point in October 2024. Most of its generics cost the same as "
               "the brand, so the surcharge, a share of the price gap, has little or nothing to charge.")
