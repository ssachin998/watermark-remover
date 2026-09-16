FROM python:3.11-slim

# System dependencies required by the code (determined from fix_pdf.py /
# app.py, not extras):
#   poppler-utils      pdftotext (output verification in fix_pdf.py step 3)
#   tesseract-ocr      OCR engine (optional --ocr text-layer rebuild)
#   tesseract-ocr-hin  Hindi OCR pack (fix_pdf.py --language eng+hin)
#   ghostscript        PDF/A conversion + ocrmypdf postprocessing
#   unpaper            optional, enables ocrmypdf --clean (scan cleanup)
RUN apt-get update && apt-get install -y \
        poppler-utils tesseract-ocr tesseract-ocr-hin ghostscript unpaper \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# PDF Fixer only -- no QBank/JSON pipeline code.
COPY app.py fix_pdf.py ./
ENV PYTHONUNBUFFERED=1
# Job directories (uploaded PDF + intermediate + clean output).  These are
# TEMPORARY processing files, needed only while a job runs: on Railway a
# volume is mounted at /data; on Render the default filesystem is ephemeral
# (no volume needed - old folders are pruned at boot and per upload).  Point
# it at a mounted volume on either platform if you want to keep outputs.
ENV PDF_FIX_JOBS_DIR=/data/pdf_fix_jobs
# Max OCR processes running at once (each job = one fix_pdf.py subprocess).
# Keep at 1 on small plans: OCR is RAM-hungry and 2 concurrent runs on a
# 512 MB container get OOM-killed (SIGKILL / exit code -9).
ENV PDF_FIX_MAX_CONCURRENT=1
# OCRmyPDF default jobs (bounded internally by CPU count; 1 is the safe
# default and can be raised from the dashboard drop-down).
ENV PDF_FIX_OCR_JOBS=1
# Keep this many finished job folders on disk.
ENV PDF_FIX_MAX_JOB_KEEP=20

EXPOSE 8080
# Gunicorn avoids Flask's development-server warning and is safe for Render /
# Railway.  The server binds 0.0.0.0 and honours $PORT (Render sets PORT;
# 8080 is only the fallback).  One worker is intentional: the dashboard keeps
# in-memory run state and must not allow separate workers to start concurrent
# writes to the same job directory.  --timeout 0: long OCR jobs must not be
# killed by the worker timeout (each job is a subprocess, workers stay idle).
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 1 --threads 4 --timeout 0 app:app"]
