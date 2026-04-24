#!/bin/sh
# Fix data dir permissions (volume may be owned by root from previous runs)
mkdir -p /data/ocr_jobs
chown -R intello:intello /data 2>/dev/null || true

# Drop to non-root user and run
exec gosu intello uvicorn intello.web:app --host 0.0.0.0 --port 8000
