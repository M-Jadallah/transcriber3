"""Celery tasks for the transcription pipeline."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

from app.celery_app import celery_app
from app.core.db import SessionLocal
from app.core.models import Export, Job, Transcript
from app.services.export_service import ensure_exports

logger = logging.getLogger(__name__)


def _audio_root() -> Path:
    return Path(os.getenv("AUDIO_ROOT", "/data/audio"))


def _exports_root() -> Path:
    return Path(os.getenv("EXPORTS_ROOT", "/data/exports"))


def _download_audio(url: str, output_dir: Path, job_id: str) -> Path:
    """Download audio from YouTube using yt-dlp."""
    output_template = str(output_dir / f"{job_id}.%(ext)s")
    audio_format = os.getenv("AUDIO_BITRATE", "64k")
    sample_rate = os.getenv("AUDIO_SAMPLE_RATE", "16000")
    channels = os.getenv("AUDIO_CHANNELS", "1")

    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", audio_format,
        "--postprocessor-args",
        f"-ar {sample_rate} -ac {channels}",
        "-o", output_template,
        "--no-cache-dir",
        "--no-check-certificates",
        url,
    ]

    youtube_config = os.getenv("YOUTUBE_CONFIG_ROOT", "/data/youtube")
    cookie_file = Path(youtube_config) / "cookies.txt"
    if cookie_file.is_file():
        cmd.extend(["--cookies", str(cookie_file)])

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=600,
    )

    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp failed: {result.stderr[:2000]}")

    # Find the output file
    mp3_file = output_dir / f"{job_id}.mp3"
    if not mp3_file.exists():
        # Try to find any audio file
        for ext in (".mp3", ".m4a", ".wav", ".ogg", ".webm"):
            for f in output_dir.glob(f"{job_id}*{ext}"):
                return f
        raise RuntimeError("Audio file not found after download")

    return mp3_file


def _transcribe_with_deepgram(audio_path: Path, api_key: str, language: str = "ar", model: str = "whisper-large") -> dict:
    """Transcribe audio using the Deepgram API."""
    from deepgram import DeepgramClient, PrerecordedOptions

    client = DeepgramClient(api_key)

    options = PrerecordedOptions(
        model=model,
        language=language,
        smart_format=True,
        punctuate=True,
        utterances=True,
        diarize=False,
    )

    with open(audio_path, "rb") as audio:
        source = {"buffer": audio, "mimetype": "audio/mp3"}
        response = client.listen.prerecorded.v("1").transcribe_file(source, options)

    return json.loads(response.json())


@celery_app.task(name="app.tasks.transcribe", bind=True, max_retries=3, default_retry_delay=60)
def transcribe(self, job_id: str) -> None:
    """Main transcription task."""
    from datetime import UTC, datetime

    with SessionLocal() as db:
        job = db.execute(
            __import__("sqlalchemy").select(Job).where(Job.id == job_id)
        ).scalar_one_or_none()

        if not job:
            logger.error("Job %s not found", job_id)
            return

        if job.status == "cancelled":
            logger.info("Job %s was cancelled, skipping", job_id)
            return

        try:
            # Mark as running
            job.status = "running"
            job.started_at = datetime.now(UTC)
            db.commit()

            # Download audio
            audio_dir = _audio_root() / job_id
            audio_dir.mkdir(parents=True, exist_ok=True)

            audio_path = _download_audio(job.url, audio_dir, job_id)
            logger.info("Downloaded audio for job %s: %s", job_id, audio_path)

            # Get title from yt-dlp
            try:
                title_result = subprocess.run(
                    ["yt-dlp", "--no-playlist", "--get-title", "--no-cache-dir", job.url],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if title_result.returncode == 0 and title_result.stdout.strip():
                    job.title = title_result.stdout.strip()[:1000]
            except Exception:
                pass

            # Transcribe
            api_key = os.getenv("DEEPGRAM_API_KEY", "")
            if not api_key:
                raise RuntimeError("DEEPGRAM_API_KEY not configured")

            language = job.language or os.getenv("DEFAULT_LANGUAGE", "ar")
            model = job.model or os.getenv("DEFAULT_DEEPGRAM_MODEL", "whisper-large")

            result = _transcribe_with_deepgram(audio_path, api_key, language, model)
            logger.info("Transcription completed for job %s", job_id)

            # Extract text from result
            text = ""
            channels = result.get("results", {}).get("channels", [])
            for channel in channels:
                for alternative in channel.get("alternatives", []):
                    text += alternative.get("transcript", "") + "\n"

            if not text.strip():
                raise RuntimeError("Transcription returned empty text")

            # Save transcript
            transcript = Transcript(
                job_id=job_id,
                text=text.strip(),
                json_data=json.dumps(result, ensure_ascii=False),
            )
            db.add(transcript)

            # Mark as completed
            job.status = "completed"
            job.completed_at = datetime.now(UTC)
            db.commit()

            # Generate exports
            db.refresh(job)
            ensure_exports(db, job)

            logger.info("Job %s completed successfully", job_id)

        except Exception as exc:
            logger.error("Job %s failed: %s", job_id, exc)
            try:
                job.status = "failed"
                job.error_message = str(exc)[:2000]
                job.completed_at = datetime.now(UTC)
                db.commit()
            except Exception:
                db.rollback()

            # Retry for transient failures
            if self.request.retries < self.max_retries:
                raise self.retry(exc=exc)
