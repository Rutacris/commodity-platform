from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db.session import get_db
from schemas.price import InsightRequest, InsightResponse
from services.ollama_service import ollama_service

router = APIRouter(prefix="/insights", tags=["AI Insights"])


@router.post("", response_model=InsightResponse,
             summary="Ask a natural language question about commodity prices")
def get_insight(
    request: InsightRequest,
    db: Session = Depends(get_db),
):
    """
    Ask the local Mistral model a question about current prices.
    The model is given the latest prices as context automatically.

    Example questions:
    - "Which market has the cheapest maize right now?"
    - "How does the price of beans compare across markets?"
    - "What is the average sugar price in Kigali?"
    """
    return ollama_service.answer_insight(db, request)
