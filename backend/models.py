"""
models.py — Canonical schemas for construction daily report extraction.

Why here: Single source of truth for the data shape.
           FastAPI uses these for request/response validation.
           Extractor uses these to instruct GPT-4o on what to return.
           DB models mirror these for storage.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


# ─── Nested structures ────────────────────────────────────────────────────────

class WorkerEntry(BaseModel):
    """One row from the worker/manpower table."""
    classification: Optional[str] = Field(None, description="e.g. Foreman, Laborer, Electrician")
    name: Optional[str] = Field(None, description="Worker name if listed individually")
    count: Optional[int] = Field(None, description="Number of workers in this classification")
    hours: Optional[float] = Field(None, description="Hours worked (S=straight, OT=1.5x, DT=2x combined)")


class EquipmentEntry(BaseModel):
    description: Optional[str] = None
    hours: Optional[float] = None


# ─── Core extraction result ───────────────────────────────────────────────────

class DailyReportExtracted(BaseModel):
    """
    Canonical schema — maps ALL vendor form variations to this shape.
    Fields are Optional because different forms omit different sections.
    """
    # Header
    document_date: Optional[str] = Field(None, description="Date of report in YYYY-MM-DD")
    wt_job_number: Optional[str] = Field(None, description="Whiting-Turner job number")
    project_name: Optional[str] = None
    project_location: Optional[str] = None

    # Contractor
    contractor_name: Optional[str] = None
    supervisor_name: Optional[str] = Field(None, description="Foreman, superintendent, or rep name")

    # Conditions
    weather: Optional[str] = None
    temperature: Optional[str] = None

    # Manpower
    total_manpower: Optional[int] = Field(None, description="Total headcount on site")
    workers: list[WorkerEntry] = Field(default_factory=list)

    # Work
    work_description: Optional[str] = Field(None, description="Description of work performed")
    areas_locations: Optional[str] = Field(None, description="Work areas or floor locations mentioned")

    # Equipment
    equipment_utilized: list[EquipmentEntry] = Field(default_factory=list)
    equipment_idle: list[EquipmentEntry] = Field(default_factory=list)

    # Safety
    accidents_occurred: Optional[bool] = None
    open_issues: Optional[bool] = None
    safety_notes: Optional[str] = None

    # Quality flags — populated by extractor, not by LLM
    low_confidence_fields: list[str] = Field(
        default_factory=list,
        description="Field names where Azure DI confidence was below threshold"
    )
    extraction_notes: Optional[str] = Field(
        None, description="Any ambiguities or warnings from the extraction"
    )


# ─── API request/response ─────────────────────────────────────────────────────

class ExtractionResponse(BaseModel):
    """What the API returns after processing a document."""
    record_id: int
    filename: str
    file_type: str
    status: str                         # "success" | "needs_review" | "failed"
    extracted: DailyReportExtracted
    created_at: datetime
    processing_time_seconds: float


class RecordListItem(BaseModel):
    record_id: int
    filename: str
    file_type: str
    status: str
    contractor_name: Optional[str]
    document_date: Optional[str]
    total_manpower: Optional[int]
    created_at: datetime


class RecordDetail(ExtractionResponse):
    """Full record with raw DI output for debugging."""
    raw_di_markdown: Optional[str] = None