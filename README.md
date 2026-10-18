# Cruise Critic Data Helper

Explore cruise prices, ratings, and destinations through simple questions and charts.

## Overview

**Cruise Critic Data Helper** brings together a relational database, Power BI dashboards, and a Streamlit app for understanding cruise data. Ask a question in everyday language, get an answer calculated from the dataset, and view the chart and source records behind it.

AI is how the helper understands your question. By default, it uses a model installed on your computer through **Ollama**, so no API key is needed. Python and SQL calculate the numbers and prepare the answer. OpenAI is also available as a provider in the app's settings.

The project began as an **EECS 3421 – Database Systems** course project. Its database design, reporting, and question interface now form a single workflow for exploring the sample data.

## Contents

- [Run locally](#run-locally)
- [Ask about your data](#ask-about-your-data)
- [How the helper works](#how-the-helper-works)
- [Data definitions and current limitations](#data-definitions-and-current-limitations)
- [Database design](#database-design)
- [Power BI dashboards](#power-bi-dashboards)
- [Developer setup](#developer-setup)
- [Validation](#validation)
- [Project structure](#project-structure)
- [Planned improvements](#planned-improvements)

## Run locally

You need **Python 3.11 or newer** and **Ollama with a local chat model installed**.

Open Ollama, then open a terminal in the project folder and run:

```bash
python3 AIAnalysis/run.py
```

Open the local URL printed in the terminal, usually **http://localhost:8501**.

The launcher prepares the Python environment, installs the required packages, and starts the helper. The first run needs an internet connection and may take a few minutes. It does not download Ollama models. On Windows, use `python` if `python3` is unavailable.

To stop the helper, press **Ctrl+C** in the terminal. Run the same command whenever you want to use it again. The example buttons also work when Ollama is unavailable.

## Ask about your data

Type a complete question and click **Ask**. You can ask about average deal prices, price per day, ratings, or deal counts. Include a year, cruise line, destination, price limit, or duration to narrow the question.

For example:

- “Which cruise line has the lowest average price per day?”
- “Which destinations had the lowest average price in 2024?”
- “How many deal records are there in 2024?”

The helper shows a short answer and a chart when the result supports one. Open **See the data behind this answer** to inspect the result table, matching source records, and SQL calculation, or download the table.

Each question is independent. Current offers, future prices, actual revenue, and explanations of why a trend happened are outside the available data.

### Try an example

The three example buttons provide a quick introduction:

- **Compare cruise prices** — compare cruise lines by average price per day.
- **Compare destination ratings** — compare average destination ratings.
- **See prices over time** — compare average deal prices from 2023 to 2025.

These prepared examples run directly against the CSV data and do not make AI calls.

### AI settings

**Ollama (on this computer)** is selected by default. The helper automatically finds installed local models. Open **AI settings** to check or change the model. The first question may take longer while the model loads.

If Ollama was closed when the helper started, open it and click **Check again** in AI settings. You can also start Ollama in another terminal with `ollama serve`; `ollama list` shows installed models. The helper connects to `http://127.0.0.1:11434` on the same computer.

To use OpenAI, select **OpenAI (API key)** in AI settings and paste your key into the password field. A key entered there stays in memory for that browser session. OpenAI requests can incur API charges. Ollama requires no API key or paid API calls.

## How the helper works

1. **Understand the question:** the selected AI model identifies the measure, grouping, and filters to use.
2. **Check the request:** the helper validates that analysis plan against the supported measures and filters.
3. **Calculate the answer:** Python builds parameterized SQL and runs it against the validated deal records in DuckDB.
4. **Show the result:** Streamlit displays a factual summary, a relevant chart, and the supporting records.

The model interprets the question; every reported number is calculated from the data. The helper never executes model-written SQL or Python. Model interpretation still needs evaluation, because a valid analysis plan does not guarantee that a question was understood correctly.

With Ollama, the question and dataset summary stay on the computer running the helper. The model receives category names, available years, and record counts rather than individual deal rows. When OpenAI is selected, that same context is sent to OpenAI with `store=False`. The helper does not automatically switch from Ollama to OpenAI and does not train or fine-tune a model.

## Data definitions and current limitations

- **Dataset:** 366 sample deal records from 2019–2025, with an eight-trip catalog. These course-project records are not established as a representative sample of the cruise market.
- **Prices:** currency is unspecified. Price per day is calculated as `PRICE / DURATION` for each record before averaging.
- **Ratings:** fact-table ratings are out of 5. Ship and cruise-line catalog ratings are separate measures.
- **Years:** derived from `REVIEW_DATE`, treated as the observation date rather than a confirmed sailing or booking date.
- **Counts:** a deal record is not a confirmed booking, passenger, or destination visit.
- **Unavailable measures:** the exported fact CSV contains no actual sales, cost, or weather records. The SQL seed data includes only five short review titles, so review sentiment is not implemented.

### Relationship audit

The fact export has 366 distinct trip IDs. **358 records lack a matching trip ID** in the eight-row trip catalog. Of the eight matching IDs, **seven disagree on ship or cruise line**.

The helper reports these issues and analyzes the deal table directly, preserving all 366 fact records. It does not infer replacement trip IDs or join unreliable trip metadata. Source CSVs and the existing Power BI artifacts are unchanged.

The loader also checks required fields, unique deal IDs, valid ratings, positive finite prices and durations, whole-number identifiers, price-per-day consistency, and dimension coverage. CSV row numbers are retained for traceability.

---

## Database design

The relational database was developed for **EECS 3421 – Database Systems** to model a simplified Cruise Critic platform. It provides the project’s schema, constraints, and sample cruise records.

### Purpose

Design and implement a relational database to support core Cruise Critic functionality, including cruise search, deals, reviews, destinations, and community interaction.

### Technologies

- Microsoft SQL Server  
- Azure Data Studio  
- ERDPlus  

### Key Features

- Fully normalized relational schema  
- Primary and foreign key constraints  
- Referential and domain integrity enforcement  
- Sample data populated across all tables  
- Management-focused SQL queries (pricing, ratings, demand)

### Core Tables

- CRUISE_LINE  
- CRUISE_SHIP  
- CRUISE_TRIP  
- CRUISE_DEAL  
- DESTINATION  
- PORT  
- COMMUNITY_REVIEW  
- USER_ACCOUNT  
- FORUM

---

## Power BI dashboards

The Power BI reports provide dashboard views of cruise prices, ratings, destinations, and the project's analytical model.

The screenshots retain the reports' original revenue/spend labels and assumed **40% profit / 60% cost** measures. Those are course-project assumptions, not verified financial results. Some environmental measures shown in the reports are absent from the exported fact CSV. The helper uses the [data definitions](#data-definitions-and-current-limitations) when answering questions.

### Dashboard access

The data helper runs locally without a Microsoft account. Signing up directly for the **Power BI online service** normally requires a work or school account; a personal email alone does not qualify. **Power BI Desktop remains free for local report creation.** See Microsoft's [service signup guidance](https://learn.microsoft.com/en-us/power-bi/fundamentals/service-self-service-signup-purchase-for-power-bi) and [Desktop documentation](https://learn.microsoft.com/en-us/power-bi/fundamentals/desktop-get-the-desktop).

### Tools

- Power BI 
- SQL  
- DAX
- Database Markup Language

### Data Model

- **Fact Table:** FACT_CRUISE_ANALYTICS  
- **Dimensions:** Cruise Line, Cruise Trip, Destination, Cruise Ship, Date  

**Grain:** One row per cruise deal per trip.

The STAR schema is shown below:
(Note the surrogate keys for each DIMENSION table and the FACT table)

![Cruise Analytics Star Schema](PowerBIModelling/StarSchema.png)

The Power BI dashboard measures use this star schema.

### Model relationships

The analytical model follows a star schema design using the surrogate keys conceptually for all dimensions. In the Power BI implementation, natural keys (Trip ID, Company Name, Ship Name, Destination Name, and Review Date) define the relationships between fact and dimension tables. The data helper checks the exported CSVs and identifies missing and conflicting trip relationships; those data-quality limitations are documented in the [relationship audit](#relationship-audit).

- `FACT_CRUISE_ANALYTICS[REVIEW_DATE]`
  → `DIM_DATE[Full_Date]`

- `FACT_CRUISE_ANALYTICS[TRIP_ID]`
  → `DIM_CRUISE_TRIP[TRIP_ID]`

- `FACT_CRUISE_ANALYTICS[COMPANY_NAME]`
  → `DIM_CRUISE_LINE[COMPANY_NAME]`

- `FACT_CRUISE_ANALYTICS[SHIP_NAME]`
  → `DIM_CRUISE_SHIP[SHIP_NAME]`

- `FACT_CRUISE_ANALYTICS[DESTINATION_NAME]`
  → `DIM_DESTINATION[DESTINATION_NAME]`

All relationships are configured as **many-to-one**, with **single-direction filtering** from dimensions to the fact table.

![Power BI model relationships](PowerBIModelling/PowerBISchema.png)


### Dashboard 1

The first dashboard enables analysis of:

- Estimated Profit (approximated as 40% of Total Revenue).
- Total Revenue (Amount Spent) by Year (trend across 2019–2025).
- Estimated Cost (approximated as 60% of Total Revenue).
- Top Cruise Line (Cruise Line with the Highest Revenue).
- Total Deals by Year.
- Average Price Per Deal.
- Worst Cruise Line (Cruise Line with the Lowest Revenue).
- Estimated Profit by Cruise Line (comparison across companies).
- Estimated Profit by Trip Duration.
- Destination Overview (map visualization highlighting the most visited destination and enabling destination-based filtering).
- Most Visited Destination.

![Cruise analytics dashboard 1](PowerBIModelling/dashboard1.png)

### Dashboard 2

The second dashboard focuses on destination-level and contextual insights, allowing users to explore cruise performance alongside environmental and location-based factors. It highlights how revenue, profitability, and demand change across destinations and over time.

This dashboard enables analysis of:

- Estimated Profit (approximated as 40% of Total Revenue).
- Estimated Cost (approximated as 60% of Total Revenue).
- Total Amount Spent on Cruises by Year (2019–2025).
- Year Slicer
- Average Price per Deal.
- Best and Worst Cruise Lines by Revenue.
- Estimated Profit by Cruise Line.
- Average Travel Temperature (°C) by destination and year.
- Weather Impact indicator (Rain Impact classification).
- Destination overview using an interactive map visualization.
- Destination-based filtering that dynamically updates all KPIs and visuals.

Dashboard 2 complements Dashboard 1 by shifting the focus from overall financial trends to destination-aware analysis, helping users understand how location, climate conditions, and seasonal factors intersect with cruise demand and profitability.

![Cruise analytics dashboard 2](PowerBIModelling/dashboard2.png)


### Dashboard 3

The third dashboard provides a deeper analytical view of cruise performance by integrating financial trends, destination characteristics, customer ratings, and environmental conditions. It is designed to support multi-dimensional analysis across time, cruise lines, and destinations.

This dashboard enables analysis of:

- Total Amount Spent on Cruises by Year (2019–2025) to evaluate long-term revenue patterns.
- Average Temperature by Destination to analyze destination seasonality and climate influence.
- Cruise Ratings Over the Years to track changes in customer satisfaction over time.
- Estimated Profit by Cruise Line for comparative profitability analysis.
- Table of Environmental Conditions by Year, including Rain Impact and Sea Condition classifications.
- Year-based filtering to isolate specific periods for focused analysis.
- Interactive cross-filtering across all visuals to explore relationships between spending, destination climate, environmental factors, and customer ratings.

Dashboard 3 complements Dashboards 1 and 2 by extending the analysis beyond core financial KPIs into customer experience and environmental context, enabling more nuanced insights into factors influencing cruise demand and performance.


![Cruise analytics dashboard 3](PowerBIModelling/dashboard3.png)

---

## Developer setup

<details>
<summary>Packages, saved configuration, and manual setup</summary>

### Packages

The interface uses Streamlit and its built-in charts. pandas handles data preparation, DuckDB runs analytical SQL, and Pydantic validates analysis plans. Ollama uses its local HTTP API through httpx; the OpenAI provider uses the OpenAI Python SDK. See [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs) and [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses).

### Saved configuration

Ollama discovers installed local models directly and needs no secrets file. Cloud model shortcuts are excluded from the local model list.

For OpenAI, environment variables `OPENAI_API_KEY` and `OPENAI_MODEL` are supported. Alternatively, copy `AIAnalysis/.streamlit/secrets.example.toml` to `AIAnalysis/.streamlit/secrets.toml` and add your key there. The default OpenAI model is `gpt-4.1-mini`; a replacement must support Responses API structured outputs.

A key entered in the app overrides saved configuration; environment variables take precedence over the secrets file. `.env` files are not loaded automatically. Real secrets are ignored by Git.

### Manual setup

The launcher stores its Python environment outside the repository so paths containing a colon (`:`) work on macOS/Linux. To manage the environment yourself:

```bash
python3 -m venv /tmp/cruise-critic-ai-venv
source /tmp/cruise-critic-ai-venv/bin/activate
python -m pip install -r AIAnalysis/requirements.txt
cd AIAnalysis
python -m streamlit run app.py
```

Keep `AIAnalysis`, `FactTable`, and `DimensionTables` together when moving the project. The launcher starts Streamlit from `AIAnalysis` so local configuration is picked up correctly.

</details>

## Validation

With the Python environment activated, run from inside `AIAnalysis`:

```bash
python -m unittest discover -s tests -v
```

The automated suite covers numerical results, filters, empty results, invalid plans, data audits, simulated Ollama and OpenAI responses, connection failures, and the helper's example and question flows. It makes no real model requests or paid API calls.

Local checks with **qwen3:8b** also exercised price comparisons, a year-specific deal count, and responses to unavailable revenue and profit measures. These checks do not establish general model accuracy; a broader evaluation set remains planned.

## Project structure

| File or folder | Purpose |
| --- | --- |
| [AIAnalysis/run.py](AIAnalysis/run.py) | Prepares Python and starts the helper. |
| [AIAnalysis/app.py](AIAnalysis/app.py) | Streamlit interface for questions, examples, and results. |
| [AIAnalysis/cruise_ai/](AIAnalysis/cruise_ai/) | Data loading, AI interpretation, validation, and calculations. |
| [AIAnalysis/tests/](AIAnalysis/tests/) | Automated calculation and interface checks. |
| [FactTable/](FactTable/) | Exported cruise deal records. |
| [DimensionTables/](DimensionTables/) | Cruise lines, ships, trips, destinations, and dates. |
| [SQLQueries/](SQLQueries/) | Database schema, sample inserts, and queries. |
| [PowerBIModelling/](PowerBIModelling/) | Dashboard screenshots and analytical model diagrams. |
| [ClassProjectModelling/](ClassProjectModelling/) | Database design diagrams and schema model. |
| [ClassProjectReport/](ClassProjectReport/) | Original course project report. |

## Planned improvements

1. Evaluate AI interpretation against 30–50 questions with verified answers and measure accuracy and response time.
2. Reconcile trip references and expand the catalog before adding recommendations.
3. Add a suitable review-text dataset before attempting sentiment analysis.
4. Choose a Streamlit-compatible host for an online demo, with an appropriate model connection.

The helper currently runs locally. Hosting, broader model evaluation, recommendations, and sentiment analysis remain future work.
