"""Export service: generates TXT, SRT, VTT, and DOCX exports from transcripts."""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, List, Optional

from sqlalchemy.orm import Session

from app.core.models import Export, Job, Transcript

logger = logging.getLogger(__name__)


def _exports_root() -> Path:
    return Path(os.getenv("EXPORTS_ROOT", "/data/exports"))


def _job_export_dir(job_id: str) -> Path:
    return _exports_root() / job_id


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _generate_txt(transcript: Transcript) -> str:
    """Return the plain text content of the transcript."""
    return transcript.text or ""


def _generate_srt(transcript: Transcript) -> str:
    """Generate SRT subtitle content from Deepgram JSON data."""
    if not transcript.json_data:
        return ""
    try:
        data = json.loads(transcript.json_data)
    except (json.JSONDecodeError, TypeError):
        return ""

    words = []
    results = data.get("results", {})
    channels = results.get("channels", [])
    for channel in channels:
        alternatives = channel.get("alternatives", [])
        for alt in alternatives:
            words.extend(alt.get("words", []))

    if not words:
        return ""

    lines = []
    for idx, word in enumerate(words):
        if idx % 8 == 0 and idx > 0:
            # Start a new subtitle every ~8 words
            pass
        start = word.get("start", 0)
        end = word.get("end", 0)

    # Group words into subtitle blocks
    block_size = 8
    for block_idx in range(0, len(words), block_size):
        block = words[block_idx : block_idx + block_size]
        if not block:
            continue
        sub_idx = block_idx // block_size + 1
        start_time = block[0].get("start", 0)
        end_time = block[-1].get("end", 0)

        start_h = int(start_time // 3600)
        start_m = int((start_time % 3600) // 60)
        start_s = int(start_time % 60)
        start_ms = int((start_time % 1) * 1000)

        end_h = int(end_time // 3600)
        end_m = int((end_time % 3600) // 60)
        end_s = int(end_time % 60)
        end_ms = int((end_time % 1) * 1000)

        text = " ".join(w.get("word", "") for w in block)
        lines.append(
            f"{sub_idx}\n"
            f"{start_h:02d}:{start_m:02d}:{start_s:02d},{start_ms:03d} --> "
            f"{end_h:02d}:{end_m:02d}:{end_s:02d},{end_ms:03d}\n"
            f"{text}\n"
        )

    return "\n".join(lines)


def _generate_vtt(transcript: Transcript) -> str:
    """Generate WebVTT subtitle content from Deepgram JSON data."""
    srt = _generate_srt(transcript)
    if not srt:
        return ""
    # Convert SRT timestamps to VTT format
    vtt = "WEBVTT\n\n" + srt.replace(",", ".")
    return vtt


def _generate_docx(transcript: Transcript) -> bytes:
    """Generate a DOCX file from the transcript text."""
    from docx import Document

    doc = Document()
    doc.add_heading("Transcript", level=1)
    text = transcript.text or ""
    for paragraph_text in text.split("\n\n"):
        if paragraph_text.strip():
            doc.add_paragraph(paragraph_text.strip())

    import io
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def _create_export_record(
    db: Session,
    job: Job,
    fmt: str,
    file_name: str,
    file_path: Path,
    size_bytes: int,
    mime_type: str,
) -> Export:
    """Create an Export database record."""
    export = Export(
        job_id=job.id,
        format=fmt,
        file_path=str(file_path),
        file_name=file_name,
        mime_type=mime_type,
        size_bytes=size_bytes,
    )
    db.add(export)
    db.flush()
    return export


def ensure_exports(db: Session, job: Job) -> List[Export]:
    """Ensure all export files exist for a completed job. Return the export records."""
    if not job.transcript:
        return list(job.exports)

    existing_formats = {export.format for export in job.exports}
    export_dir = _job_export_dir(job.id)
    export_dir.mkdir(parents=True, exist_ok=True)

    exports = list(job.exports)

    # TXT export
    if "txt" not in existing_formats:
        txt_content = _generate_txt(job.transcript)
        if txt_content:
            txt_path = export_dir / f"{job.id}.txt"
            _write_text(txt_path, txt_content)
            export = _create_export_record(
                db, job, "txt", f"{job.id}.txt", txt_path,
                len(txt_content.encode("utf-8")), "text/plain; charset=utf-8",
            )
            exports.append(export)

    # SRT export
    if "srt" not in existing_formats:
        srt_content = _generate_srt(job.transcript)
        if srt_content:
            srt_path = export_dir / f"{job.id}.srt"
            _write_text(srt_path, srt_content)
            export = _create_export_record(
                db, job, "srt", f"{job.id}.srt", srt_path,
                len(srt_content.encode("utf-8")), "text/srt; charset=utf-8",
            )
            exports.append(export)

    # VTT export
    if "vtt" not in existing_formats:
        vtt_content = _generate_vtt(job.transcript)
        if vtt_content:
            vtt_path = export_dir / f"{job.id}.vtt"
            _write_text(vtt_path, vtt_content)
            export = _create_export_record(
                db, job, "vtt", f"{job.id}.vtt", vtt_path,
                len(vtt_content.encode("utf-8")), "text/vtt; charset=utf-8",
            )
            exports.append(export)

    # DOCX export
    if "docx" not in existing_formats:
        try:
            docx_bytes = _generate_docx(job.transcript)
            if docx_bytes:
                docx_path = export_dir / f"{job.id}.docx"
                docx_path.write_bytes(docx_bytes)
                export = _create_export_record(
                    db, job, "docx", f"{job.id}.docx", docx_path,
                    len(docx_bytes),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
                exports.append(export)
        except Exception as exc:
            logger.warning("Failed to generate DOCX for job %s: %s", job.id, exc)

    # JSON export
    if "json" not in existing_formats and job.transcript.json_data:
        json_path = export_dir / f"{job.id}.json"
        _write_text(json_path, job.transcript.json_data)
        export = _create_export_record(
            db, job, "json", f"{job.id}.json", json_path,
            len(job.transcript.json_data.encode("utf-8")), "application/json",
        )
        exports.append(export)

    db.commit()
    return exports
