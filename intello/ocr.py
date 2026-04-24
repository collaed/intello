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

# Job storage (SQLite-persisted, survives restarts)
JOBS_DIR = Path(os.environ.get("OCR_JOBS_DIR", "/data/ocr_jobs"))
JOBS_DIR.mkdir(parents=True, exist_ok=True)

# Process pool for CPU-bound OCR work — prevents blocking the event loop
from concurrent.futures import ProcessPoolExecutor
_ocr_pool = ProcessPoolExecutor(max_workers=1)  # 1 worker = no concurrent OOM


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
    language = _normalize_lang(language)
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
    language = _normalize_lang(language)
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

def _detect_font_style(paragraph: dict, img=None) -> tuple[str, float]:
    """Detect font style from OCR paragraph data. Returns (fontname, fontsize).
    Uses word bbox geometry to classify serif/sans/mono."""
    bbox = paragraph.get("bbox", [0, 0, 100, 20])
    words = paragraph.get("words", [])
    if not words:
        return "helv", 10  # default sans-serif

    # Estimate font size from bbox height (in PDF points at 72dpi from 300dpi scan)
    char_height = (bbox[3] - bbox[1]) * 72 / 300
    fontsize = max(6, min(16, char_height * 0.7))

    # Detect monospace: check if word widths per character are uniform
    char_widths = []
    for w in words:
        if w.get("bbox") and w.get("text") and len(w["text"]) > 0:
            w_width = w["bbox"][2] - w["bbox"][0]
            char_widths.append(w_width / len(w["text"]))

    if char_widths and len(char_widths) >= 3:
        avg_cw = sum(char_widths) / len(char_widths)
        variance = sum((c - avg_cw) ** 2 for c in char_widths) / len(char_widths)
        # Monospace: very low variance in character width
        if variance < (avg_cw * 0.05) ** 2:
            return "cour", fontsize  # Courier (monospace)

    # Detect bold: thicker strokes = taller relative to width
    avg_aspect = 0
    for w in words:
        if w.get("bbox") and w.get("text"):
            ww = w["bbox"][2] - w["bbox"][0]
            wh = w["bbox"][3] - w["bbox"][1]
            if wh > 0:
                avg_aspect += ww / wh / max(len(w["text"]), 1)
    if words:
        avg_aspect /= len(words)

    # Detect serif vs sans-serif heuristic:
    # Serif fonts tend to have more width variation between characters
    # and slightly wider average character width relative to height
    if char_widths and len(char_widths) >= 3:
        avg_cw = sum(char_widths) / len(char_widths)
        cv = (sum((c - avg_cw) ** 2 for c in char_widths) / len(char_widths)) ** 0.5 / max(avg_cw, 1)
        # Higher coefficient of variation = more likely serif
        if cv > 0.25:
            # Serif
            if avg_aspect > 0.7:
                return "tibo", fontsize  # Times Bold
            return "tiro", fontsize  # Times Roman (serif)

    # Default: sans-serif
    if avg_aspect > 0.7:
        return "hebo", fontsize  # Helvetica Bold
    return "helv", fontsize  # Helvetica (sans-serif)


