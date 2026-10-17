"""Run from this directory with: python -m streamlit run app.py"""

import os

import plotly.express as px
import streamlit as st

from cruise_ai.assistant import AssistantError, DEFAULT_MODEL, EXAMPLES, plan_question
from cruise_ai.data import FACT_PATH, load_dataset
from cruise_ai.models import Filters, QueryPlan
from cruise_ai.query import GROUP_LABELS, METRICS, execute_plan, filter_rows, summarize

st.set_page_config(page_title="Cruise Analytics Copilot", page_icon="⚓", layout="wide")
st.markdown("""
<style>
.block-container {max-width: 1240px; padding-top: 2.3rem;}
.cruise-eyebrow {color: #087f8c; font-size: .78rem; letter-spacing: .16em;
                text-transform: uppercase; font-weight: 700; margin-bottom: .4rem;}
h1 {letter-spacing: -.04em;}
[data-testid="stMetric"] {background: #fff; border: 1px solid #dce6eb;
                         border-radius: 12px; padding: 1rem;}
[data-testid="stMetricValue"] {font-size: 1.7rem;}
</style>
""", unsafe_allow_html=True)


@st.cache_data
def get_dataset():
    return load_dataset()


def setting(name: str, default: str = "") -> str:
    if value := os.environ.get(name):
        return value
    try:
        return str(st.secrets.get(name, default))
    except (FileNotFoundError, KeyError):
        return default


