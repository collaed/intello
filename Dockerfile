FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-fra tesseract-ocr-deu tesseract-ocr-spa \
    tesseract-ocr-ita tesseract-ocr-por tesseract-ocr-nld \
    tesseract-ocr-rus \
    ghostscript \
    poppler-utils \
    libgl1 \
    wget \
    unpaper \
    && rm -rf /var/lib/apt/lists/*

# Install Piper TTS
RUN mkdir -p /opt/piper && \
    wget -qO- https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_x86_64.tar.gz | tar xz -C /opt/piper --strip-components=1 && \
    mkdir -p /opt/piper/voices

# Download EN + FR voices
RUN wget -q -O /opt/piper/voices/en_US-lessac-medium.onnx https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx && \
    wget -q -O /opt/piper/voices/en_US-lessac-medium.onnx.json https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json && \
    wget -q -O /opt/piper/voices/fr_FR-siwis-medium.onnx https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx && \
    wget -q -O /opt/piper/voices/fr_FR-siwis-medium.onnx.json https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx.json

ENV PATH="/opt/piper:${PATH}"

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m spacy download en_core_web_sm
COPY . .

# Run as non-root user
RUN useradd -m -u 1000 intello && \
    mkdir -p /data && chown intello:intello /data && \
    chown -R intello:intello /opt/piper
USER intello

EXPOSE 8000
CMD ["uvicorn", "intello.web:app", "--host", "0.0.0.0", "--port", "8000"]
