from typing import List, Optional

import requests
from sqlalchemy.orm import Session

from core.config import get_settings
from models.price import Price
from schemas.price import InsightRequest, InsightResponse

settings = get_settings()

_SYSTEM = """
You are an agricultural market analyst for Rwanda.
You have access to recent commodity price data for: Maize, Beans, Rice, Cooking Oil, Sugar.
Answer the user's question clearly and concisely in 2-4 sentences.
Base your answer only on the data provided. Do not speculate.
If the data is insufficient, say so.
"""


class OllamaService:

    def answer_insight(
        self, db: Session, request: InsightRequest
    ) -> InsightResponse:
        context = self._build_context(db, request.commodity)
        prompt = (
            f"Price data:\n{context}\n\n"
            f"Question: {request.question}"
        )

        answer = self._call_ollama(prompt)
        return InsightResponse(
            question=request.question,
            answer=answer,
            model=settings.OLLAMA_MODEL,
        )

    # ── Build data context from DB ────────────────────────────────────────────

    def _build_context(self, db: Session, commodity: Optional[str]) -> str:
        """
        Pull the most recent 30 price records and format them as a
        compact markdown table for the model context window.
        """
        from sqlalchemy import func
        from models.price import Price

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

        rows = q.order_by(Price.commodity, Price.market).limit(30).all()

        if not rows:
            return "No price data available."

        lines = ["Commodity | Market | Price (RWF) | Unit | Date"]
        lines.append("--------- | ------ | ----------- | ---- | ----")
        for r in rows:
            lines.append(
                f"{r.commodity} | {r.market} | {r.price} | {r.unit} | {r.date}"
            )
        return "\n".join(lines)

    # ── Ollama API call ───────────────────────────────────────────────────────

    def _call_ollama(self, prompt: str) -> str:
        try:
            resp = requests.post(
                f"{settings.OLLAMA_HOST}/api/generate",
                json={
                    "model":  settings.OLLAMA_MODEL,
                    "system": _SYSTEM,
                    "prompt": prompt,
                    "stream": False,
                },
                timeout=120,
            )
            resp.raise_for_status()
            return resp.json().get("response", "No response from model.").strip()
        except requests.exceptions.ConnectionError:
            return (
                "AI service unavailable — Ollama is not running or unreachable. "
                "Check that Ollama is running on the host machine."
            )
        except Exception as e:
            return f"Error calling AI model: {e}"


ollama_service = OllamaService()
