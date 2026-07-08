from datetime import date
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import func, distinct
from sqlalchemy.orm import Session

from models.price import Price
from schemas.price import (
    CommoditySummary, LatestPrice, MarketSummary,
    PriceFilters, PriceListOut, PriceOut,
)


class PriceService:

    # ── Filtered list with pagination ─────────────────────────────────────────

    def list_prices(self, db: Session, filters: PriceFilters) -> PriceListOut:
        q = db.query(Price)

        if filters.commodity:
            q = q.filter(Price.commodity.ilike(f"%{filters.commodity}%"))
        if filters.market:
            q = q.filter(Price.market.ilike(f"%{filters.market}%"))
        if filters.source:
            q = q.filter(Price.source == filters.source)
        if filters.date_from:
            q = q.filter(Price.date >= filters.date_from)
        if filters.date_to:
            q = q.filter(Price.date <= filters.date_to)

        total = q.count()
        items = (
            q.order_by(Price.date.desc(), Price.commodity)
             .offset((filters.page - 1) * filters.size)
             .limit(filters.size)
             .all()
        )

        return PriceListOut(
            total=total,
            page=filters.page,
            size=filters.size,
            items=[PriceOut.model_validate(r) for r in items],
        )

    # ── Latest price per commodity × market ───────────────────────────────────

    def latest_prices(
        self,
        db: Session,
        commodity: Optional[str] = None,
        market: Optional[str] = None,
    ) -> List[LatestPrice]:
        """
        Returns the most recent price for each commodity/market combination.
        Uses a subquery to get the max date per group, then joins back.
        """
        subq = (
            db.query(
                Price.commodity,
                Price.market,
                func.max(Price.date).label("max_date"),
            )
            .group_by(Price.commodity, Price.market)
            .subquery()
        )

        q = (
            db.query(Price)
            .join(
                subq,
                (Price.commodity == subq.c.commodity)
                & (Price.market == subq.c.market)
                & (Price.date == subq.c.max_date),
            )
        )

        if commodity:
            q = q.filter(Price.commodity.ilike(f"%{commodity}%"))
        if market:
            q = q.filter(Price.market.ilike(f"%{market}%"))

        rows = q.order_by(Price.commodity, Price.market).all()
        return [
            LatestPrice(
                commodity=r.commodity,
                market=r.market,
                price=r.price,
                currency=r.currency,
                unit=r.unit,
                date=r.date,
                source=r.source,
            )
            for r in rows
        ]

    # ── Per-commodity summary stats ───────────────────────────────────────────

    def commodity_summary(self, db: Session) -> List[CommoditySummary]:
        rows = (
            db.query(
                Price.commodity,
                func.avg(Price.price).label("avg_price"),
                func.min(Price.price).label("min_price"),
                func.max(Price.price).label("max_price"),
                func.max(Price.date).label("latest_date"),
                func.count(Price.id).label("record_count"),
            )
            .group_by(Price.commodity)
            .order_by(Price.commodity)
            .all()
        )
        return [
            CommoditySummary(
                commodity=r.commodity,
                avg_price=round(Decimal(str(r.avg_price)), 2) if r.avg_price else None,
                min_price=r.min_price,
                max_price=r.max_price,
                latest_date=r.latest_date,
                record_count=r.record_count,
            )
            for r in rows
        ]

    # ── Per-market summary ────────────────────────────────────────────────────

    def market_summary(self, db: Session) -> List[MarketSummary]:
        rows = (
            db.query(
                Price.market,
                func.count(Price.id).label("record_count"),
            )
            .group_by(Price.market)
            .order_by(Price.market)
            .all()
        )
        summaries = []
        for r in rows:
            commodities = (
                db.query(distinct(Price.commodity))
                .filter(Price.market == r.market)
                .scalar_subquery()
            )
            # Fetch commodity names for this market
            commodity_list = [
                c[0]
                for c in db.query(distinct(Price.commodity))
                           .filter(Price.market == r.market)
                           .all()
            ]
            summaries.append(
                MarketSummary(
                    market=r.market,
                    record_count=r.record_count,
                    commodities=sorted(commodity_list),
                )
            )
        return summaries

    # ── Price trend for a commodity ───────────────────────────────────────────

    def price_trend(
        self,
        db: Session,
        commodity: str,
        market: Optional[str] = None,
        days: int = 90,
    ) -> List[PriceOut]:
        from datetime import timedelta
        cutoff = date.today() - timedelta(days=days)
        q = (
            db.query(Price)
            .filter(
                Price.commodity.ilike(f"%{commodity}%"),
                Price.date >= cutoff,
            )
            .order_by(Price.date.asc())
        )
        if market:
            q = q.filter(Price.market.ilike(f"%{market}%"))
        return [PriceOut.model_validate(r) for r in q.all()]


# ── Singleton ─────────────────────────────────────────────────────────────────
price_service = PriceService()
