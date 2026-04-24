"""OCR routes — image, PDF, jobs, result serving."""
import asyncio
import json
import os
from typing import Optional

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import FileResponse, Response

from intello import ocr
from intello import ocr_engines
from intello import jobs as jobsys

router = APIRouter(prefix="/api/v1/ocr", tags=["ocr"])


@router.post("")
async def ocr_image(
    file: UploadFile = File(...),
    language: str = Form("eng"),
    output: str = Form("json"),
    quality: str = Form("auto"),
):
    """OCR a single image. Auto-rotates. quality: fast|auto|best."""
    import tempfile
    content = await file.read()
    max_bytes = ocr.MAX_UPLOAD_MB * 1024 * 1024
    if len(content) > max_bytes:
        return {"error": f"File too large: {len(content)//1024//1024}MB (max {ocr.MAX_UPLOAD_MB}MB)"}

    with tempfile.NamedTemporaryFile(suffix=f"_{file.filename}", delete=False) as f:
        f.write(content)
        tmp = f.name

    result = await ocr_engines.smart_ocr(tmp, language, quality)
    os.unlink(tmp)

    if output == "text":
        return Response(result["text"], media_type="text/plain")
    return result


@router.post("/pdf")
async def ocr_pdf(
    file: UploadFile = File(...),
    language: str = Form("eng"),
    output: str = Form("json"),
    pages: str = Form(""),
    async_mode: bool = Form(False),
):
    """OCR a PDF. async_mode=true for background processing.
    output: json|structured|text|searchable_pdf|hybrid.
    hybrid = real text + preserved illustrations (smallest output)."""
    import tempfile
    content = await file.read()
    max_bytes = ocr.MAX_UPLOAD_MB * 1024 * 1024
    if len(content) > max_bytes:
        return {"error": f"File too large: {len(content)//1024//1024}MB (max {ocr.MAX_UPLOAD_MB}MB)"}

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(content)
        tmp = f.name

    if async_mode:
        job_id = jobsys.create_job("ocr_pdf", f"{file.filename} ({output})")

        async def _run():
            if output == "searchable_pdf":
                out_path = tmp + "_ocr.pdf"
                result = ocr.ocr_pdf_searchable(tmp, out_path, language, pages)
                os.unlink(tmp)
                return {"ok": result["ok"], "result_path": out_path if result["ok"] else None,
                        "error": result.get("error")}
            if output == "hybrid":
                out_path = tmp + "_hybrid.pdf"
                result = ocr.ocr_pdf_hybrid(tmp, out_path, language, pages)
                os.unlink(tmp)
                return result
            structured = output == "structured"
            result = ocr.ocr_pdf_to_text(tmp, language, pages, structured=structured)
            os.unlink(tmp)
            return result

        asyncio.create_task(jobsys.run_async(job_id, _run()))
        return {"job_id": job_id, "status": "queued",
                "poll": f"/api/jobs/{job_id}", "result": f"/api/jobs/{job_id}/result"}

    if output == "searchable_pdf":
        out_path = tmp + "_ocr.pdf"
        result = ocr.ocr_pdf_searchable(tmp, out_path, language, pages)
        os.unlink(tmp)
        if result["ok"]:
            return FileResponse(out_path, media_type="application/pdf",
                                filename=f"ocr_{file.filename}")
        return {"error": result.get("error", "OCR failed")}

    if output == "hybrid":
        out_path = tmp + "_hybrid.pdf"
        result = ocr.ocr_pdf_hybrid(tmp, out_path, language, pages)
        os.unlink(tmp)
        if result["ok"]:
            return FileResponse(out_path, media_type="application/pdf",
                                filename=f"hybrid_{file.filename}",
                                headers={"X-OCR-Engine": result.get("engine", ""),
                                         "X-OCR-Confidence": str(result.get("avg_confidence", 0)),
                                         "X-OCR-Size": str(result.get("size_bytes", 0))})
        return {"error": result.get("error", "Hybrid OCR failed")}

    structured = output == "structured"
    result = ocr.ocr_pdf_to_text(tmp, language, pages, structured=structured)
    os.unlink(tmp)

    if output == "text":
        full_text = "\n\n".join(f"--- Page {p['page']} ---\n{p['text']}" for p in result["pages"])
        return Response(full_text, media_type="text/plain")
    return result