def _classify_image(img_bytes: bytes, img_bbox: tuple, page_area: float) -> str:
    """Classify an embedded image: 'pure_image' (photo/illustration) or 'text_image' (may contain text).

    VERY conservative — only strips images that are CLEARLY photos/illustrations.
    Anything with text characteristics (including colored backgrounds with text,
    inverted text, callout boxes) goes through OCR.
    """
    from PIL import Image
    import io

    img_area = (img_bbox[2] - img_bbox[0]) * (img_bbox[3] - img_bbox[1])
    area_ratio = img_area / page_area if page_area > 0 else 0

    try:
        pil_img = Image.open(io.BytesIO(img_bytes))
        w, h = pil_img.size

        # Tiny images (<3% of page) — icons, bullets, decorative elements
        if area_ratio < 0.03:
            return "pure_image"

        # Very wide and short = horizontal rule or thin banner
        if w > h * 8:
            return "pure_image"

        import numpy as np
        arr = np.array(pil_img.convert("L"))  # grayscale
        std = float(np.std(arr))
        mean = float(np.mean(arr))

        # --- Detect text-bearing images (KEEP for OCR) ---

        # White/light text on dark background (inverted/negative text)
        # Dark mean + some variance = likely colored box with white text
        if mean < 100 and std > 30:
            return "text_image"  # dark background with content — likely inverted text

        # Colored background with text (callout boxes, highlighted sections)
        # Check if image has a dominant non-white, non-black color
        if pil_img.mode in ("RGB", "RGBA"):
            rgb = np.array(pil_img.convert("RGB"))
            r_std = float(np.std(rgb[:, :, 0]))
            g_std = float(np.std(rgb[:, :, 1]))
            b_std = float(np.std(rgb[:, :, 2]))
            # Low per-channel variance but not grayscale = solid colored background
            if max(r_std, g_std, b_std) < 70 and min(r_std, g_std, b_std) < 40:
                # Solid-ish color — likely a text box with colored background
                return "text_image"

        # Any image with structured horizontal patterns = likely text lines
        # Check row-by-row variance: text pages have alternating light/dark rows
        if arr.shape[0] > 20:
            row_means = np.mean(arr, axis=1)
            row_variance = float(np.std(row_means))
            if row_variance > 15:
                return "text_image"  # horizontal banding = text lines

        # --- Only classify as pure image if VERY clearly a photo ---

        # Very high color variance across all channels = natural photo
        if std > 70 and pil_img.mode in ("RGB", "RGBA"):
            rgb = np.array(pil_img.convert("RGB"))
            color_std = float(np.std(rgb))
            if color_std > 60:
                return "pure_image"  # high color diversity = photo

        # Everything else: assume it contains text (safe default)
        return "text_image"

    except Exception:
        return "text_image"  # if analysis fails, OCR it


