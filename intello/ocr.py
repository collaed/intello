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


MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "200"))


def _auto_rotate(image_path: str) -> str | None:
    """Detect rotation using Tesseract OSD and correct if needed. Returns corrected path or None."""
    try:
        r = subprocess.run(
            ["tesseract", image_path, "stdout", "--psm", "0"],
            capture_output=True, text=True, timeout=15)
        for line in r.stdout.split("\n"):
            if "Rotate:" in line:
                angle = int(line.split(":")[-1].strip())
                if angle and angle != 0:
                    from PIL import Image
                    img = Image.open(image_path)
                    rotated = img.rotate(-angle, expand=True)
                    out = image_path + "_rotated.png"
                    rotated.save(out)
                    return out
    except Exception:
        pass
    return None


def ocr_image(image_path: str, language: str = "eng", output: str = "json") -> dict:
    """OCR a single image. Auto-detects and corrects rotation.
    output: json (structured), text (plain), hocr (HTML with positions)."""
    try:
        # Auto-rotate using Tesseract's OSD (orientation/script detection)
        corrected_path = _auto_rotate(image_path)
        img_to_ocr = corrected_path or image_path
        # hOCR mode — returns HTML with embedded positions for every word
        if output == "hocr":
            r = subprocess.run(
                ["tesseract", img_to_ocr, "stdout", "-l", language, "hocr"],
                capture_output=True, text=True, timeout=60)
            return {"hocr": r.stdout, "language": language}

        # Get plain text
        r = subprocess.run(
            ["tesseract", img_to_ocr, "stdout", "-l", language],
            capture_output=True, text=True, timeout=60)
        text = r.stdout.strip()

        if output == "text":
            return {"text": text, "language": language}

        # Get TSV for structured block-level data
        r2 = subprocess.run(
            ["tesseract", img_to_ocr, "stdout", "-l", language, "tsv"],
            capture_output=True, text=True, timeout=60)

        # Parse TSV into paragraphs → lines → words hierarchy
        paragraphs = []
        current_para = {"words": [], "bbox": None, "text": ""}
        current_block = -1
        current_par = -1
        confidences = []

        for line in r2.stdout.strip().split("\n")[1:]:
            parts = line.split("\t")
            if len(parts) < 12:
                continue

            level = int(parts[0])  # 1=page 2=block 3=paragraph 4=line 5=word
            block_num = int(parts[1])
            par_num = int(parts[2])
            word = parts[11].strip()
            conf = float(parts[10]) if parts[10] else 0
            x, y, w, h = int(parts[6]), int(parts[7]), int(parts[8]), int(parts[9])

            # New paragraph boundary
            if (block_num != current_block or par_num != current_par) and current_para["words"]:
                current_para["text"] = " ".join(w["text"] for w in current_para["words"])
                paragraphs.append(current_para)
                current_para = {"words": [], "bbox": None, "text": ""}

            current_block = block_num
            current_par = par_num

            if word and conf > 0:
                bbox = [x, y, x + w, y + h]
                current_para["words"].append({"text": word, "bbox": bbox, "confidence": round(conf, 1)})
                confidences.append(conf)

                # Expand paragraph bbox
                if current_para["bbox"] is None:
                    current_para["bbox"] = list(bbox)
                else:
                    current_para["bbox"][0] = min(current_para["bbox"][0], bbox[0])
                    current_para["bbox"][1] = min(current_para["bbox"][1], bbox[1])
                    current_para["bbox"][2] = max(current_para["bbox"][2], bbox[2])
                    current_para["bbox"][3] = max(current_para["bbox"][3], bbox[3])

        # Flush last paragraph
        if current_para["words"]:
            current_para["text"] = " ".join(w["text"] for w in current_para["words"])
            paragraphs.append(current_para)

        avg_conf = sum(confidences) / len(confidences) if confidences else 0

        return {
            "text": text,
            "confidence": round(avg_conf, 1),
            "language": language,
            "paragraphs": paragraphs,
            "paragraph_count": len(paragraphs),
            "word_count": len(confidences),
        }
    except subprocess.TimeoutExpired:
        return {"text": "", "confidence": 0, "language": language, "paragraphs": [], "error": "Timeout"}
    except Exception as e:
        return {"text": "", "confidence": 0, "language": language, "paragraphs": [], "error": str(e)}
    finally:
        # Clean up rotated temp file
        if corrected_path and os.path.exists(corrected_path):
            os.unlink(corrected_path)


def ocr_pdf_to_text(pdf_path: str, language: str = "eng", pages: str = "",
                    structured: bool = False) -> dict:
    """Extract text from a scanned PDF page by page.
    structured=True returns paragraphs with bounding boxes per page."""
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
            page_result = ocr_image(f.name, language, "json")
            page_num = (page_range[0] if page_range else 1) + i
            entry = {
                "page": page_num,
                "text": page_result["text"],
                "confidence": page_result["confidence"],
            }
            if structured:
                entry["paragraphs"] = page_result.get("paragraphs", [])
                entry["word_count"] = page_result.get("word_count", 0)
                # Detect image regions (large gaps between text blocks)
                entry["image_regions"] = _detect_image_regions(
                    page_result.get("paragraphs", []), img.width, img.height)
            results.append(entry)
            os.unlink(f.name)

    return {
        "pages": results,
        "total_pages": len(images),
        "processed_pages": len(results),
    }



def _detect_image_regions(paragraphs: list, page_w: int, page_h: int) -> list:
    """Detect likely image regions — areas of the page with no text."""
    if not paragraphs or not page_h:
        return []

    # Get all text bounding boxes
    text_boxes = [p["bbox"] for p in paragraphs if p.get("bbox")]
    if not text_boxes:
        return [{"bbox": [0, 0, page_w, page_h], "type": "full_page_image"}]

    # Find vertical gaps > 10% of page height between text blocks
    sorted_boxes = sorted(text_boxes, key=lambda b: b[1])  # sort by y
    regions = []
    prev_bottom = 0

    for box in sorted_boxes:
        gap = box[1] - prev_bottom
        if gap > page_h * 0.10:  # >10% of page = likely image
            regions.append({
                "bbox": [0, prev_bottom, page_w, box[1]],
                "type": "image_region",
                "height_pct": round(gap / page_h * 100, 1),
            })
        prev_bottom = max(prev_bottom, box[3])

    # Check bottom of page
    if page_h - prev_bottom > page_h * 0.10:
        regions.append({
            "bbox": [0, prev_bottom, page_w, page_h],
            "type": "image_region",
            "height_pct": round((page_h - prev_bottom) / page_h * 100, 1),
        })

    return regions

def ocr_pdf_searchable(pdf_path: str, output_path: str, language: str = "eng", pages: str = "") -> bool:
    """Create a searchable PDF using OCRmyPDF. Auto-rotates pages."""
    cmd = ["ocrmypdf", "-l", language, "--force-ocr", "--optimize", "1",
           "--rotate-pages",           # auto-detect and fix rotation
           "--deskew",                 # fix slight skew
           "--clean",                  # clean up scan artifacts
           ]
    if pages:
        cmd.extend(["--pages", pages])
    cmd.extend([pdf_path, output_path])

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)  # 30min for large books
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
