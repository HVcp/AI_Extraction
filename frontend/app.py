"""
app.py — Streamlit frontend for the Daily Report Extraction POC.

Three sections:
  1. Upload & Extract  — drag-drop file → call /extract → show result instantly
  2. Records Browser   — paginated table of all extractions with status filter
  3. Record Detail     — click any row → full extraction + flagged fields + raw DI

Connects to FastAPI backend at BACKEND_URL (default: http://localhost:8000).
"""

import json
import os
from datetime import datetime

import requests
import streamlit as st
import pandas as pd

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

st.set_page_config(
    page_title="WT Daily Report Extraction",
    page_icon="🏗️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Styling ──────────────────────────────────────────────────────────────────

st.markdown("""
<style>
.status-success    { color: #22c55e; font-weight: 600; }
.status-review     { color: #f59e0b; font-weight: 600; }
.status-failed     { color: #ef4444; font-weight: 600; }
.flag-chip         { background: #fef3c7; color: #92400e; padding: 2px 8px;
                     border-radius: 12px; font-size: 0.8rem; margin: 2px; display: inline-block; }
.section-header    { font-size: 1rem; font-weight: 700; color: #374151;
                     border-bottom: 2px solid #e5e7eb; padding-bottom: 6px; margin-bottom: 12px; }
</style>
""", unsafe_allow_html=True)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def status_badge(status: str) -> str:
    icons = {"success": "✅", "needs_review": "⚠️", "failed": "❌"}
    return f"{icons.get(status, '?')} {status.replace('_', ' ').title()}"


def api_post_extract(file_bytes: bytes, filename: str) -> dict | None:
    try:
        resp = requests.post(
            f"{BACKEND_URL}/extract",
            files={"file": (filename, file_bytes)},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError:
        st.error("❌ Cannot reach backend. Is FastAPI running on port 8000?")
    except requests.exceptions.HTTPError as e:
        st.error(f"API error {e.response.status_code}: {e.response.json().get('detail', str(e))}")
    return None


def api_get_records(status_filter: str | None = None) -> list[dict]:
    try:
        params = {"limit": 200}
        if status_filter:
            params["status"] = status_filter
        resp = requests.get(f"{BACKEND_URL}/records", params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return []


def api_get_record(record_id: int) -> dict | None:
    try:
        resp = requests.get(f"{BACKEND_URL}/records/{record_id}", timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def api_delete_record(record_id: int) -> bool:
    try:
        resp = requests.delete(f"{BACKEND_URL}/records/{record_id}", timeout=10)
        return resp.status_code == 204
    except Exception:
        return False


# ─── Sidebar navigation ───────────────────────────────────────────────────────

st.sidebar.title("🏗️ WT Daily Report\nExtraction POC")
st.sidebar.markdown("---")
page = st.sidebar.radio(
    "Navigate",
    ["📤 Upload & Extract", "📋 Records Browser", "🔍 Record Detail"],
    label_visibility="collapsed",
)

# Health check indicator
try:
    health = requests.get(f"{BACKEND_URL}/health", timeout=3)
    if health.status_code == 200:
        st.sidebar.success("🟢 Backend connected")
    else:
        st.sidebar.error("🔴 Backend error")
except Exception:
    st.sidebar.warning("🟡 Backend unreachable")

st.sidebar.markdown("---")
st.sidebar.caption(f"Backend: `{BACKEND_URL}`")


# ─── Page 1: Upload & Extract ─────────────────────────────────────────────────

if page == "📤 Upload & Extract":
    st.title("📤 Upload Daily Report")
    st.caption("Supports PDF, images (JPG/PNG), and Excel files")

    uploaded = st.file_uploader(
        "Drop a daily report here",
        type=["pdf", "jpg", "jpeg", "png", "tiff", "xlsx", "xls"],
        help="The file is processed in memory — not stored on disk",
    )

    if uploaded:
        col1, col2, col3 = st.columns([2, 1, 1])
        col1.markdown(f"**File:** `{uploaded.name}`")
        col2.markdown(f"**Size:** {len(uploaded.getvalue()):,} bytes")
        col3.markdown(f"**Type:** `{uploaded.type}`")

        if st.button("🚀 Extract Data", type="primary", use_container_width=True):
            with st.spinner("Running Azure Document Intelligence + GPT-4o..."):
                result = api_post_extract(uploaded.getvalue(), uploaded.name)

            if result:
                status = result["status"]
                extracted = result["extracted"]

                # ── Status banner ──
                if status == "success":
                    st.success(f"✅ Extraction complete in {result['processing_time_seconds']:.1f}s")
                elif status == "needs_review":
                    st.warning(f"⚠️ Needs human review — {len(extracted['low_confidence_fields'])} field(s) flagged")
                else:
                    st.error("❌ Extraction failed")

                # ── Flagged fields ──
                if extracted.get("low_confidence_fields"):
                    st.markdown("**Low-confidence fields (review these):**")
                    chips = " ".join(
                        f'<span class="flag-chip">⚠️ {f}</span>'
                        for f in extracted["low_confidence_fields"]
                    )
                    st.markdown(chips, unsafe_allow_html=True)

                st.markdown("---")

                # ── Extracted fields ──
                c1, c2 = st.columns(2)

                with c1:
                    st.markdown('<div class="section-header">Header</div>', unsafe_allow_html=True)
                    st.markdown(f"**Date:** {extracted.get('document_date') or '—'}")
                    st.markdown(f"**WT Job #:** {extracted.get('wt_job_number') or '—'}")
                    st.markdown(f"**Project:** {extracted.get('project_name') or '—'}")
                    st.markdown(f"**Location:** {extracted.get('project_location') or '—'}")
                    st.markdown(f"**Contractor:** {extracted.get('contractor_name') or '—'}")
                    st.markdown(f"**Supervisor:** {extracted.get('supervisor_name') or '—'}")
                    st.markdown(f"**Weather:** {extracted.get('weather') or '—'} {extracted.get('temperature') or ''}")

                with c2:
                    st.markdown('<div class="section-header">Safety</div>', unsafe_allow_html=True)
                    acc = extracted.get("accidents_occurred")
                    issues = extracted.get("open_issues")
                    st.markdown(f"**Accidents/Near-misses:** {'Yes ⚠️' if acc else 'No' if acc is False else '—'}")
                    st.markdown(f"**Open issues:** {'Yes ⚠️' if issues else 'No' if issues is False else '—'}")
                    if extracted.get("safety_notes"):
                        st.markdown(f"**Notes:** {extracted['safety_notes']}")

                # ── Workers table ──
                st.markdown('<div class="section-header">Manpower</div>', unsafe_allow_html=True)
                workers = extracted.get("workers") or []
                total = extracted.get("total_manpower")
                if workers:
                    df = pd.DataFrame([
                        {
                            "Classification": w.get("classification") or "—",
                            "Name": w.get("name") or "—",
                            "Count": w.get("count") or "—",
                            "Hours": w.get("hours") or "—",
                        }
                        for w in workers
                    ])
                    st.dataframe(df, use_container_width=True, hide_index=True)
                    st.caption(f"Total manpower on site: **{total or sum(w.get('count') or 0 for w in workers)}**")
                else:
                    st.info("No worker data extracted")

                # ── Work description ──
                st.markdown('<div class="section-header">Work Performed</div>', unsafe_allow_html=True)
                st.markdown(extracted.get("work_description") or "_Not extracted_")
                if extracted.get("areas_locations"):
                    st.caption(f"Areas: {extracted['areas_locations']}")

                # ── Equipment ──
                eq_util = extracted.get("equipment_utilized") or []
                eq_idle = extracted.get("equipment_idle") or []
                if eq_util or eq_idle:
                    st.markdown('<div class="section-header">Equipment</div>', unsafe_allow_html=True)
                    ec1, ec2 = st.columns(2)
                    with ec1:
                        st.caption("Utilized")
                        if eq_util:
                            st.dataframe(pd.DataFrame(eq_util), hide_index=True, use_container_width=True)
                        else:
                            st.markdown("—")
                    with ec2:
                        st.caption("Idle")
                        if eq_idle:
                            st.dataframe(pd.DataFrame(eq_idle), hide_index=True, use_container_width=True)
                        else:
                            st.markdown("—")

                # ── Extraction notes ──
                if extracted.get("extraction_notes"):
                    st.info(f"💬 Extraction note: {extracted['extraction_notes']}")

                # ── Raw JSON expander ──
                with st.expander("🔧 Raw JSON (debug)"):
                    st.json(extracted)

                st.success(f"Record saved → ID `{result['record_id']}`")


# ─── Page 2: Records Browser ──────────────────────────────────────────────────

elif page == "📋 Records Browser":
    st.title("📋 Extracted Records")

    col_f, col_r = st.columns([3, 1])
    with col_f:
        status_filter = st.selectbox(
            "Filter by status",
            ["All", "success", "needs_review", "failed"],
            index=0,
        )
    with col_r:
        if st.button("🔄 Refresh"):
            st.rerun()

    filter_val = None if status_filter == "All" else status_filter
    records = api_get_records(filter_val)

    if not records:
        st.info("No records found. Upload a document to get started.")
    else:
        st.caption(f"{len(records)} record(s)")

        # Summary metrics
        m1, m2, m3, m4 = st.columns(4)
        success_count = sum(1 for r in records if r["status"] == "success")
        review_count = sum(1 for r in records if r["status"] == "needs_review")
        total_workers = sum(r.get("total_manpower") or 0 for r in records)

        m1.metric("Total Records", len(records))
        m2.metric("✅ Success", success_count)
        m3.metric("⚠️ Needs Review", review_count)
        m4.metric("👷 Total Workers", total_workers)

        st.markdown("---")

        # Records table
        df_data = []
        for r in records:
            df_data.append({
                "ID": r["record_id"],
                "File": r["filename"],
                "Type": r["file_type"].upper(),
                "Status": status_badge(r["status"]),
                "Contractor": r.get("contractor_name") or "—",
                "Date": r.get("document_date") or "—",
                "Workers": r.get("total_manpower") or "—",
                "Uploaded": r["created_at"][:16].replace("T", " "),
            })

        df = pd.DataFrame(df_data)
        st.dataframe(df, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.caption("To view full detail: go to **Record Detail** tab and enter the ID")

        # Quick delete
        del_id = st.number_input("Delete record by ID:", min_value=1, step=1, value=None)
        if st.button("🗑️ Delete", type="secondary") and del_id:
            if api_delete_record(int(del_id)):
                st.success(f"Record {del_id} deleted")
                st.rerun()
            else:
                st.error("Delete failed")


# ─── Page 3: Record Detail ────────────────────────────────────────────────────

elif page == "🔍 Record Detail":
    st.title("🔍 Record Detail")

    record_id = st.number_input("Enter Record ID:", min_value=1, step=1, value=1)

    if st.button("Load Record", type="primary"):
        record = api_get_record(int(record_id))

        if not record:
            st.error(f"Record {record_id} not found")
        else:
            extracted = record["extracted"]

            # Header
            st.markdown(f"### Record #{record['record_id']} — `{record['filename']}`")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Status", status_badge(record["status"]))
            c2.metric("File Type", record["file_type"].upper())
            c3.metric("Processing", f"{record['processing_time_seconds']:.1f}s")
            c4.metric("Uploaded", record["created_at"][:10])

            # Flags
            flags = extracted.get("low_confidence_fields", [])
            if flags:
                st.warning(f"⚠️ {len(flags)} low-confidence field(s) need review")
                st.markdown(
                    " ".join(f'<span class="flag-chip">⚠️ {f}</span>' for f in flags),
                    unsafe_allow_html=True,
                )

            st.markdown("---")

            # Full extracted data
            tab1, tab2, tab3 = st.tabs(["📊 Extracted Data", "🔧 Raw DI Markdown", "📄 Raw JSON"])

            with tab1:
                r1, r2 = st.columns(2)
                with r1:
                    for label, key in [
                        ("Date", "document_date"), ("WT Job #", "wt_job_number"),
                        ("Project", "project_name"), ("Location", "project_location"),
                        ("Contractor", "contractor_name"), ("Supervisor", "supervisor_name"),
                        ("Weather", "weather"), ("Temperature", "temperature"),
                    ]:
                        val = extracted.get(key) or "—"
                        flag = " ⚠️" if key in flags else ""
                        st.markdown(f"**{label}:** {val}{flag}")

                with r2:
                    acc = extracted.get("accidents_occurred")
                    issues = extracted.get("open_issues")
                    st.markdown(f"**Accidents:** {'Yes ⚠️' if acc else 'No' if acc is False else '—'}")
                    st.markdown(f"**Open Issues:** {'Yes ⚠️' if issues else 'No' if issues is False else '—'}")
                    if extracted.get("safety_notes"):
                        st.markdown(f"**Safety Notes:** {extracted['safety_notes']}")

                st.markdown("**Workers:**")
                workers = extracted.get("workers") or []
                if workers:
                    flagged_w = [f for f in flags if f.startswith("workers")]
                    if flagged_w:
                        st.warning(f"⚠️ Worker fields flagged: {', '.join(flagged_w)}")
                    st.dataframe(pd.DataFrame(workers), use_container_width=True, hide_index=True)
                else:
                    st.info("No worker data")

                st.markdown("**Work Description:**")
                st.markdown(extracted.get("work_description") or "_Not extracted_")

                if extracted.get("extraction_notes"):
                    st.info(f"💬 {extracted['extraction_notes']}")

            with tab2:
                raw_md = record.get("raw_di_markdown")
                if raw_md:
                    st.caption(f"{len(raw_md):,} characters from Azure Document Intelligence")
                    st.text_area("Azure DI Markdown Output", raw_md, height=600)
                else:
                    st.info("No raw DI output (Excel files bypass Document Intelligence)")

            with tab3:
                st.json(extracted)
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    