"""
main.py — FastAPI application.

Endpoints:
  POST /extract          Upload a document → extract → save → return result
  GET  /records          List all extracted records (paginated)
  GET  /records/{id}     Full record detail with raw DI markdown
  DELETE /records/{id}   Delete a record
  GET  /health           Health check (verifies Azure connectivity)

Design decisions:
- Async FastAPI but sync Azure SDK calls (azure-ai-documentintelligence is sync)
  → use run_in_executor to avoid blocking the event loop in production
- Files are NOT stored on disk — processed in memory, only JSON saved to DB
  → no blob storage needed for POC (add Azure Blob in production)
"""

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager   # FIX 1: was asyncio_contextmanager (typo)
from datetime import datetime, timezone
from functools import partial
from typing import Optional

import uvicorn
from fastapi import FastAPI, File, UploadFile, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from backend.database import get_db, init_db, save_record, ExtractionRecord
from backend.extractor import extract_document
from backend.models import ExtractionResponse, RecordListItem, RecordDetail, DailyReportExtracted

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".xlsx", ".xls"}


# ─── App lifecycle ────────────────────────────────────────────────────────────

@asynccontextmanager                         # FIX 1: correct import
async def lifespan(app: FastAPI):
    logger.info("Starting up — initialising database")
    init_db()
    yield
    logger.info("Shutting down")


app = FastAPI(
    title="WT Daily Report Extraction POC",
    description="AI-powered extraction from construction site daily reports",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501"],   # Streamlit dev origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _determine_status(extracted: DailyReportExtracted) -> str:
    """
    success      → clean extraction, all key fields present
    needs_review → low-confidence fields flagged or key fields missing
    """
    key_fields_missing = not extracted.contractor_name or not extracted.document_date
    has_flags = len(extracted.low_confidence_fields) > 0
    if key_fields_missing or has_flags:
        return "needs_review"
    return "success"


def _record_to_response(record: ExtractionRecord) -> ExtractionResponse:
    extracted_dict = json.loads(record.extracted_json)
    return ExtractionResponse(
        record_id=record.id,
        filename=record.filename,
        file_type=record.file_type,
        status=record.status,
        extracted=DailyReportExtracted(**extracted_dict),
        created_at=record.created_at,
        processing_time_seconds=record.processing_time_seconds or 0,
    )


# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.post("/extract", response_model=ExtractionResponse, status_code=201)
async def extract_endpoint(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Upload a daily report (PDF, image, or Excel) and extract structured data.
    Returns the extraction result immediately — no polling needed for POC.
    """
    from pathlib import Path

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{suffix}'. Allowed: {ALLOWED_EXTENSIONS}",
        )

    file_bytes = await file.read()
    if len(file_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    logger.info(f"Processing: {file.filename} ({len(file_bytes):,} bytes)")
    start = time.perf_counter()

    try:
        # FIX 2: Azure DI SDK is fully synchronous (DocumentIntelligenceClient, NOT
        # AsyncDocumentIntelligenceClient). Never await its methods.
        # Wrapping in run_in_executor keeps the async event loop unblocked while
        # the sync DI + OpenAI calls run in a threadpool thread.
        loop = asyncio.get_event_loop()
        extracted, file_type, raw_markdown = await loop.run_in_executor(
            None,
            partial(extract_document, file_bytes, file.filename),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"Extraction failed for {file.filename}")
        raise HTTPException(status_code=500, detail=f"Extraction error: {str(e)}")

    elapsed = time.perf_counter() - start
    status = _determine_status(extracted)

    record = save_record(
        db=db,
        filename=file.filename,
        file_type=file_type,
        status=status,
        extracted_dict=extracted.model_dump(),
        raw_di_markdown=raw_markdown,
        processing_time=elapsed,
    )

    logger.info(f"Saved record {record.id} | status={status} | {elapsed:.1f}s")
    return _record_to_response(record)


@app.get("/records", response_model=list[RecordListItem])
def list_records(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    status: Optional[str] = Query(None, description="Filter: success | needs_review | failed"),
    db: Session = Depends(get_db),
):
    """List extracted records, newest first."""
    query = db.query(ExtractionRecord).order_by(ExtractionRecord.created_at.desc())
    if status:
        query = query.filter(ExtractionRecord.status == status)
    records = query.offset(skip).limit(limit).all()

    return [
        RecordListItem(
            record_id=r.id,
            filename=r.filename,
            file_type=r.file_type,
            status=r.status,
            contractor_name=r.contractor_name,
            document_date=r.document_date,
            total_manpower=r.total_manpower,
            created_at=r.created_at,
        )
        for r in records
    ]


@app.get("/records/{record_id}", response_model=RecordDetail)
def get_record(record_id: int, db: Session = Depends(get_db)):
    """Full detail for one record, including raw DI markdown for debugging."""
    record = db.query(ExtractionRecord).filter(ExtractionRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail=f"Record {record_id} not found")

    extracted_dict = json.loads(record.extracted_json)
    return RecordDetail(
        record_id=record.id,
        filename=record.filename,
        file_type=record.file_type,
        status=record.status,
        extracted=DailyReportExtracted(**extracted_dict),
        created_at=record.created_at,
        processing_time_seconds=record.processing_time_seconds or 0,
        raw_di_markdown=record.raw_di_markdown,
    )


@app.delete("/records/{record_id}", status_code=204)
def delete_record(record_id: int, db: Session = Depends(get_db)):
    record = db.query(ExtractionRecord).filter(ExtractionRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail=f"Record {record_id} not found")
    db.delete(record)
    db.commit()


@app.get("/health")
def health_check():
    """
    Lightweight check — verifies env vars are set.
    Does NOT make Azure API calls (avoids cost on health checks).
    """
    import os
    missing = [
        k for k in [
            "AZURE_DOC_INTELLIGENCE_ENDPOINT", "AZURE_DOC_INTELLIGENCE_KEY",
            "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_KEY", "AZURE_OPENAI_DEPLOYMENT"
        ]
        if not os.getenv(k)
    ]
    if missing:
        raise HTTPException(status_code=503, detail=f"Missing env vars: {missing}")
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    