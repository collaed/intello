#!/usr/bin/env python3
"""Launch the AI Router web interface."""
import uvicorn

if __name__ == "__main__":
    print("🚀 Starting AI Router web UI at http://localhost:8000")
    uvicorn.run("intello.web:app", host="0.0.0.0", port=8000, reload=True)
