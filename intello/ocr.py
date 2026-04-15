"""OCR service — image and PDF text extraction via Tesseract/OCRmyPDF."""
import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

# Job storage
_jobs: dict[str, dict] = {}
JOBS_DIR = Path(os.environ.get("OCR_JOBS_DIR", "/data/ocr_jobs"))
JOBS_DIR.mkdir(parents=True, exist_ok=True)


def get_languages() -> list[str]:
    """Get installed Tesseract languages."""
    try:
        r = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True)
        langs = [l.strip() for l in r.stdout.strip().split("\n")[1:] if l.strip()]
        return langs
    except Exception:
        return ["eng"]


def ocr_image(image_path: str, language: str = "eng") -> dict:
    """OCR a single image, return text + block-level data."""
    try:
        # Get plain text
        r = subprocess.run(
            ["tesseract", image_path, "stdout", "-l", language],
            capture_output=True, text=True, timeout=60)
        text = r.stdout.strip()

        # Get TSV for block-level data
        r2 = subprocess.run(
            ["tesseract", image_path, "stdout", "-l", language, "tsv"],
            capture_output=True, text=True, timeout=60)

        blocks = []
        confidences = []
        for line in r2.stdout.strip().split("\n")[1:]:  # skip header
            parts = line.split("\t")
            if len(parts) >= 12 and parts[11].strip():
                conf = float(parts[10]) if parts[10] else 0
                if conf > 0:
                    confidences.append(conf)
                    blocks.append({
                        "text": parts[11],
                        "bbox": [int(parts[6]), int(parts[7]),
                                 int(parts[6]) + int(parts[8]),
                                 int(parts[7]) + int(parts[9])],
                        "confidence": round(conf, 1),
                    })

        avg_conf = sum(confidences) / len(confidences) if confidences else 0

        return {
            "text": text,
            "confidence": round(avg_conf, 1),
            "language": language,
            "blocks": blocks,
        }
    except subprocess.TimeoutExpired:
        return {"text": "", "confidence": 0, "language": language, "blocks": [], "error": "Timeout"}
    except Exception as e:
        return {"text": "", "confidence": 0, "language": language, "blocks": [], "error": str(e)}


def ocr_pdf_to_text(pdf_path: str, language: str = "eng", pages: str = "") -> dict:
    """Extract text from a scanned PDF page by page."""
    from pdf2image import convert_from_path

    page_range = None
    if pages:
        parts = pages.split("-")
        if len(parts) == 2:
            page_range = (int(parts[0]), int(parts[1]))

    images = convert_from_path(
        pdf_path,
        first_page=page_range[0] if page_range else None,
        last_page=page_range[1] if page_range else None,
        dpi=300,
    )

    results = []
    for i, img in enumerate(images):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            img.save(f.name, "PNG")
            page_result = ocr_image(f.name, language)
            page_num = (page_range[0] if page_range else 1) + i
            results.append({
                "page": page_num,
                "text": page_result["text"],
                "confidence": page_result["confidence"],
            })
            os.unlink(f.name)

    return {
        "pages": results,
        "total_pages": len(images),
        "processed_pages": len(results),
    }


def ocr_pdf_searchable(pdf_path: str, output_path: str, language: str = "eng", pages: str = "") -> bool:
    """Create a searchable PDF using OCRmyPDF."""
    cmd = ["ocrmypdf", "-l", language, "--force-ocr", "--optimize", "1"]
    if pages:
        cmd.extend(["--pages", pages])
    cmd.extend([pdf_path, output_path])

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        return r.returncode == 0
    except Exception:
        return False


# --- Async job management ---

def create_job(file_path: str, language: str, output: str, pages: str = "") -> str:
    job_id = uuid.uuid4().hex[:12]
    _jobs[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "file_path": file_path,
        "language": language,
        "output": output,
        "pages": pages,
        "progress": 0,
        "pages_done": 0,
        "created_at": time.time(),
        "result_path": None,
        "error": None,
    }
    return job_id


def get_job(job_id: str) -> dict | None:
    return _jobs.get(job_id)


async def run_job(job_id: str):
    """Process an OCR job asynchronously."""
    job = _jobs.get(job_id)
    if not job:
        return

    job["status"] = "processing"

    try:
        if job["output"] == "searchable_pdf":
            out_path = str(JOBS_DIR / f"{job_id}.pdf")
            loop = asyncio.get_event_loop()
            ok = await loop.run_in_executor(
                None, ocr_pdf_searchable, job["file_path"], out_path, job["language"], job["pages"])
            if ok:
                job["status"] = "complete"
                job["result_path"] = out_path
                job["progress"] = 100
            else:
                job["status"] = "failed"
                job["error"] = "OCRmyPDF failed"
        else:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, ocr_pdf_to_text, job["file_path"], job["language"], job["pages"])
            job["status"] = "complete"
            job["progress"] = 100
            job["pages_done"] = result["processed_pages"]
            # Store result as JSON
            out_path = str(JOBS_DIR / f"{job_id}.json")
            with open(out_path, "w") as f:
                json.dump(result, f)
            job["result_path"] = out_path
    except Exception as e:
        job["status"] = "failed"
        job["error"] = str(e)
