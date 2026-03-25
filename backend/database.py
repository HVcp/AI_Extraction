"""
database.py — SQLAlchemy setup + ORM model for extracted records.

Why SQLite for POC: zero-config, file-based, same SQLAlchemy API as Azure SQL.
Production swap: change DATABASE_URL to mssql+pyodbc://... — rest stays identical.
"""

import json
from datetime import datetime, timezone

from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Float
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session

from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./poc_extraction.db")

# connect_args only needed for SQLite (thread safety)
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


class ExtractionRecord(Base):
    """
    One row per uploaded document.
    extracted_json stores the full DailyReportExtracted as JSON string.
    This is intentional — avoids premature schema normalisation in POC phase.
    Production: split workers into a separate table for querying headcount.
    """
    __tablename__ = "extraction_records"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    file_type = Column(String(20), nullable=False)       # pdf | image | excel
    status = Column(String(20), nullable=False)          # success | needs_review | failed

    # Top-level fields duplicated for fast list queries (avoids JSON parse on list page)
    contractor_name = Column(String(255))
    document_date = Column(String(20))
    total_manpower = Column(Integer)

    # Full extracted payload
    extracted_json = Column(Text, nullable=False)
    raw_di_markdown = Column(Text)                       # raw Azure DI output (debug)

    processing_time_seconds = Column(Float)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


def get_db():
    """FastAPI dependency — yields a DB session, closes it after request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables. Called once at app startup."""
    Base.metadata.create_all(bind=engine)


def save_record(
    db: Session,
    filename: str,
    file_type: str,
    status: str,
    extracted_dict: dict,
    raw_di_markdown: str | None,
    processing_time: float,
) -> ExtractionRecord:
    """Persist one extraction result and return the saved ORM object."""
    record = ExtractionRecord(
        filename=filename,
        file_type=file_type,
        status=status,
        contractor_name=extracted_dict.get("contractor_name"),
        document_date=extracted_dict.get("document_date"),
        total_manpower=extracted_dict.get("total_manpower"),
        extracted_json=json.dumps(extracted_dict),
        raw_di_markdown=raw_di_markdown,
        processing_time_seconds=processing_time,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record