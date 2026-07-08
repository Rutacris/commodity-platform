from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from db.session import get_db
from services.data_ingestion_service import DataIngestionService

router = APIRouter(prefix="/ingest", tags=["Data Ingestion"])


@router.get("/", summary="Render ingestion form")
def ingestion_form():
    return {
        "message": "Use the HTML form at /ingest/ui or POST to /ingest/file, /ingest/text, or /ingest/url",
    }


@router.post("/file", summary="Upload CSV, Excel, or text file")
def ingest_file(
    file: UploadFile = File(...),
    source: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="A filename is required")

    content = file.file.read()
    records = DataIngestionService.parse_records_from_bytes(file.filename, content, source_label=source or "uploaded")
    result = DataIngestionService.ingest_records(db, records, source_label=source or "uploaded")
    return {"source": "file", "filename": file.filename, **result}


@router.post("/text", summary="Ingest from pasted text")
def ingest_text(
    text: str = Form(...),
    source: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    records = DataIngestionService.parse_records_from_text(text, source_label=source or "manual")
    result = DataIngestionService.ingest_records(db, records, source_label=source or "manual")
    return {"source": "text", **result}


@router.post("/url", summary="Ingest from a remote CSV or Excel file")
def ingest_url(
    url: str = Form(...),
    source: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    records = DataIngestionService.parse_records_from_url(url, source_label=source or "url")
    result = DataIngestionService.ingest_records(db, records, source_label=source or "url")
    return {"source": "url", "url": url, **result}
