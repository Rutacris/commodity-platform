from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ── Shared ────────────────────────────────────────────────────────────────────

class PriceBase(BaseModel):
    commodity: str
    market:    str
    price:     Decimal
    currency:  str  = "RWF"
    unit:      str  = "kg"
    date:      date
    source:    Optional[str] = None


# ── Response ──────────────────────────────────────────────────────────────────

class PriceOut(PriceBase):
    id:         int
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class PriceListOut(BaseModel):
    total:  int
    page:   int
    size:   int
    items:  List[PriceOut]


# ── Filters (query params) ────────────────────────────────────────────────────

class PriceFilters(BaseModel):
    commodity:  Optional[str]  = Field(None, description="Filter by commodity name")
    market:     Optional[str]  = Field(None, description="Filter by market name")
    source:     Optional[str]  = Field(None, description="Filter by data source")
    date_from:  Optional[date] = Field(None, description="Start date (inclusive)")
    date_to:    Optional[date] = Field(None, description="End date (inclusive)")
    page:       int            = Field(1,    ge=1, description="Page number")
    size:       int            = Field(50,   ge=1, le=500, description="Page size")


# ── Summary / analytics ───────────────────────────────────────────────────────

class CommoditySummary(BaseModel):
    commodity:  str
    avg_price:  Optional[Decimal]
    min_price:  Optional[Decimal]
    max_price:  Optional[Decimal]
    latest_date: Optional[date]
    record_count: int


class MarketSummary(BaseModel):
    market:      str
    record_count: int
    commodities: List[str]


class LatestPrice(BaseModel):
    commodity: str
    market:    str
    price:     Decimal
    currency:  str
    unit:      str
    date:      date
    source:    Optional[str] = None


# ── AI insight ────────────────────────────────────────────────────────────────

class InsightRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=5,
        max_length=500,
        description="Natural language question about commodity prices",
        examples=["Which market has the cheapest maize this month?"],
    )
    commodity: Optional[str] = Field(
        None, description="Scope question to this commodity"
    )


class InsightResponse(BaseModel):
    question: str
    answer:   str
    model:    str