def chart_for(result):
    label = METRICS[result.plan.metric][1]
    group_label = GROUP_LABELS[result.plan.group_by]
    table = result.table
    if result.plan.group_by == "year":
        figure = px.line(
            table.sort_values("group"), x="group", y="value", markers=True,
            labels={"group": group_label, "value": label},
            color_discrete_sequence=["#087f8c"],
        )
        figure.update_xaxes(dtick=1, tickformat="d")
        figure.update_traces(line_width=3, marker_size=8)
    else:
        # Treat durations as categories so bars remain legible alongside ship/line names.
        table = table.copy()
        table["group"] = table["group"].astype(str)
        figure = px.bar(
            table, x="value", y="group", orientation="h",
            labels={"group": group_label, "value": label},
            color_discrete_sequence=["#087f8c"],
        )
        figure.update_yaxes(autorange="reversed", categoryorder="array", categoryarray=table["group"].tolist())
    figure.update_layout(
        height=370, margin=dict(l=0, r=20, t=20, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font_color="#142b40", hoverlabel_bgcolor="white",
    )
    figure.update_xaxes(showgrid=True, gridcolor="#e5edf1")
    return figure


try:
    dataset = get_dataset()
except (ValueError, OSError, KeyError) as error:
    st.error(f"The project data could not be loaded: {error}")
    st.stop()

api_key = setting("OPENAI_API_KEY")
if api_key == "replace-with-your-api-key":
    api_key = ""
model = setting("OPENAI_MODEL", DEFAULT_MODEL)
first_year, last_year = int(dataset.rows.year.min()), int(dataset.rows.year.max())

with st.sidebar:
    st.markdown("### ⚓ Cruise Critic")
    st.caption("DATABASE → ANALYTICS → AI")
    st.divider()
    mode = st.radio("Question mode", ["Demo examples", "AI assistant"])
    if mode == "Demo examples":
        st.caption("Prepared questions. No API key or AI call needed.")
    else:
        st.caption("AI interprets your question. Results are calculated from the data.")
        st.caption("API configured" if api_key else "API key needed")
    st.divider()
    st.markdown("#### Explore a slice")
    if first_year == last_year:
        years = (first_year, last_year)
        st.caption(f"Observation year: {first_year}")
    else:
        years = st.slider("Observation years", first_year, last_year, (first_year, last_year))
    companies = st.multiselect(
        "Cruise lines", sorted(dataset.rows.company_name.unique()),
        help="Leave empty to include every cruise line in the fact data.",
    )
    destinations = st.multiselect(
        "Destinations", sorted(dataset.rows.destination_name.unique()),
        help="Leave empty to include every destination in the fact data.",
    )
    minimum_rating = st.slider("Minimum deal rating", 0.0, 5.0, 0.0, 0.1)
    st.caption("Filters apply to both questions and the data explorer. Empty selections include all categories.")
    st.divider()
    st.caption(f"{len(dataset.rows):,} exported deal records · {first_year}–{last_year}")
    st.caption("Local analysis with no Microsoft account required.")

scope = Filters(
    start_year=years[0], end_year=years[1], cruise_lines=companies,
    destinations=destinations, min_rating=minimum_rating,
)
visible = filter_rows(dataset, scope)
scope_signature = (mode, scope.model_dump_json())
if st.session_state.get("scope_signature") != scope_signature:
    st.session_state.pop("last_analysis", None)
    st.session_state["scope_signature"] = scope_signature

st.markdown('<div class="cruise-eyebrow">Cruise Critic · AI Analysis</div>', unsafe_allow_html=True)
st.title("Your data. A clearer course.")
st.markdown("Ask about cruise prices, ratings, and destinations. Follow each answer back to the data.")

metrics = st.columns(4)
metrics[0].metric("Deal records", f"{len(visible):,}")
metrics[1].metric("Avg. deal price", f"{visible.price.mean():,.2f}" if len(visible) else "—")
metrics[2].metric("Avg. price / day", f"{visible.price_per_day.mean():,.2f}" if len(visible) else "—")
metrics[3].metric("Avg. rating / 5", f"{visible.rating.mean():.2f}" if len(visible) else "—")
st.caption("Prices are shown in the source dataset’s units; currency is unspecified. Counts describe exported deals.")

ask_tab, explore_tab, notes_tab = st.tabs(["Ask the data", "Explore", "Data notes"])

with ask_tab:
    st.subheader("What would you like to find out?")
    prompt, prepared_plan = None, None
    if mode == "Demo examples":
        st.info("Demo mode runs prepared questions against the real project CSV. Enable AI assistant mode for your own questions.")
        with st.form("demo_question"):
            example = st.selectbox("Example question", list(EXAMPLES))
            submitted = st.form_submit_button("Analyze example", type="primary")
        if submitted:
            prompt, prepared_plan = example, EXAMPLES[example].model_copy(deep=True)
    else:
        if not api_key:
            st.warning("Add an OpenAI API key to enable questions. The demo and explorer are ready to use.")
            st.markdown("Setup: copy `.streamlit/secrets.example.toml` to `.streamlit/secrets.toml` inside `AIAnalysis`, then add your key and restart the app.")
        else:
            st.caption("Your question, the dataset schema, category names, and active filters are sent to OpenAI. Raw deal rows stay local. API usage may incur charges.")
        st.caption("Ask one complete question at a time. For example: “Which destinations have the lowest average price in 2024?”")
        prompt = st.chat_input(
            "Ask about prices, ratings, or deal counts…",
            disabled=not bool(api_key), max_chars=1000,
        )

    if prompt:
        # Replace old output immediately; a failed request must not leave an old answer visible.
        st.session_state.pop("last_analysis", None)
        with st.spinner("Checking your question against the dataset…"):
            try:
                plan = prepared_plan or plan_question(prompt, dataset, scope, api_key, model)
                if plan.kind == "unsupported":
                    reply = {"question": prompt, "message": plan.message or "Try asking about one supported measure: price, price per day, rating, or deal count."}
                else:
                    result = execute_plan(dataset, plan, scope)
                    reply = {"question": prompt, "result": result}
                st.session_state["last_analysis"] = reply
            except (AssistantError, ValueError) as error:
                st.error(str(error))

    if reply := st.session_state.get("last_analysis"):
        with st.chat_message("user"):
            st.write(reply["question"])
        with st.chat_message("assistant"):
            if "message" in reply:
                st.info(reply["message"])
            else:
                result = reply["result"]
                st.caption("Demo example · calculated locally" if mode == "Demo examples" else "AI interpreted · calculated locally")
                st.markdown(summarize(result))
                if not result.table.empty:
                    if result.plan.group_by != "none":
                        st.plotly_chart(chart_for(result), width="stretch")
                    output = result.table.rename(columns={
                        "group": GROUP_LABELS[result.plan.group_by],
                        "value": METRICS[result.plan.metric][1], "records": "Records in group",
                    })
                    st.dataframe(output, hide_index=True, width="stretch")
                    st.download_button("Download results as CSV", output.to_csv(index=False).encode(),
                                       "cruise-analysis.csv", "text/csv")
                with st.expander("Show evidence and analysis details"):
                    st.caption(f"Source: {FACT_PATH}. All {result.matched_records:,} matching records are available below.")
                    st.code(result.sql, language="sql")
                    st.write("Bound parameters", result.parameters)
                    st.json({"question_plan": result.plan.model_dump(), "sidebar_filters": result.scope.model_dump()}, expanded=False)
                    st.dataframe(result.source_rows, hide_index=True, width="stretch")
                    st.download_button(
                        "Download matching source records", result.source_rows.to_csv(index=False).encode(),
                        "cruise-source-records.csv", "text/csv",
                    )
    else:
        st.markdown("**A few places to start**")
        st.markdown("Compare cruise lines by price per day, track yearly average prices, or explore destination ratings.")

with explore_tab:
    st.subheader("See the patterns behind the answers")
    st.caption("These charts use the sidebar filters. Question-specific filters apply only to that answer.")
    if visible.empty:
        st.info("No records match the active filters. Widen the range to explore the data.")
    else:
        left, right = st.columns(2)
        with left:
            st.markdown("**Average price per day by cruise line**")
            result = execute_plan(dataset, QueryPlan(metric="avg_price_per_day", group_by="cruise_line", direction="asc"), scope)
            st.plotly_chart(chart_for(result), width="stretch", key="explore_price")
        with right:
            st.markdown("**Average rating over observation years**")
            result = execute_plan(dataset, QueryPlan(metric="avg_rating", group_by="year", sort_by="group", direction="asc"), scope)
            st.plotly_chart(chart_for(result), width="stretch", key="explore_rating")
        st.markdown("**Filtered deal records**")
        st.dataframe(visible, hide_index=True, width="stretch")
        st.download_button("Download filtered data", visible.to_csv(index=False).encode(), "cruise-filtered-data.csv", "text/csv")

with notes_tab:
    st.subheader("Understand the source")
    st.markdown("This app extends a database course project and its Power BI dashboards with a Python interface for questions and exploration.")
    st.markdown("**Why a separate app?** Signing up for the Power BI online service normally requires a work or school account; a personal email alone does not qualify. This app provides another way to explore the CSV data and ask questions without a Power BI service login. Power BI Desktop remains available for local report creation.")
    st.markdown("[Microsoft: individual Power BI service signup](https://learn.microsoft.com/en-us/power-bi/fundamentals/service-self-service-signup-purchase-for-power-bi) · [Power BI Desktop](https://learn.microsoft.com/en-us/power-bi/fundamentals/desktop-get-the-desktop)")
    st.markdown("**How to read the measures**")
    st.markdown("""
- Each fact row is an exported cruise deal record, not a confirmed booking or passenger.
- Deal price is an offer-level measure. Sales revenue and actual profit are unavailable.
- Average price per day is the mean of each deal’s `PRICE / DURATION`.
- Ratings come from the fact export and use a 0–5 scale.
- Years come from `REVIEW_DATE`, treated as the observation date.
- The static course dataset does not establish current availability, review sentiment, or causes of trends.
""")
    st.markdown("**Source checks**")
    st.dataframe(dataset.audit, hide_index=True, width="stretch")
    st.caption("Issues are reported without altering the source CSVs. Analytics use the fact table directly; unreliable trip links are not joined.")
    st.markdown("**AI scope**")
    st.markdown("AI mode interprets your question into a validated plan. The app builds the SQL from supported measures and filters, calculates results locally, and writes a factual summary from those results. Demo mode uses fixed plans. Neither mode trains a model on these records.")
