"""A simple screen: choose an example, or ask your own question."""

import os

import streamlit as st

from cruise_ai.assistant import AssistantError, DEFAULT_MODEL, EXAMPLES, plan_question
from cruise_ai.data import FACT_PATH, load_dataset
from cruise_ai.local_ai import list_ollama_models, plan_with_ollama
from cruise_ai.models import Filters
from cruise_ai.query import GROUP_LABELS, METRICS, execute_plan, summarize

st.set_page_config(page_title="Cruise Data Helper", page_icon="⚓")


@st.cache_data
def get_dataset():
    return load_dataset()


def saved_setting(name, default=""):
    """Advanced users can still use environment variables or a secrets file."""
    if value := os.environ.get(name):
        return value
    try:
        return str(st.secrets.get(name, default))
    except (FileNotFoundError, KeyError):
        return default


@st.cache_data(ttl=10, show_spinner=False)
def get_local_models():
    try:
        return list_ollama_models(), ""
    except AssistantError as error:
        return [], str(error)


# 1. Read the CSV data already included in the project.
try:
    dataset = get_dataset()
except (ValueError, OSError, KeyError):
    st.error("I couldn't open the cruise data. Keep the FactTable and DimensionTables folders next to AIAnalysis.")
    st.stop()

st.title("⚓ Cruise Data Helper")
st.write("Ask a question about cruise prices, ratings, or destinations.")
st.caption(f"{len(dataset.rows):,} sample deal records · {int(dataset.rows.year.min())}–{int(dataset.rows.year.max())}")

# 2. Ollama uses a model on this computer. OpenAI is an optional alternative.
api_key, model, connection_message = "", None, ""
with st.expander("AI settings"):
    provider = st.selectbox("Use AI from", ["Ollama (on this computer)", "OpenAI (API key)"], key="provider")
    if provider.startswith("Ollama"):
        models, connection_message = get_local_models()
        if models:
            model = st.selectbox("Installed model", models, key="ollama_model")
        else:
            st.info(connection_message or "Ollama is running, but no local models were found. Add a chat model in Ollama, then check again.")
        st.button("Check again", on_click=get_local_models.clear)
        st.caption("Uses Ollama on this computer. No API key or paid API calls.")
    else:
        entered_key = st.text_input(
            "OpenAI API key", type="password", key="session_api_key",
            placeholder="Paste your API key here",
        )
        api_key = entered_key.strip() or saved_setting("OPENAI_API_KEY")
        if api_key == "replace-with-your-api-key":
            api_key = ""
        model = saved_setting("OPENAI_MODEL", DEFAULT_MODEL)
        st.caption("A key entered here is kept only for this browser session. AI requests may cost money.")

using_ollama = provider.startswith("Ollama")
ready = bool(model) if using_ollama else bool(api_key)

st.subheader("Try an example")
st.caption("These examples use fixed questions and do not make AI calls.")
prompt, prepared_plan = None, None
examples = list(EXAMPLES.items())
for label, index in [
    ("Compare cruise prices", 0),
    ("Compare destination ratings", 2),
    ("See prices over time", 1),
]:
    if st.button(label, key=f"example_{index}", width="stretch"):
        prompt, prepared_plan = examples[index]
        prepared_plan = prepared_plan.model_copy(deep=True)

st.subheader("Or ask your own question")
if not ready:
    st.info("Open AI settings above to connect Ollama or add an OpenAI key. You can use the examples now.")
elif using_ollama:
    st.caption(f"Using {model} on this computer. No API key needed. Ask one complete question at a time.")
else:
    st.caption("Ask one complete question at a time. Your question and a summary of the dataset are sent to OpenAI; individual deal records stay local.")

with st.form("question_form"):
    question = st.text_input(
        "Your question", key="question", disabled=not ready, max_chars=1000,
        placeholder="Which destinations had the lowest average price in 2024?",
    )
    ask = st.form_submit_button("Ask", type="primary", disabled=not ready)
if ask:
    prompt, prepared_plan = question, None

# 3. AI interprets the question. Python calculates every number in the answer.
if prompt is not None:
    st.session_state.pop("answer", None)
    if not prompt.strip():
        st.warning("Type a question first, then click Ask.")
    else:
        with st.spinner("Finding your answer…"):
            try:
                if prepared_plan:
                    plan = prepared_plan
                elif using_ollama:
                    plan = plan_with_ollama(prompt, dataset, model)
                else:
                    plan = plan_question(prompt, dataset, Filters(), api_key, model)
                answer = {
                    "question": prompt, "used_ai": prepared_plan is None,
                    "provider": "Ollama" if using_ollama else "OpenAI", "model": model,
                }
                if plan.kind == "unsupported":
                    answer["message"] = plan.message or "Try asking about average prices, ratings, or how many deals are in the data."
                else:
                    answer["result"] = execute_plan(dataset, plan)
                st.session_state["answer"] = answer
            except (AssistantError, ValueError) as error:
                st.error(str(error))

# 4. Show a short answer and one chart. Extra detail stays folded away.
if answer := st.session_state.get("answer"):
    st.divider()
    st.subheader("Your answer")
    st.write(answer["question"])
    st.caption(f"{answer.get('provider', 'AI')} question · {answer.get('model', '')}" if answer["used_ai"] else "Example result · no AI used")
    if "message" in answer:
        st.info(answer["message"])
    else:
        result = answer["result"]
        st.markdown(summarize(result))
        if not result.table.empty:
            output = result.table.rename(columns={
                "group": GROUP_LABELS[result.plan.group_by],
                "value": METRICS[result.plan.metric][1], "records": "Number of deals",
            })
            if result.plan.group_by != "none":
                chart_data = output.set_index(GROUP_LABELS[result.plan.group_by])[[METRICS[result.plan.metric][1]]]
                if result.plan.group_by == "year":
                    chart_data = chart_data.sort_index()
                    chart_data.index = chart_data.index.astype(str)
                    st.line_chart(chart_data, color="#087f8c")
                else:
                    st.bar_chart(chart_data, color="#087f8c", horizontal=True, sort=False)
            with st.expander("See the data behind this answer"):
                st.dataframe(output, hide_index=True, width="stretch")
                st.download_button("Download this table", output.to_csv(index=False).encode(), "cruise-answer.csv", "text/csv")
                st.caption(f"Calculated from {result.matched_records:,} records in {FACT_PATH}.")
                st.code(result.sql, language="sql")
                st.write("Query values:", result.parameters)
                st.dataframe(result.source_rows, hide_index=True, width="stretch")

with st.expander("About the data"):
    st.write("This is the sample dataset from the Cruise Critic project, not a list of current cruise offers.")
    st.write("Prices use the source data's units; the currency isn't specified. Ratings are out of 5. Years come from the review dates.")
    st.write("Each row describes a deal, not a confirmed booking. Some trip references don't match the trip list, so answers use the deal table directly.")
