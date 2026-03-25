"""
extractor.py — The core extraction pipeline.

⚠️  THIS MODULE IS INTENTIONALLY SYNCHRONOUS.
    azure-ai-documentintelligence and openai SDKs used here are the SYNC variants.
    Do NOT import AsyncDocumentIntelligenceClient or use AsyncAzureOpenAI here.
    The FastAPI endpoint wraps calls via asyncio.run_in_executor — that's the
    correct pattern for running sync blocking IO in an async FastAPI app.

Stage 1: Azure Document Intelligence (prebuilt-layout)
         → OCR + table structure + markdown output + confidence scores
         → Handles: PDF (scanned/digital), images (JPG/PNG), Office files

Stage 2: Azure OpenAI GPT-4o
         → Receives DI markdown + confidence map
         → Maps variable vendor formats → canonical DailyReportExtracted JSON
         → No hallucination risk on structure (DI grounded it first)

Stage 3: Confidence flagging
         → Fields sourced from low-confidence DI regions are tagged
         → These drive the "needs_review" status and UI highlight

For Excel files: skip DI entirely, use openpyxl — AI is not needed.
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

import pandas as pd
from azure.ai.documentintelligence import DocumentIntelligenceClient   # SYNC client — never use AsyncDocumentIntelligenceClient here
from azure.ai.documentintelligence.models import DocumentContentFormat
from azure.core.credentials import AzureKeyCredential
from dotenv import load_dotenv
from openai import AzureOpenAI

from backend.models import DailyReportExtracted, WorkerEntry, EquipmentEntry

# Anchor .env to project root regardless of what directory uvicorn launches from
_ROOT = Path(__file__).parent.parent
load_dotenv(dotenv_path=_ROOT / ".env")

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.80"))


def _require(key: str) -> str:
    """Get required env var — raises clear ValueError instead of cryptic KeyError."""
    val = os.getenv(key)
    if not val:
        raise ValueError(f"Missing or empty env var: '{key}' — check your .env file")
    return val


# ─── Client setup ─────────────────────────────────────────────────────────────

def _get_di_client() -> DocumentIntelligenceClient:
    return DocumentIntelligenceClient(
        endpoint=_require("AZURE_DOC_INTELLIGENCE_ENDPOINT"),
        credential=AzureKeyCredential(_require("AZURE_DOC_INTELLIGENCE_KEY")),
    )


def _get_openai_client() -> AzureOpenAI:
    return AzureOpenAI(
        azure_endpoint=_require("AZURE_OPENAI_ENDPOINT"),
        api_key=_require("AZURE_OPENAI_KEY"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
    )


# ─── Stage 1: Azure Document Intelligence ────────────────────────────────────

def run_document_intelligence(file_bytes: bytes, content_type: str) -> tuple[str, list[str]]:
    """
    Run Azure DI prebuilt-layout on the document bytes.

    Returns:
        markdown_content: Full document as markdown (tables preserved as markdown tables)
        low_confidence_words: List of words with confidence below threshold
    """
    client = _get_di_client()

    # Pass raw bytes directly as body + content_type = SDK sends multipart/binary.
    # DO NOT combine AnalyzeDocumentRequest(bytes_source=...) with content_type kwarg —
    # bytes_source wraps bytes in a JSON+base64 body (Content-Type: application/json),
    # but passing content_type="image/png" overrides the header → Azure gets a JSON body
    # with an image/png header and rejects it as corrupted/unsupported format.
    poller = client.begin_analyze_document(
        model_id="prebuilt-layout",
        body=file_bytes,                              # raw bytes — SDK sets correct header
        content_type=content_type,                    # image/png | application/pdf | etc.
        output_content_format=DocumentContentFormat.MARKDOWN,
    )

    result = poller.result()

    markdown_content = result.content or ""

    # Collect words below confidence threshold for flagging
    low_confidence_words: list[str] = []
    if result.pages:
        for page in result.pages:
            if page.words:
                for word in page.words:
                    if word.confidence is not None and word.confidence < CONFIDENCE_THRESHOLD:
                        low_confidence_words.append(word.content)

    logger.info(
        f"DI complete: {len(markdown_content)} chars, "
        f"{len(low_confidence_words)} low-confidence words"
    )
    return markdown_content, low_confidence_words


# ─── Stage 2: GPT-4o semantic mapping ────────────────────────────────────────

_SYSTEM_PROMPT = """You are a data extraction assistant for construction site daily reports.
You receive the text content of a daily work report (already OCR'd) and must extract structured data.

Rules:
1. Extract ONLY what is explicitly present in the document. Do not infer or guess.
2. For missing fields, use null — never fabricate values.
3. For worker tables: each DISTINCT classification gets its own entry in the workers array.
4. Dates must be in YYYY-MM-DD format. If year is ambiguous, use context clues.
5. total_manpower = sum of all worker counts if not explicitly stated.
6. Return ONLY valid JSON matching the schema. No preamble, no markdown fences.

Output JSON schema:
{
  "document_date": "YYYY-MM-DD or null",
  "wt_job_number": "string or null",
  "project_name": "string or null",
  "project_location": "string or null",
  "contractor_name": "string or null",
  "supervisor_name": "string or null",
  "weather": "string or null",
  "temperature": "string or null",
  "total_manpower": integer_or_null,
  "workers": [
    {"classification": "string", "name": "string or null", "count": integer_or_null, "hours": float_or_null}
  ],
  "work_description": "string or null",
  "areas_locations": "string or null",
  "equipment_utilized": [{"description": "string", "hours": float_or_null}],
  "equipment_idle": [{"description": "string", "hours": float_or_null}],
  "accidents_occurred": true_false_or_null,
  "open_issues": true_false_or_null,
  "safety_notes": "string or null",
  "extraction_notes": "any ambiguities you noticed, or null"
}"""


def run_llm_mapping(
    markdown_content: str,
    low_confidence_words: list[str],
) -> tuple[DailyReportExtracted, list[str]]:
    """
    Send DI markdown to GPT-4o and parse structured output.

    Returns:
        extracted: DailyReportExtracted instance
        flagged_fields: Field names that mention low-confidence words
    """
    client = _get_openai_client()
    deployment = _require("AZURE_OPENAI_DEPLOYMENT")

    # Build context note about low-confidence regions
    confidence_note = ""
    if low_confidence_words:
        sample = low_confidence_words[:20]  # cap to avoid token waste
        confidence_note = (
            f"\n\nNote: The following words were low-confidence in OCR and may be "
            f"misread: {', '.join(sample)}. Flag any fields containing these words "
            f"in extraction_notes."
        )

    user_message = f"Extract structured data from this daily report:\n\n{markdown_content}{confidence_note}"

    response = client.chat.completions.create(
        model=deployment,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=0,          # deterministic extraction
        max_tokens=2000,
        response_format={"type": "json_object"},
    )

    raw_json = response.choices[0].message.content
    data = json.loads(raw_json)

    # Parse into Pydantic model — validates types and fills defaults
    extracted = DailyReportExtracted(
        document_date=data.get("document_date"),
        wt_job_number=data.get("wt_job_number"),
        project_name=data.get("project_name"),
        project_location=data.get("project_location"),
        contractor_name=data.get("contractor_name"),
        supervisor_name=data.get("supervisor_name"),
        weather=data.get("weather"),
        temperature=data.get("temperature"),
        total_manpower=data.get("total_manpower"),
        workers=[WorkerEntry(**w) for w in (data.get("workers") or [])],
        work_description=data.get("work_description"),
        areas_locations=data.get("areas_locations"),
        equipment_utilized=[EquipmentEntry(**e) for e in (data.get("equipment_utilized") or [])],
        equipment_idle=[EquipmentEntry(**e) for e in (data.get("equipment_idle") or [])],
        accidents_occurred=data.get("accidents_occurred"),
        open_issues=data.get("open_issues"),
        safety_notes=data.get("safety_notes"),
        extraction_notes=data.get("extraction_notes"),
    )

    # Determine which field names contain low-confidence words
    flagged_fields = _flag_low_confidence_fields(extracted, low_confidence_words)
    extracted.low_confidence_fields = flagged_fields

    return extracted, flagged_fields


def _flag_low_confidence_fields(
    extracted: DailyReportExtracted, low_confidence_words: list[str]
) -> list[str]:
    """Check which extracted fields contain OCR low-confidence words."""
    if not low_confidence_words:
        return []

    lc_set = {w.lower() for w in low_confidence_words}
    flagged = []

    def _contains_lc(value: Optional[str]) -> bool:
        if not value:
            return False
        return any(lc in value.lower() for lc in lc_set)

    field_map = {
        "contractor_name": extracted.contractor_name,
        "supervisor_name": extracted.supervisor_name,
        "project_name": extracted.project_name,
        "work_description": extracted.work_description,
        "wt_job_number": extracted.wt_job_number,
        "document_date": extracted.document_date,
    }
    for field, value in field_map.items():
        if _contains_lc(value):
            flagged.append(field)

    # Check worker names/classifications
    for i, w in enumerate(extracted.workers):
        if _contains_lc(w.name) or _contains_lc(w.classification):
            flagged.append(f"workers[{i}]")

    return flagged


# ─── Excel handler (no AI needed) ────────────────────────────────────────────

def extract_from_excel(file_bytes: bytes, filename: str) -> DailyReportExtracted:
    """
    Extract from Excel/XLS daily reports using pandas.
    No AI — these are structured and machine-readable.
    Returns a partial DailyReportExtracted filled from sheet data.
    """
    import io

    try:
        # Read all sheets
        xls = pd.read_excel(io.BytesIO(file_bytes), sheet_name=None, header=None)
        # Flatten all sheets into one text blob for simple extraction
        text_parts = []
        for sheet_name, df in xls.items():
            text_parts.append(f"Sheet: {sheet_name}")
            text_parts.append(df.fillna("").astype(str).to_string())

        combined_text = "\n".join(text_parts)

        # For Excel, still use GPT-4o mapping (text is clean, DI not needed)
        client = _get_openai_client()
        deployment = _require("AZURE_OPENAI_DEPLOYMENT")

        response = client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": f"Extract structured data from this Excel daily report:\n\n{combined_text[:4000]}"},
            ],
            temperature=0,
            max_tokens=2000,
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content)
        return DailyReportExtracted(
            document_date=data.get("document_date"),
            contractor_name=data.get("contractor_name"),
            wt_job_number=data.get("wt_job_number"),
            project_name=data.get("project_name"),
            supervisor_name=data.get("supervisor_name"),
            total_manpower=data.get("total_manpower"),
            workers=[WorkerEntry(**w) for w in (data.get("workers") or [])],
            work_description=data.get("work_description"),
            weather=data.get("weather"),
            extraction_notes="Extracted from Excel — no OCR confidence data available",
        )
    except Exception as e:
        logger.error(f"Excel extraction failed for {filename}: {e}")
        return DailyReportExtracted(extraction_notes=f"Excel parse error: {str(e)}")


# ─── Main entry point ─────────────────────────────────────────────────────────

SUPPORTED_CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
}

EXCEL_EXTENSIONS = {".xlsx", ".xls"}


def extract_document(
    file_bytes: bytes, filename: str
) -> tuple[DailyReportExtracted, str, str | None]:
    """
    Main extraction entry point.

    Returns:
        extracted: DailyReportExtracted
        file_type: "pdf" | "image" | "excel"
        raw_di_markdown: raw DI output string (None for Excel)
    """
    suffix = Path(filename).suffix.lower()

    # ── Excel: no DI needed ──
    if suffix in EXCEL_EXTENSIONS:
        extracted = extract_from_excel(file_bytes, filename)
        return extracted, "excel", None

    # ── PDF / Image: full pipeline ──
    content_type = SUPPORTED_CONTENT_TYPES.get(suffix)
    if not content_type:
        raise ValueError(f"Unsupported file type: {suffix}")

    file_type = "pdf" if suffix == ".pdf" else "image"

    # Stage 1
    markdown_content, low_confidence_words = run_document_intelligence(
        file_bytes, content_type
    )

    # Stage 2 + 3
    extracted, _ = run_llm_mapping(markdown_content, low_confidence_words)

    return extracted, file_type, markdown_content