"""Load source CSVs, validate measures, and report relationship issues."""

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FACT_PATH = "FactTable/FACT_CRUISE_ANALYTICS.csv"


@dataclass
class Dataset:
    rows: pd.DataFrame
    audit: pd.DataFrame
    trips: pd.DataFrame

    def context(self) -> dict:
        """Only a schema summary and public category values go to the model."""
        return {
            "source": FACT_PATH,
            "records": len(self.rows),
            "observation_years": sorted(self.rows["year"].unique().tolist()),
            "cruise_lines": sorted(self.rows["company_name"].unique().tolist()),
            "destinations": sorted(self.rows["destination_name"].unique().tolist()),
            "ships": sorted(self.rows["ship_name"].unique().tolist()),
            "duration_days": sorted(self.rows["duration"].unique().tolist()),
            "currency": "Not specified in the exported data. Use price units.",
        }


def load_dataset(project_root: Path = PROJECT_ROOT) -> Dataset:
    facts = pd.read_csv(project_root / FACT_PATH)
    required = {
        "REVIEW_DATE", "TRIP_ID", "COMPANY_NAME", "SHIP_NAME",
        "DESTINATION_NAME", "DEAL_ID", "PRICE", "DURATION", "PRICE_PER_DAY", "RATING",
    }
    if missing := required - set(facts.columns):
        raise ValueError(f"Fact CSV is missing required columns: {', '.join(sorted(missing))}")
    if facts.empty or facts[list(required)].isna().any().any():
        raise ValueError("The fact CSV must contain complete deal records.")
    rows = facts.rename(columns=str.lower).copy()
    rows["observation_date"] = pd.to_datetime(rows.pop("review_date"), errors="raise")
    for col in ["price", "duration", "price_per_day", "rating", "trip_id", "deal_id"]:
        rows[col] = pd.to_numeric(rows[col], errors="raise")
    numeric = rows[["price", "duration", "price_per_day", "rating", "trip_id", "deal_id"]]
    if numeric.isin([float("inf"), float("-inf")]).any().any():
        raise ValueError("Measures and identifiers must be finite numbers.")
    if (rows["price"] <= 0).any() or (rows["duration"] <= 0).any():
        raise ValueError("Deal prices and durations must be positive.")
    for col in ["duration", "trip_id", "deal_id"]:
        if (rows[col] % 1 != 0).any():
            raise ValueError(f"{col} must contain whole numbers.")
        rows[col] = rows[col].astype("int64")
    if not rows["rating"].between(0, 5).all():
        raise ValueError("Ratings must fall between zero and five.")
    if rows["deal_id"].duplicated().any():
        raise ValueError("Deal identifiers must be unique at the exported fact grain.")
    for col in ["company_name", "ship_name", "destination_name"]:
        rows[col] = rows[col].astype(str).str.strip()
        if rows[col].eq("").any():
            raise ValueError(f"{col} cannot contain blank values.")
    derived_price = rows["price"] / rows["duration"]
    inconsistent_price = int(((rows["price_per_day"] - derived_price).abs() > 0.02).sum())
    rows["price_per_day"] = derived_price
    rows["year"] = rows["observation_date"].dt.year
    rows["source_row"] = range(2, len(rows) + 2)

    # These dimensions are audited, never used to fabricate a fact-to-trip join.
    trips = pd.read_csv(project_root / "DimensionTables/CRUISE_TRIP.csv")
    ships = pd.read_csv(project_root / "DimensionTables/CRUISE_SHIP.csv")
    destinations = pd.read_csv(project_root / "DimensionTables/DESTINATION.csv")
    lines = pd.read_csv(project_root / "DimensionTables/CRUISE_LINE.csv")
    dates = pd.read_csv(project_root / "DimensionTables/DIM_DATE.csv")
    if trips["TRIP_ID"].duplicated().any():
        raise ValueError("The trip dimension must have unique trip IDs.")
    unmatched = int((~rows["trip_id"].isin(trips["TRIP_ID"])).sum())
    trip_lookup = trips.set_index("TRIP_ID")
    matched = rows[rows["trip_id"].isin(trip_lookup.index)]
    conflicting = int((
        matched["ship_name"].ne(matched["trip_id"].map(trip_lookup["SHIP_NAME"]))
        | matched["company_name"].ne(matched["trip_id"].map(trip_lookup["COMPANY_NAME"]))
    ).sum())

    checks = [
        ("Complete fact records", 0, f"All {len(rows):,} records passed measure and identifier validation."),
        ("Trip IDs without a dimension match", unmatched,
         "Analytics use the fact export directly; missing trip metadata is not inferred."),
        ("Matched trip IDs with ship or line conflicts", conflicting,
         "The original fact and trip catalogs are retained separately."),
        ("Ship names without a dimension match", int((~rows["ship_name"].isin(ships["SHIP_NAME"])).sum()),
         "Checks fact ship names against the ship catalog."),
        ("Cruise lines without a dimension match", int((~rows["company_name"].isin(lines["COMPANY_NAME"])).sum()),
         "Checks fact cruise lines against the line catalog."),
        ("Destinations without a dimension match", int((~rows["destination_name"].isin(destinations["NAME"])).sum()),
         "Checks fact destinations against the destination catalog."),
        ("Observation dates without a dimension match",
         int((~rows["observation_date"].isin(pd.to_datetime(dates["FULL_DATE"]))).sum()),
         "The source REVIEW_DATE is an observation date, not a confirmed sailing or booking date."),
        ("Inconsistent exported price per day", inconsistent_price,
         "The app always calculates price per day as PRICE / DURATION using full precision."),
    ]
    audit = pd.DataFrame([
        {"Check": name, "Status": "Needs review" if count else "Passed",
         "Affected records": count, "Details": detail}
        for name, count, detail in checks
    ])
    return Dataset(rows=rows, audit=audit, trips=trips)