@router.post("/jobs")
async def ocr_create_job(
    file: Optional[UploadFile] = File(None),
    file_url: Optional[str] = Form(None),
    language: str = Form("eng"),
    output: str = Form("searchable_pdf"),
    pages: str = Form(""),
    optimize: int = Form(3),
    force_ocr: bool = Form(False),
):
    """Create an async OCR job for large PDFs.
    optimize: 0=none, 1=lossless, 2=lossy, 3=aggressive (smallest output).
    force_ocr: True=re-OCR all pages, False=skip pages with existing text (default, smaller output)."""
    import tempfile
    import httpx

    if file and file.filename:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False, dir=str(ocr.JOBS_DIR)) as f:
            f.write(await file.read())
            tmp = f.name
    elif file_url:
        # SSRF protection: only allow http(s) to non-internal IPs
        from urllib.parse import urlparse
        parsed = urlparse(file_url)
        if parsed.scheme not in ("http", "https"):
            return {"error": "Only http/https URLs allowed"}
        host = parsed.hostname or ""
        if host in ("localhost", "127.0.0.1", "0.0.0.0") or host.startswith("169.254.") or host.startswith("10.") or host.startswith("192.168."):
            return {"error": "Internal URLs not allowed"}
        # 172.16.0.0 - 172.31.255.255 are private (not 172.0-172.15)
        if host.startswith("172."):
            try:
                second = int(host.split(".")[1])
                if 16 <= second <= 31:
                    return {"error": "Internal URLs not allowed"}
            except (ValueError, IndexError):
                pass
            return {"error": "Internal URLs not allowed"}
        async with httpx.AsyncClient(timeout=120, follow_redirects=False) as c:
            r = await c.get(file_url)
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False, dir=str(ocr.JOBS_DIR)) as f:
                f.write(r.content)
                tmp = f.name
    else:
        return {"error": "Provide file or file_url"}

    job_id = ocr.create_job(tmp, language, output, pages)
    asyncio.create_task(ocr.run_job(job_id))
    return ocr.get_job(job_id)


@router.get("/jobs/{job_id}")
async def ocr_job_status(job_id: str):
    job = ocr.get_job(job_id)
    if not job:
        return {"error": "Job not found"}
    return {k: v for k, v in job.items() if k != "file_path"}


@router.get("/jobs/{job_id}/result")
async def ocr_job_result(job_id: str):
    job = ocr.get_job(job_id)
    if not job or job["status"] != "complete" or not job.get("result_path"):
        return {"error": "Job not complete"}

    path = job["result_path"]
    if not os.path.exists(path):
        return {"error": "Result file already cleaned up"}

    # Read into memory, delete file, return response
    with open(path, "rb") as f:
        data = f.read()
    os.unlink(path)
    ocr._update_job(job_id, status="delivered")

    media = "application/pdf" if path.endswith(".pdf") else "application/json"
    return Response(data, media_type=media,
                    headers={"Content-Disposition": f"attachment; filename={job_id}.pdf"})


# Compat: BC tries to GET the raw file path
compat_router = APIRouter(tags=["ocr-compat"])


@compat_router.get("/data/ocr_jobs/{filename}")
async def serve_ocr_file(filename: str):
    """Serve OCR result files directly (BC compat). Deletes after download."""
    import re
    safe = re.sub(r'[^a-zA-Z0-9._-]', '', filename)
    if not safe or safe != filename or '..' in filename:
        return Response("Forbidden", status_code=403)
    path = os.path.join("/data/ocr_jobs", safe)
    if not os.path.isfile(path):
        return Response("Not found", status_code=404)

    with open(path, "rb") as f:
        data = f.read()
    os.unlink(path)

    media = "application/pdf" if safe.endswith(".pdf") else "application/json"
    return Response(data, media_type=media)
