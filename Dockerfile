FROM python:3.12-slim

# Install Tesseract OCR + language packs + PDF tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-fra tesseract-ocr-deu tesseract-ocr-spa \
    tesseract-ocr-ita tesseract-ocr-por tesseract-ocr-nld \
    tesseract-ocr-rus \
    ghostscript \
    poppler-utils \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "intello.web:app", "--host", "0.0.0.0", "--port", "8000"]
