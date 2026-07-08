from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from db.session import get_db
from schemas.price import (
    CommoditySummary, LatestPrice, MarketSummary,
    PriceFilters, PriceListOut, PriceOut,
)
from services.price_service import price_service

router = APIRouter(prefix="/prices", tags=["Prices"])


@router.get("", response_model=PriceListOut, summary="List prices with filters")
def list_prices(
    commodity: Optional[str] = Query(None, description="Filter by commodity (partial match)"),
    market:    Optional[str] = Query(None, description="Filter by market (partial match)"),
    source:    Optional[str] = Query(None, description="Filter by source"),
    date_from: Optional[str] = Query(None, description="Start date YYYY-MM-DD"),
    date_to:   Optional[str] = Query(None, description="End date YYYY-MM-DD"),
    page:      int           = Query(1,   ge=1),
    size:      int           = Query(50,  ge=1, le=500),
    db: Session = Depends(get_db),
):
    from datetime import date as Date
    filters = PriceFilters(
        commodity=commodity,
        market=market,
        source=source,
        date_from=Date.fromisoformat(date_from) if date_from else None,
        date_to=Date.fromisoformat(date_to)     if date_to   else None,
        page=page,
        size=size,
    )
    return price_service.list_prices(db, filters)


@router.get("/latest", response_model=List[LatestPrice],
            summary="Latest price per commodity × market")
def latest_prices(
    commodity: Optional[str] = Query(None),
    market:    Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    return price_service.latest_prices(db, commodity=commodity, market=market)


@router.get("/summary/commodities", response_model=List[CommoditySummary],
            summary="Avg / min / max per commodity")
def commodity_summary(db: Session = Depends(get_db)):
    return price_service.commodity_summary(db)


@router.get("/summary/markets", response_model=List[MarketSummary],
            summary="Record counts and commodities per market")
def market_summary(db: Session = Depends(get_db)):
    return price_service.market_summary(db)


@router.get("/trend/{commodity}", response_model=List[PriceOut],
            summary="Price history for a commodity over N days")
def price_trend(
    commodity: str,
    market: Optional[str] = Query(None, description="Scope to a specific market"),
    days:   int           = Query(90, ge=7, le=365, description="Lookback window"),
    db: Session = Depends(get_db),
):
    return price_service.price_trend(db, commodity, market=market, days=days)
