"""The bounded analysis language shared by the app, model, and SQL compiler."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Filters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_year: int | None = Field(default=None, ge=1900, le=2100)
    end_year: int | None = Field(default=None, ge=1900, le=2100)
    cruise_lines: list[str] = Field(default_factory=list, max_length=20)
    destinations: list[str] = Field(default_factory=list, max_length=20)
    min_rating: float | None = Field(default=None, ge=0, le=5)
    max_price: float | None = Field(default=None, ge=0, le=1000000)
    min_duration: int | None = Field(default=None, ge=1, le=365)
    max_duration: int | None = Field(default=None, ge=1, le=365)

    @model_validator(mode="after")
    def check_ranges(self):
        if self.start_year is not None and self.end_year is not None:
            if self.start_year > self.end_year:
                raise ValueError("Start year must be on or before end year.")
        if self.min_duration is not None and self.max_duration is not None:
            if self.min_duration > self.max_duration:
                raise ValueError("Minimum duration must not exceed maximum duration.")
        return self


class QueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["analysis", "unsupported"] = "analysis"
    message: str = Field(default="", max_length=500)
    metric: Literal["avg_price", "avg_price_per_day", "avg_rating", "deal_count"]
    group_by: Literal["cruise_line", "destination", "year", "ship", "duration", "none"]
    sort_by: Literal["value", "group"] = "value"
    direction: Literal["asc", "desc"] = "desc"
    limit: int = Field(default=20, ge=1, le=20)
    filters: Filters = Field(default_factory=Filters)
