from datetime import date, datetime

from sqlalchemy import (
    Column, Date, DateTime, Index, Integer,
    Numeric, String, Text, UniqueConstraint, func,
)

from db.session import Base


class Price(Base):
    __tablename__ = "prices"

    id         = Column(Integer, primary_key=True, index=True)
    commodity  = Column(String(50),  nullable=False, index=True)
    market     = Column(String(100), nullable=False, index=True)
    price      = Column(Numeric,     nullable=False)
    currency   = Column(String(10),  nullable=False, default="RWF")
    unit       = Column(String(20),  nullable=False, default="kg")
    date       = Column(Date,        nullable=False, index=True)
    source     = Column(Text)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("commodity", "market", "date", "source",
                         name="uq_price_commodity_market_date_source"),
        Index("idx_prices_date_desc", "date"),
    )

    def __repr__(self) -> str:
        return (
            f"<Price id={self.id} commodity={self.commodity!r} "
            f"market={self.market!r} price={self.price} date={self.date}>"
        )