def ocr_pdf_hybrid(pdf_path: str, output_path: str, language: str = "eng",
                    pages: str = "") -> dict:
    """Three-phase hybrid OCR:
    Phase 1: Classify each page and strip pure images (photos/illustrations)
    Phase 2: OCR the text-only version (faster, more accurate, cheaper escalation)
    Phase 3: Recombine OCR'd text + original illustrations

    Pages classified as:
    - >70% pure image area: keep original page as-is (no OCR)
    - 30-70% pure image: strip images → OCR text → recombine
    - <30% pure image: discard page image, render as pure text
    """
    try:
        import fitz
    except ImportError:
        return {"ok": False, "error": "pymupdf not installed"}

    lang = _normalize_lang(language)
    src = fitz.open(pdf_path)

    page_range = None
    if pages:
        parts = pages.split("-")
        if len(parts) == 2:
            page_range = (int(parts[0]), int(parts[1]))

    start_page = (page_range[0] - 1) if page_range else 0
    end_page = page_range[1] if page_range else src.page_count

    # Phase 1: Classify pages
    page_plans = []  # [{type: "full_image"|"mixed"|"text_only", images: [...]}]

    for page_idx in range(start_page, end_page):
        page = src[page_idx]
        page_area = page.rect.width * page.rect.height
        img_list = page.get_images(full=True)

        pure_images = []  # images to preserve
        text_images = []  # images that may contain text (need OCR)
        total_pure_area = 0

        for img_info in img_list:
            xref = img_info[0]
            try:
                img_bytes = src.extract_image(xref)["image"]
                # Get image bbox on page
                img_rects = page.get_image_rects(xref)
                if not img_rects:
                    continue
                bbox = img_rects[0]
                img_area = bbox.width * bbox.height

                classification = _classify_image(img_bytes, (bbox.x0, bbox.y0, bbox.x1, bbox.y1), page_area)

                if classification == "pure_image":
                    pure_images.append({"xref": xref, "bbox": bbox, "bytes": img_bytes, "area": img_area})
                    total_pure_area += img_area
                else:
                    text_images.append({"xref": xref, "bbox": bbox, "area": img_area})
            except Exception:
                continue

        image_ratio = total_pure_area / page_area if page_area > 0 else 0

        if image_ratio > 0.70:
            page_plans.append({"type": "full_image", "page_idx": page_idx, "images": pure_images})
        elif image_ratio > 0.30:
            page_plans.append({"type": "mixed", "page_idx": page_idx, "images": pure_images})
        else:
            page_plans.append({"type": "text_only", "page_idx": page_idx, "images": pure_images})

    # Phase 2: Create stripped PDF (text-images only) and OCR it
    pages_to_ocr = [p["page_idx"] for p in page_plans if p["type"] != "full_image"]

    ocr_results = {}  # page_idx → {paragraphs, confidence}
    if pages_to_ocr:
        from pdf2image import convert_from_path
        # Render only the pages that need OCR
        for page_idx in pages_to_ocr:
            page_num = page_idx + 1  # pdf2image is 1-indexed
            imgs = convert_from_path(pdf_path, dpi=300, first_page=page_num, last_page=page_num)
            if imgs:
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                    imgs[0].save(f.name, "PNG")
                    result = ocr_image(f.name, lang, "json")
                    os.unlink(f.name)
                ocr_results[page_idx] = result

    # Phase 3: Recombine
    out_doc = fitz.open()
    total_conf = []

    for plan in page_plans:
        page_idx = plan["page_idx"]
        src_page = src[page_idx]
        w = src_page.rect.width
        h = src_page.rect.height

        if plan["type"] == "full_image":
            # Keep original page exactly as-is
            out_doc.insert_pdf(src, from_page=page_idx, to_page=page_idx)

        elif plan["type"] == "mixed":
            # New page: insert pure images at original positions + OCR'd text
            new_page = out_doc.new_page(width=w, height=h)

            # Insert preserved illustrations from original
            for img in plan["images"]:
                try:
                    new_page.insert_image(img["bbox"], stream=img["bytes"])
                except Exception:
                    pass

            # Insert OCR'd text
            ocr_data = ocr_results.get(page_idx, {})
            if ocr_data.get("confidence"):
                total_conf.append(ocr_data["confidence"])
            for para in ocr_data.get("paragraphs", []):
                if not para.get("text") or not para.get("bbox"):
                    continue
                bbox = para["bbox"]
                # Scale from 300dpi pixel coords to PDF points
                sx = w / (src_page.rect.width * 300 / 72)
                sy = h / (src_page.rect.height * 300 / 72)
                rect = fitz.Rect(bbox[0] * sx, bbox[1] * sy, bbox[2] * sx, bbox[3] * sy)
                fontname, fontsize = _detect_font_style(para)
                try:
                    new_page.insert_textbox(rect, para["text"], fontsize=fontsize,
                                             fontname=fontname, align=fitz.TEXT_ALIGN_LEFT)
                except Exception:
                    pass

        else:  # text_only
            # Pure text page — no images, just OCR'd text on clean background
            new_page = out_doc.new_page(width=w, height=h)

            # Small pure images (icons, bullets) still get inserted
            for img in plan["images"]:
                try:
                    new_page.insert_image(img["bbox"], stream=img["bytes"])
                except Exception:
                    pass

            ocr_data = ocr_results.get(page_idx, {})
            if ocr_data.get("confidence"):
                total_conf.append(ocr_data["confidence"])
            for para in ocr_data.get("paragraphs", []):
                if not para.get("text") or not para.get("bbox"):
                    continue
                bbox = para["bbox"]
                sx = w / (src_page.rect.width * 300 / 72)
                sy = h / (src_page.rect.height * 300 / 72)
                rect = fitz.Rect(bbox[0] * sx, bbox[1] * sy, bbox[2] * sx, bbox[3] * sy)
                fontname, fontsize = _detect_font_style(para)
                try:
                    new_page.insert_textbox(rect, para["text"], fontsize=fontsize,
                                             fontname=fontname, align=fitz.TEXT_ALIGN_LEFT)
                except Exception:
                    pass

    src.close()
    out_doc.save(output_path, deflate=True, garbage=4)
    out_doc.close()

    avg_conf = sum(total_conf) / len(total_conf) if total_conf else 0
    size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
    full_img_pages = sum(1 for p in page_plans if p["type"] == "full_image")
    mixed_pages = sum(1 for p in page_plans if p["type"] == "mixed")
    text_pages = sum(1 for p in page_plans if p["type"] == "text_only")

    return {"ok": True, "size_bytes": size, "pages": len(page_plans),
            "full_image_pages": full_img_pages, "mixed_pages": mixed_pages,
            "text_pages": text_pages, "avg_confidence": round(avg_conf, 1),
            "engine": "tesseract+hybrid_v2"}


# Map common language codes to Tesseract 3-letter codes
LANG_MAP = {
    "en": "eng", "fr": "fra", "de": "deu", "es": "spa",
    "it": "ita", "pt": "por", "nl": "nld", "ru": "rus",
    "eng": "eng", "fra": "fra", "deu": "deu", "spa": "spa",
    "ita": "ita", "por": "por", "nld": "nld", "rus": "rus",
}


def _normalize_lang(language: str) -> str:
    return LANG_MAP.get(language.lower().strip(), language)


