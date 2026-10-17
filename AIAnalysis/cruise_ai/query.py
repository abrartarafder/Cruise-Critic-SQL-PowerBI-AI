"""Compile validated plans into parameterized, application-owned SELECTs."""

from dataclasses import dataclass

import duckdb
import pandas as pd

from .data import Dataset
from .models import Filters, QueryPlan

METRICS = {
    "avg_price": ("AVG(price)", "Average deal price", "price units"),
    "avg_price_per_day": ("AVG(price_per_day)", "Average price per day", "price units/day"),
    "avg_rating": ("AVG(rating)", "Average rating", "out of 5"),
    "deal_count": ("COUNT(*)", "Deal records", "records"),
}
GROUPS = {
    "cruise_line": "company_name", "destination": "destination_name",
    "year": "year", "ship": "ship_name", "duration": "duration",
}
GROUP_LABELS = {
    "cruise_line": "Cruise line", "destination": "Destination", "year": "Observation year",
    "ship": "Ship", "duration": "Duration (days)", "none": "All matching records",
}


@dataclass
class QueryResult:
    plan: QueryPlan
    table: pd.DataFrame
    source_rows: pd.DataFrame
    sql: str
    parameters: list
    scope: Filters

    @property
    def matched_records(self) -> int:
        return len(self.source_rows)


def validate_categories(filters: Filters, dataset: Dataset) -> None:
    for values, column in [
        (filters.cruise_lines, "company_name"),
        (filters.destinations, "destination_name"),
    ]:
        unknown = set(values) - set(dataset.rows[column])
        if unknown:
            raise ValueError(f"No matching {column.replace('_', ' ')} in this dataset: {', '.join(sorted(unknown))}")


def compile_filters(filters: Filters) -> tuple[list[str], list]:
    clauses, params = [], []
    for column, operator, value in [
        ("year", ">=", filters.start_year), ("year", "<=", filters.end_year),
        ("rating", ">=", filters.min_rating), ("price", "<=", filters.max_price),
        ("duration", ">=", filters.min_duration), ("duration", "<=", filters.max_duration),
    ]:
        if value is not None:
            clauses.append(f"{column} {operator} ?")
            params.append(value)
    for column, values in [
        ("company_name", filters.cruise_lines), ("destination_name", filters.destinations),
    ]:
        if values:
            clauses.append(f"{column} IN ({', '.join('?' for _ in values)})")
            params.extend(values)
    return clauses, params


def filter_rows(dataset: Dataset, scope: Filters) -> pd.DataFrame:
    validate_categories(scope, dataset)
    clauses, params = compile_filters(scope)
    where = " AND ".join(clauses) or "TRUE"
    with duckdb.connect(":memory:") as connection:
        connection.register("deals", dataset.rows)
        return connection.execute(f"SELECT * FROM deals WHERE {where}", params).df()


def execute_plan(dataset: Dataset, plan: QueryPlan, scope: Filters | None = None) -> QueryResult:
    # Revalidate at this boundary even when called from outside the UI.
    plan = QueryPlan.model_validate(plan.model_dump())
    scope = Filters.model_validate((scope or Filters()).model_dump())
    if plan.kind != "analysis":
        raise ValueError("This question cannot be answered with the available measures.")
    validate_categories(plan.filters, dataset)
    validate_categories(scope, dataset)
    clauses, parameters = [], []
    for filters in [scope, plan.filters]:
        part_clauses, part_params = compile_filters(filters)
        clauses.extend(part_clauses)
        parameters.extend(part_params)
    where = " AND ".join(clauses) or "TRUE"
    measure = METRICS[plan.metric][0]
    if plan.group_by == "none":
        group = "'All matching records'"
        grouping = ""
    else:
        group = GROUPS[plan.group_by]
        grouping = f"\nGROUP BY {group}"
    sort = '"group"' if plan.sort_by == "group" else "value"
    direction = "ASC" if plan.direction == "asc" else "DESC"
    sql = (
        f'SELECT {group} AS "group",\n       {measure} AS value,\n       COUNT(*) AS records'
        f"\nFROM deals\nWHERE {where}{grouping}"
        f'\nORDER BY {sort} {direction}, "group" ASC\nLIMIT ?'
    )
    with duckdb.connect(":memory:") as connection:
        connection.register("deals", dataset.rows)
        source_rows = connection.execute(f"SELECT * FROM deals WHERE {where}", parameters).df()
        table = connection.execute(sql, [*parameters, plan.limit]).df()
    # An aggregate over zero rows produces a null row in SQL; present it as no result.
    if source_rows.empty:
        table = table.iloc[:0]
    return QueryResult(plan, table, source_rows, sql, [*parameters, plan.limit], scope)


def summarize(result: QueryResult) -> str:
    if result.table.empty:
        return "No deal records match this question and the active filters. Try widening the year range or removing a filter."
    plan, table = result.plan, result.table
    _, metric_label, unit = METRICS[plan.metric]

    def display(value):
        return f"{int(value):,}" if plan.metric == "deal_count" else f"{value:,.2f}"

    coverage = f"Based on {result.matched_records:,} matching deal records."
    if plan.group_by == "none":
        return f"{metric_label}: **{display(table.iloc[0]['value'])} {unit}**. {coverage}"
    if plan.group_by == "year" and plan.sort_by == "group" and len(table) > 1:
        ordered = table.sort_values("group")
        first, last = ordered.iloc[0], ordered.iloc[-1]
        return (
            f"{metric_label} was **{display(first['value'])} {unit} in {int(first['group'])}** "
            f"and **{display(last['value'])} {unit} in {int(last['group'])}**. {coverage} "
            "Years refer to the exported review/observation date."
        )
    first = table.iloc[0]
    rank = "lowest" if plan.direction == "asc" else "highest"
    if plan.sort_by != "value":
        return f"Showing {metric_label.lower()} by {GROUP_LABELS[plan.group_by].lower()}. {coverage}"
    group_label = str(first["group"])
    if plan.group_by in ["year", "duration"]:
        group_label = str(int(first["group"]))
    if plan.group_by == "duration":
        group_label += " days"
    tied = int(table["value"].eq(first["value"]).sum()) > 1
    lead = f"{group_label} is tied for the {rank}" if tied else f"{group_label} has the {rank}"
    return (
        f"**{lead} {metric_label.lower()}**: **{display(first['value'])} {unit}** "
        f"across {int(first['records']):,} records in that group. {coverage}"
    )
