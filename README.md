# PDF Fixer

A small Flask dashboard that cleans garbled medical MCQ PDFs (MARROW ED8
series) before any extraction runs. Works on **Render** (recommended, see
below) and **Railway**, fully via Docker.

**One job, one output: a CLEAN PDF.** The dashboard does one thing by
default and one thing optionally:

1. **Removes the watermark** — generic, works for **any PDF / any repeated
   watermark**, not just the itachibot series. Pages are kept exactly as
   uploaded (no re-render, no re-encode), so the output is visually identical
   and stays near the original file size. Detection is multi-signal and
   confidence-gated (repetition ≥90% of pages, position, size, opacity,
   rotation, geometry); a repeated object is **not** automatically a
   watermark. Channels:
   - **full-page image families** — the same watermark is often stored as
     several pixel variants (e.g. 82% + 18% of pages); all full-page
     variants whose union covers ≥90% of the file are one family and all are
     removed;
   - **unique-per-page raster overlays** — some tools bake the watermark
     into a NEW raster per page (different pixels each page). When full-page
     images cover ≥98% of pages AND those pages also carry visible vector
     content AND the images are rotated or light-gray (stamp-like, ≤1% ink),
     every full-page image is removed as one watermark family;
   - **same-position images** repeated on ≥90% of pages covering ≥25% of the
     page area (diagonal grey banners);
   - **full-page Form XObjects** repeated on ≥90% of pages (vector-text /
     painted-band watermarks);
   - **inline images** (`BI … EI`) repeated across pages;
   - **watermark text** — known strings ("Sold by", "itachibot", "you
     purchased", "not for distribution", …) plus any text span repeated on
     ≥90% of pages that is rotated, large, or known: removed from the
     content streams and redacted visually. A same-**position** text family
     (same diagonal region on ≥90% of pages even when the wording differs,
     e.g. "… - page 123") is redacted at its exact bbox on every page;
   - **invisible / low-alpha text** — text drawn with render mode `3 Tr`
     (invisible) or alpha `< 0.5` that recurs on ≥90% of pages is removed
     **state-checked**: only the hidden-state ops are dropped, so an
     identical *visible* string is never damaged;
   - **repeated vector paths** — identical path geometry repeated on ≥90% of
     pages at one position, when low-alpha (area ≥10%) or large (area
     ≥25%); full-page frames and margin furniture are excluded;
   - **raster-baked watermarks** — when full-page bitmaps cover (almost)
     every page and nothing else proves a removable object, the watermark is
     likely burned INTO the pixels. The app builds a per-pixel consensus
     mask (same normalized pixel is a light-gray overlay on ≥75% of sampled
     pages), carves out solid gray figures/columns, dark content and margin
     furniture, then fills those watermark pixels with the page's paper tone
     and re-encodes the page image as JPEG (no geometry change, no
     re-render). This also handles slide decks that keep a searchable or
     invisible-OCR text layer mentioning the watermark, or pages with
     visible text on top of a background bitmap.
   - **watermark-associated annotations & layers** — URI link annotations
     whose URI contains a detected watermark string (or whose rect covers
     ≥80% of a redacted watermark span) are removed *with* the watermark;
     every other link (GoTo, TOC, citations, navigation) is never touched.
     Optional Content Groups (layers) are inspected; only an OCG whose name
     is watermark-like **and** is OFF by default (a hidden layer) is
     trimmed. Visible layers are logged only.

   Legitimate content is always protected: small corner logos, one-off
   figures, tables, page numbers and header/footer furniture stay untouched,
   and an image-only scan with **no provable watermark pattern** is refused
   with a clear message instead of being damaged. After each job the output
   is compared against the input (page count, page dimensions, images,
   links, annotations, text length); page count/dimensions changes fail the
   job.
2. **OPTIONAL — rebuilds the broken text layer with OCR**
   (`ocrmypdf --force-ocr`, English + Hindi, with a pytesseract fallback).
   **Off by default**: OCR re-renders every page at high DPI, so the file is
   typically many times larger than the upload, and on low-DPI scans (like
   55 DPI iLovePDF outputs) the recognized words are often wrong. Only tick
   "Rebuild text layer with OCR" if you truly need a searchable layer.

There is **no database, no JSON/QBank/Gemini pipeline** in this app.
`fix_pdf.py` does all the PDF work; `app.py` is only the upload → progress
→ download UI.

## Deploying

### Render (recommended)

The app is a plain Docker web service that listens on `0.0.0.0:$PORT`
(Render sets `PORT`; `8080` is only the fallback). No persistent disk is
required — job files are temporary processing artifacts (see
[Storage behavior](#storage-behavior)).

**Option A — blueprint:** the repo contains a minimal `render.yaml`
(web service, Docker runtime, free plan, health check `/health`). On Render:
*New +* → *Web Service* → *Deploy from Git repo* → pick the repo. Render
pre-fills the settings.

**Option B — manual:**

| Setting | Value |
|---|---|
| Service type | Web Service |
| Runtime | Docker (uses `./Dockerfile`; no build command needed) |
| Plan | Free (or any) |
| Health check path | `/health` |
| Environment variables | none required (all have safe defaults) |
| Disk / persistent volume | not required |
| Start command | (from Dockerfile) `gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 1 --threads 4 --timeout 0 app:app` |
| Build command | none (Dockerfile) |

Free-tier caveats: the instance sleeps after ~15 min idle (first request
after a sleep pays a boot delay) and has 512 MB RAM — the no-OCR default
path is light, but OCR on large scans can hit the memory limit; the job
then fails cleanly with an OOM explanation (never corrupts the upload).

### Railway

Same image, same behavior. If you attach a Railway volume at `/data` the
job files land there (`PDF_FIX_JOBS_DIR=/data/pdf_fix_jobs` is the Docker
default); without a volume they still work on the local disk. Nothing in the
code is Railway-specific anymore (the old platform-specific CLI default was
removed; `fix_pdf.py` now requires an explicit input path).

### Local (no Docker)

```bash
apt-get update && apt-get install -y \
  poppler-utils tesseract-ocr tesseract-ocr-hin ghostscript unpaper
pip install -r requirements.txt
gunicorn --bind 0.0.0.0:8080 --workers 1 --threads 4 --timeout 0 app:app
# or: python app.py  (dev server, same behaviour)
```

### Docker

```bash
docker build -t pdf-fixer .
docker run -p 8080:8080 -e PORT=8080 pdf-fixer
```

System packages are only the ones the code actually calls:
`poppler-utils` (pdftotext, output verification), `tesseract-ocr`
+ `tesseract-ocr-hin` (OCR), `ghostscript` (PDF/A), `unpaper` (optional
`--clean`).

## Env vars

Names only — the app has no API keys or credentials; nothing secret is
ever configured, logged or stored.

| Var | Default | Meaning |
|---|---|---|
| `PORT` | `8080` | listen port (set by Render) |
| `PDF_FIX_JOBS_DIR` | `/data/pdf_fix_jobs` (Docker) / `./pdf_fix_jobs` | job workspace root (temporary files) |
| `PDF_FIX_MAX_CONCURRENT` | `1` | max parallel jobs (keep 1 on 512 MB plans) |
| `PDF_FIX_MAX_JOB_KEEP` | `20` | job folders kept on disk |
| `PDF_FIX_MAX_UPLOAD_MB` | `200` | upload size cap |
| `PDF_FIX_OCR_JOBS` | `1` | default tesseract workers per job (clamped to CPU count) |
| `PDF_FIX_OUTPUT_TYPE` | `pdfa` | default output type (`pdfa` or `pdf`) |
| `PDF_FIX_JOB_TIMEOUT` | `0` (off) | optional hard per-job cap in seconds; a wedged job is terminated and reported |

> **Memory (OCR only):** OCR is RAM-hungry. On 512 MB plans keep
> `PDF_FIX_MAX_CONCURRENT=1`, `PDF_FIX_OCR_JOBS=1`, leave "Clean" unchecked
> and use `PDF_FIX_OUTPUT_TYPE=pdf` if you see `exit code -9` (the kernel's
> out-of-memory kill). The app sets `OMP_THREAD_LIMIT=1` so every tesseract
> process uses one thread. The default no-OCR path uses PyMuPDF only and is
> light on memory.

## Storage behavior

- Each job gets `PDF_FIX_JOBS_DIR/<16-hex-uuid>/` with `input.pdf`,
  `step1_no_watermark.pdf`, `output_clean.pdf`. The id is server-generated
  (no user-controlled filenames reach the filesystem; uploads are also
  passed through `secure_filename` and validated against the `%PDF-`
  header).
- These files are needed **only while the job runs and until you download
  the result**. There is no database and no persistent state, so on
  platforms with an ephemeral filesystem (Render Free) a restart loses
  in-flight jobs (they reappear as errors on the next boot) but nothing
  valuable — old folders are pruned at startup and after each upload,
  bounded by `PDF_FIX_MAX_JOB_KEEP`. Interrupted/cancelled/failed jobs are
  pruned the same way; temp PDFs cannot accumulate.
- Duplicate filenames are impossible (uuid dirs); concurrent uploads queue
  on `PDF_FIX_MAX_CONCURRENT`; a bad PDF can never take the web worker down
  (per-job subprocess).
- If you want finished outputs to survive restarts, point
  `PDF_FIX_JOBS_DIR` at a mounted volume on either platform.

## Dashboard

- Upload a PDF (max 200 MB by default)
- Watermark removal runs automatically. **OCR is a checkbox, unchecked by
  default** — leave it off to get an upload-like file. If you tick it you
  can pick OCR language, parallel jobs, output type (PDF/A or PDF),
  deskew/clean
- Watch the live log; when done, **Download CLEAN PDF** (or preview it, or
  grab the `step1_no_watermark.pdf` intermediate)
- Cancel a running job with one click
- `/health` returns JSON (used as the Render health check)

API: `GET /`, `GET /job/<id>`, `GET /api/jobs`, `GET /api/jobs/<id>`,
`POST /upload`, `POST /api/jobs/<id>/cancel`, `GET
/download/<id>/clean|step1`, `GET /preview/<id>`, `GET /health`.

## CLI (outside the dashboard)

```bash
python fix_pdf.py input.pdf                       # watermark removal only
python fix_pdf.py input.pdf --ocr                 # add OCR text layer
python fix_pdf.py input.pdf --ocr --language eng --jobs 4
```

Inputs that are not valid PDFs are rejected with a clear error.
Password-protected PDFs are **refused** — passwords are never bypassed;
provide a decrypted copy you are authorized to process.

## Verification

After each job the log shows a step-3 summary: pages, file size
before/after, sample-page quality, watermark-string count (must be 0) and a
PASS/FAIL verdict, plus a **before/after comparison** (page count, page
dimensions, images, links, annotations, text length — count/dimensions
changes flip the verdict to FAIL) and a **detection report** listing which
channels fired and with which signals.

## Tests

```bash
pip install -r requirements-dev.txt   # pytest
python -m pytest tests/ -q
```

23 tests cover the full workflow (upload → process → download via the real
Flask app + gunicorn), 17 synthetic watermark/legitimacy/security fixtures
generated at test time, and the graceful-failure cases. Fixtures are built
with `tests/pdfgen.py` (a minimal raw-PDF writer) so each test controls the
exact PDF structure it exercises. The suite runs in a clean container
(baseline: `python:3.13` + `pip install -r requirements.txt
requirements-dev.txt` + the apt packages listed above; no Docker-specific
tooling).

## Tested vs theoretical

**Implemented and tested** (see `tests/`):

| Case | Status |
|---|---|
| Normal text watermark (known string, repeated) | ✅ removed, body preserved |
| Rotated / diagonal text watermark | ✅ removed |
| Semi-transparent (alpha < 0.5) repeated text | ✅ removed (hidden-text channel) |
| Full-page image watermark (shared XObject) | ✅ removed |
| Transparent (SMask) image watermark at same position | ✅ removed |
| Repeated vector path watermark (low alpha) | ✅ removed |
| Watermark repeated across many pages (12–20) | ✅ removed, all pages |
| Watermark with a hyperlink on it | ✅ text removed, watermark URI link removed, other links kept |
| Invisible (`3 Tr`) watermark + visible identical string | ✅ invisible removed, visible copy preserved |
| Legitimate hyperlinks (external + internal GoTo) | ✅ preserved when watermark present |
| Legitimate corner logo image | ✅ preserved |
| Tables + selectable text | ✅ table lines & cell text preserved |
| Image-only scan without provable watermark | ✅ refused, file untouched |
| Malformed PDFs (garbage, header-only, truncated) | ✅ clear error / graceful repair, never a traceback |
| Password-protected PDF | ✅ refused with clear message, never bypassed |
| Watermark-named OCG off by default | ✅ trimmed; visible OCGs & legitimate OCGs kept |
| Dashboard workflow (upload → poll → download → preview) | ✅ end-to-end incl. concurrent jobs |
| Health endpoint, invalid-upload rejection | ✅ |

**Implemented, theoretically supported, not exhaustively tested** (real-world
PDFs are unbounded; these paths exist but have only limited coverage):

- Raster-baked (in-pixel) watermarks — the consensus-mask code path runs in
  production but has no synthetic fixture here (it needs realistic scanned
  pages); behavior on exotic scans may still require a refusal.
- Watermark text using exotic font encodings (broken CMaps) — byte-level
  matching falls back to MuPDF text search + redaction, which can be
  imperfect for heavily encoded fonts.
- Watermark content inside Form XObjects with unusual nesting, or watermarks
  expressed only via `BDC/EMC` marked-content sequences.
- OCG content that is ON by default (visible layer named like a watermark):
  the layer is kept and its content is only removed if the other channels
  independently detect it.

**Known limitations / honest refusals:**

- Watermarks whose pixels are indistinguishable from page content (no
  repetition, no opacity/size/position signal) are **not** detected — the
  app refuses rather than guess, so a clean file can never be damaged.
- Redacting a text watermark also removes any legitimate text that sits
  *inside* the watermark's exact bbox (inherent to visual redaction).
- Invisible-text detection decodes simple font encodings (latin-1/UTF-16);
  binary CID payloads are skipped (undecodable → not removed, not damaged).
- The MuPDF build in this image logs a harmless `unknown keyword: 'CA'`
  warning when a stream uses direct `ca`/`CA` operators; alpha via
  ExtGState (`gs`) is fully supported. Detection of such watermarks reads
  the operators from the stream, so it is unaffected.