def ocr_pdf_searchable(pdf_path: str, output_path: str, language: str = "eng",
                       pages: str = "", optimize: int = 3, force: bool = False) -> dict:
    """Create a searchable PDF. Chunks large PDFs (>30 pages) to avoid OOM.
    Returns {ok, error, size_bytes}."""
    lang = _normalize_lang(language)

    # Get page count via pdfinfo
    page_count = 0
    try:
        r = subprocess.run(["pdfinfo", pdf_path], capture_output=True, text=True, timeout=30)
        for line in r.stdout.split("\n"):
            if line.startswith("Pages:"):
                page_count = int(line.split(":")[1].strip())
    except Exception:
        pass

    def _run_ocrmypdf(src, dst, page_range=""):
        cmd = ["ocrmypdf", "-l", lang,
               "--skip-text" if not force else "--force-ocr",
               "--optimize", str(optimize),
               "--rotate-pages", "--deskew"]
        if page_range:
            cmd.extend(["--pages", page_range])
        cmd.extend([src, dst])
        return subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    # Small PDFs or specific page range: process whole file
    if page_count <= 30 or page_count == 0 or pages:
        try:
            r = _run_ocrmypdf(pdf_path, output_path, pages)
            if r.returncode in (0, 4):
                return {"ok": True, "size_bytes": os.path.getsize(output_path) if os.path.exists(output_path) else 0}
            return {"ok": False, "error": f"exit {r.returncode}: {r.stderr[-300:]}" if r.stderr else f"exit {r.returncode}"}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "Timeout"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # Large PDFs: process 20 pages at a time, merge results
    try:
        import fitz
    except ImportError:
        # Fallback: try whole file anyway
        try:
            r = _run_ocrmypdf(pdf_path, output_path)
            if r.returncode in (0, 4):
                return {"ok": True, "size_bytes": os.path.getsize(output_path) if os.path.exists(output_path) else 0}
            return {"ok": False, "error": f"exit {r.returncode}: {r.stderr[-300:]}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    chunk_size = 20
    chunk_paths = []
    for start in range(1, page_count + 1, chunk_size):
        end = min(start + chunk_size - 1, page_count)
        chunk_out = f"{output_path}.chunk_{start}.pdf"
        try:
            r = _run_ocrmypdf(pdf_path, chunk_out, f"{start}-{end}")
            if r.returncode in (0, 4) and os.path.exists(chunk_out):
                chunk_paths.append(chunk_out)
            else:
                chunk_paths.append(None)  # failed chunk
        except Exception:
            chunk_paths.append(None)

    # Merge chunks
    try:
        merged = fitz.open()
        src = fitz.open(pdf_path)
        for i, start in enumerate(range(0, page_count, chunk_size)):
            end = min(start + chunk_size, page_count)
            if i < len(chunk_paths) and chunk_paths[i]:
                chunk_doc = fitz.open(chunk_paths[i])
                merged.insert_pdf(chunk_doc)
                chunk_doc.close()
            else:
                merged.insert_pdf(src, from_page=start, to_page=end - 1)
        src.close()
        merged.save(output_path, deflate=True, garbage=4)
        merged.close()
    except Exception as e:
        return {"ok": False, "error": f"Merge failed: {e}"}
    finally:
        for cp in chunk_paths:
            if cp and os.path.exists(cp):
                try:
                    os.unlink(cp)
                except OSError:
                    pass

    return {"ok": True, "size_bytes": os.path.getsize(output_path) if os.path.exists(output_path) else 0}


# --- Async job management (SQLite-persisted) ---

import sqlite3
from contextlib import contextmanager
from intello.log import log

_JOBS_DB = os.environ.get("OCR_JOBS_DB", "/data/ocr_jobs.db")


@contextmanager
def _jobdb():
    os.makedirs(os.path.dirname(_JOBS_DB), exist_ok=True)
    conn = sqlite3.connect(_JOBS_DB)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _init_jobdb() -> None:
    with _jobdb() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS ocr_jobs (
            job_id TEXT PRIMARY KEY,
            status TEXT DEFAULT 'queued',
            file_path TEXT,
            language TEXT DEFAULT 'eng',
            output TEXT DEFAULT 'searchable_pdf',
            pages TEXT DEFAULT '',
            progress INTEGER DEFAULT 0,
            pages_done INTEGER DEFAULT 0,
            result_path TEXT,
            error TEXT,
            engine_used TEXT DEFAULT '',
            avg_confidence REAL DEFAULT 0,
            input_size INTEGER DEFAULT 0,
            output_size INTEGER DEFAULT 0,
            created_at REAL,
            updated_at REAL
        )""")
        # Migrate old tables
        for col, default in [("engine_used", "''"), ("avg_confidence", "0"),
                              ("input_size", "0"), ("output_size", "0")]:
            try:
                conn.execute(f"SELECT {col} FROM ocr_jobs LIMIT 1")
            except Exception:
                conn.execute(f"ALTER TABLE ocr_jobs ADD COLUMN {col} DEFAULT {default}")


_init_jobdb()


def create_job(file_path: str, language: str, output: str, pages: str = "") -> str:
    job_id = uuid.uuid4().hex[:12]
    now = time.time()
    with _jobdb() as conn:
        conn.execute("""INSERT INTO ocr_jobs
                        (job_id, status, file_path, language, output, pages, created_at, updated_at)
                        VALUES (?,?,?,?,?,?,?,?)""",
                     (job_id, "queued", file_path, language, output, pages, now, now))
    return job_id


def _update_job(job_id: str, **kwargs) -> None:
    if not kwargs:
        return
    kwargs["updated_at"] = time.time()
    # Column names from code (not user input) — safe for f-string; values parameterized
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [job_id]
    with _jobdb() as conn:
        conn.execute(f"UPDATE ocr_jobs SET {sets} WHERE job_id=?", vals)  # noqa: S608


def get_job(job_id: str) -> dict | None:
    with _jobdb() as conn:
        row = conn.execute("SELECT * FROM ocr_jobs WHERE job_id=?", (job_id,)).fetchone()
    return dict(row) if row else None


async def run_job(job_id: str):
    """Process an OCR job asynchronously. Status persisted to SQLite."""
    job = get_job(job_id)
    if not job:
        return

    # Record input size
    input_size = os.path.getsize(job["file_path"]) if os.path.exists(job["file_path"]) else 0
    _update_job(job_id, status="processing", input_size=input_size)

    try:
        if job["output"] == "searchable_pdf":
            out_path = str(JOBS_DIR / f"{job_id}.pdf")
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                _ocr_pool, ocr_pdf_searchable, job["file_path"], out_path, job["language"], job["pages"])
            if result["ok"]:
                _update_job(job_id, status="complete", result_path=out_path, progress=100,
                            engine_used="tesseract+ocrmypdf",
                            output_size=result.get("size_bytes", 0))
            else:
                _update_job(job_id, status="failed", error=result.get("error", "OCRmyPDF failed"))
        elif job["output"] == "hybrid":
            out_path = str(JOBS_DIR / f"{job_id}.pdf")
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                _ocr_pool, ocr_pdf_hybrid, job["file_path"], out_path, job["language"], job["pages"])
            if result.get("ok"):
                _update_job(job_id, status="complete", result_path=out_path, progress=100,
                            engine_used=result.get("engine", "hybrid"),
                            avg_confidence=result.get("avg_confidence", 0),
                            output_size=result.get("size_bytes", 0))
            else:
                _update_job(job_id, status="failed", error=result.get("error", "Hybrid OCR failed"))
        else:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                _ocr_pool, ocr_pdf_to_text, job["file_path"], job["language"], job["pages"])
            out_path = str(JOBS_DIR / f"{job_id}.json")
            with open(out_path, "w") as f:
                json.dump(result, f)

            # Calculate average confidence across pages
            confidences = [p.get("confidence", 0) for p in result.get("pages", []) if p.get("confidence")]
            avg_conf = sum(confidences) / len(confidences) if confidences else 0

            _update_job(job_id, status="complete", result_path=out_path,
                        progress=100, pages_done=result["processed_pages"],
                        engine_used="tesseract", avg_confidence=round(avg_conf, 1),
                        output_size=os.path.getsize(out_path) if os.path.exists(out_path) else 0)
    except Exception as e:
        _update_job(job_id, status="failed", error=str(e))
    finally:
        # Clean up the uploaded source file
        src = job.get("file_path", "")
        if src and os.path.exists(src) and src != get_job(job_id).get("result_path"):
            try:
                os.unlink(src)
            except OSError:
                pass


def cleanup_old_files(max_age_hours: int = 24):
    """Remove temp files older than max_age_hours from the jobs directory."""
    cutoff = time.time() - (max_age_hours * 3600)
    if not JOBS_DIR.exists():
        return 0
    removed = 0
    for f in JOBS_DIR.iterdir():
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1
        except OSError:
            pass
    # Mark interrupted jobs as failed
    with _jobdb() as conn:
        conn.execute("UPDATE ocr_jobs SET status='failed', error='Interrupted by restart' WHERE status='processing'")
    return removed
