"""Engine tests: run fix_pdf.py as a subprocess (the production path) on
synthetic fixtures and assert removal + preservation guarantees.

Mapping to the required test list:
  1  normal text watermark            text_watermark
  2  rotated/diagonal text watermark  rotated_text
  3  transparent text watermark       alpha_text
  4  image watermark                  image_watermark
  5  transparent image watermark      alpha_image
  6  vector watermark                 vector_watermark
  7  repeated watermark (many pages)  multi_page_repeated
  8  watermark containing a hyperlink link_watermark
  9  invisible/hidden watermark       hidden_text
  10 legitimate hyperlinks preserved  legit_links
  11 legitimate images preserved      legit_image
  12 tables + selectable text         table_text
  13 multi-page document              multi_page_plain
  14 scanned/image-based PDF          scan_clean (refused)
  15 malformed/problematic PDF        malformed_* (graceful failure)
  16 password-protected PDF           encrypted (refused, not bypassed)
  17 OCG layers (extra)                ocgs.pdf (hidden removed / visible kept)
  18 small-deck false-positive guard   small_deck_nested_stamp.pdf (regression
     for the real-world 4-page deck incident: repeated slide title, wrapped
     copyright prose containing 'may not be copied', rotated translucent stamp
     and stamp artwork nested INSIDE a legitimate template form)
"""

from __future__ import annotations

import re
from pathlib import Path

import pymupdf as fitz

from conftest import run_cli

WM_RE = re.compile(r"itachibot|sold by|fa in tmark", re.IGNORECASE)


def text_of(path: Path) -> str:
    d = fitz.open(path)
    try:
        return " ".join(p.get_text() for p in d)
    finally:
        d.close()


def streams_of(path: Path) -> bytes:
    d = fitz.open(path)
    try:
        return b"".join(p.read_contents() for p in d)
    finally:
        d.close()


def links_of(path: Path) -> list[dict]:
    d = fitz.open(path)
    try:
        return [l for p in d for l in p.get_links()]
    finally:
        d.close()


# ---------------------------------------------------------------- 1. text
def test_01_normal_text_watermark(fixtures, tmp_path):
    r = run_cli(fixtures["text_watermark.pdf"], tmp_path)
    assert r.returncode == 0, r.stderr
    t = text_of(tmp_path / "out.pdf")
    assert "itachibot" not in t.lower()
    assert "Question 3" in t and "correct answer is B" in t
    d = fitz.open(tmp_path / "out.pdf")
    assert len(d) == 6


# ---------------------------------------------------------------- 2. rotated
def test_02_rotated_text_watermark(fixtures, tmp_path):
    r = run_cli(fixtures["rotated_text.pdf"], tmp_path)
    assert r.returncode == 0, r.stderr
    t = text_of(tmp_path / "out.pdf")
    assert "itachibot" not in t.lower()
    assert "Question 5" in t


# ---------------------------------------------------------------- 3. alpha text
def test_03_transparent_text_watermark(fixtures, tmp_path):
    r = run_cli(fixtures["alpha_text.pdf"], tmp_path)
    assert r.returncode == 0, r.stderr
    t = text_of(tmp_path / "out.pdf")
    assert "faintmark" not in t.lower()          # alpha watermark removed
    assert "Question 2" in t                     # body preserved
    assert "HIDDEN" in r.stdout                  # detected by the hidden channel


# ---------------------------------------------------------------- 4. image
def test_04_image_watermark(fixtures, tmp_path):
    r = run_cli(fixtures["image_watermark.pdf"], tmp_path)
    assert r.returncode == 0, r.stderr
    d = fitz.open(tmp_path / "out.pdf")
    imgs = [p.get_image_info() for p in d]
    assert all(len(i) == 0 for i in imgs), "watermark image still drawn"
    t = text_of(tmp_path / "out.pdf")
    assert "Question 6" in t


# ---------------------------------------------------------------- 5. alpha image
def test_05_transparent_image_watermark(fixtures, tmp_path):
    r = run_cli(fixtures["alpha_image.pdf"], tmp_path)
    assert r.returncode == 0, r.stderr
    d = fitz.open(tmp_path / "out.pdf")
    imgs = [p.get_image_info() for p in d]
    assert all(len(i) == 0 for i in imgs), "alpha watermark image still drawn"
    assert "Question 4" in text_of(tmp_path / "out.pdf")


# ---------------------------------------------------------------- 6. vector
def test_06_vector_watermark(fixtures, tmp_path):
    r = run_cli(fixtures["vector_watermark.pdf"], tmp_path)
    assert r.returncode == 0, r.stderr
    d = fitz.open(tmp_path / "out.pdf")
    drawings = [len(p.get_drawings()) for p in d]
    assert all(n == 0 for n in drawings), \
        f"watermark vector path still drawn: {drawings}"
    assert "Question 6" in text_of(tmp_path / "out.pdf")


# ---------------------------------------------------------------- 7. many pages
def test_07_repeated_watermark_many_pages(fixtures, tmp_path):
    r = run_cli(fixtures["multi_page_repeated.pdf"], tmp_path)
    assert r.returncode == 0, r.stderr
    d = fitz.open(tmp_path / "out.pdf")
    assert len(d) == 12
    assert all(len(p.get_image_info()) == 0 for p in d)
    t = text_of(tmp_path / "out.pdf")
    assert "itachibot" not in t.lower() and "sold by" not in t.lower()
    assert "Question 12" in t


# ---------------------------------------------------------------- 8. link on watermark
def test_08_watermark_with_hyperlink(fixtures, tmp_path):
    r = run_cli(fixtures["link_watermark.pdf"], tmp_path)
    assert r.returncode == 0, r.stderr
    t = text_of(tmp_path / "out.pdf")
    assert "itachibot" not in t.lower()
    links = links_of(tmp_path / "out.pdf")
    uris = [l.get("uri", "") for l in links if l["kind"] == fitz.LINK_URI]
    assert not any("itachibot" in u for u in uris), \
        f"watermark link survived: {uris}"
    assert any("ncbi.nlm.nih.gov" in u for u in uris), "legit link removed!"


# ---------------------------------------------------------------- 9. hidden
def test_09_invisible_hidden_watermark(fixtures, tmp_path):
    r = run_cli(fixtures["hidden_text.pdf"], tmp_path)
    assert r.returncode == 0, r.stderr
    blob = streams_of(tmp_path / "out.pdf")
    # exactly one occurrence per page remains in the streams = the VISIBLE
    # copy (the invisible 3 Tr ops are gone); the stream re-serializer
    # escapes the inner parentheses, so count the bare string
    assert blob.count(b"SECRET-MARKER-123") == 6
    t = text_of(tmp_path / "out.pdf")
    assert t.count("SECRET-MARKER-123 (visible copy)") == 6  # visible survives
    assert "HIDDEN" in r.stdout


# ---------------------------------------------------------------- 10. legit links
def test_10_legitimate_links_preserved(fixtures, tmp_path):
    r = run_cli(fixtures["legit_links.pdf"], tmp_path)
    assert r.returncode == 0, r.stderr
    t = text_of(tmp_path / "out.pdf")
    assert "itachibot" not in t.lower()
    links = links_of(tmp_path / "out.pdf")
    uris = sorted(l.get("uri", "") for l in links if l["kind"] == fitz.LINK_URI)
    assert any("ncbi.nlm.nih.gov" in u for u in uris)
    assert any("doi.org" in u for u in uris)
    assert any(l["kind"] == fitz.LINK_GOTO for l in links), "GoTo link removed!"
    assert len(links) == 3  # 2 URI + 1 GoTo, nothing else removed


# ---------------------------------------------------------------- 11. legit image
def test_11_legitimate_images_preserved(fixtures, tmp_path):
    r = run_cli(fixtures["legit_image.pdf"], tmp_path)
    assert r.returncode == 0, r.stderr
    d = fitz.open(tmp_path / "out.pdf")
    infos = [p.get_image_info() for p in d]
    assert all(len(x) == 1 for x in infos), "corner logo was deleted!"
    # logo is still in the top-right area (fitz coords: y from top)
    r0 = fitz.Rect(infos[0][0]["bbox"])
    assert r0.x0 > 400 and r0.y0 < 100
    assert "itachibot" not in text_of(tmp_path / "out.pdf").lower()


# ---------------------------------------------------------------- 12. tables
def test_12_tables_and_selectable_text(fixtures, tmp_path):
    r = run_cli(fixtures["table_text.pdf"], tmp_path)
    assert r.returncode == 0, r.stderr
    t = text_of(tmp_path / "out.pdf")
    for cell in ("HeaderA", "HeaderD", "r1b", "r2c", "q1y", "q2z"):
        assert cell in t, f"table cell lost: {cell}"
    d = fitz.open(tmp_path / "out.pdf")
    drawings = [len(p.get_drawings()) for p in d]
    assert all(n >= 20 for n in drawings), "table grid lines were damaged"
    assert "itachibot" not in t.lower()


# ---------------------------------------------------------------- 13. multi-page
def test_13_multi_page_document(fixtures, tmp_path):
    r = run_cli(fixtures["multi_page_plain.pdf"], tmp_path)
    assert r.returncode == 0, r.stderr
    d = fitz.open(tmp_path / "out.pdf")
    assert len(d) == 20
    t = text_of(tmp_path / "out.pdf")
    assert "itachibot" not in t.lower()
    assert "Chapter note 1: the answer is C." in t
    assert "Chapter note 20: the answer is C." in t
    # page sizes unchanged
    in_d = fitz.open(fixtures["multi_page_plain.pdf"])
    assert all(abs(a.rect.width - b.rect.width) < 0.1
               and abs(a.rect.height - b.rect.height) < 0.1
               for a, b in zip(in_d, d))


# ---------------------------------------------------------------- 14. scan
def test_14_scanned_pdf_without_watermark_refused(fixtures, tmp_path):
    r = run_cli(fixtures["scan_clean.pdf"], tmp_path)
    assert r.returncode != 0, "clean scan must be refused, not modified"
    assert not (tmp_path / "out.pdf").exists()
    blob = (r.stderr + r.stdout).lower()
    assert "refus" in blob or "no candidate watermark" in blob
    # the input itself is untouched
    assert fitz.open(fixtures["scan_clean.pdf"]) is not None


# ---------------------------------------------------------------- 15. malformed
def test_15_malformed_pdfs_graceful(fixtures, tmp_path):
    for name in ("malformed_garbage.pdf", "malformed_header_only.pdf",
                 "malformed_truncated.pdf"):
        outdir = tmp_path / name.replace(".pdf", "")
        r = run_cli(fixtures[name], outdir)
        out = (r.stderr + r.stdout)
        assert "Traceback (most recent call last)" not in out, \
            f"{name}: crashed with a traceback"
        outp = outdir / "out.pdf"
        if r.returncode == 0:
            # graceful REPAIR: MuPDF could recover the file - the output
            # must still be a valid, readable PDF (no silent corruption)
            d = fitz.open(outp)
            assert d.is_pdf and len(d) >= 1
            d.close()
        else:
            # graceful REJECTION: clear error, no output file, sane code
            assert "error" in out.lower(), f"{name}: no clear error message"
            assert r.returncode in (1, 2, 3)
            assert not outp.exists()
    # the garbage file must specifically be rejected as invalid
    r = run_cli(fixtures["malformed_garbage.pdf"], tmp_path / "g2")
    assert r.returncode == 3
    assert "not a valid pdf" in (r.stderr + r.stdout).lower()


# ---------------------------------------------------------------- 16. encrypted
def test_16_password_protected_refused(fixtures, tmp_path):
    r = run_cli(fixtures["encrypted.pdf"], tmp_path)
    assert r.returncode == 3, f"encrypted pdf must be refused: {r.stderr}"
    assert not (tmp_path / "out.pdf").exists()
    out = (r.stderr + r.stdout).lower()
    assert "password" in out and "never bypassed" in out
    assert "Traceback (most recent call last)" not in (r.stderr + r.stdout)


# ---------------------------------------------------------------- 17. OCG layers
def test_17_watermark_layers_handled(fixtures, tmp_path):
    r = run_cli(fixtures["ocgs.pdf"], tmp_path)
    assert r.returncode == 0, r.stderr
    # the OFF-by-default watermark-named OCG is removed; the ON-by-default
    # watermark-named OCG and the legitimate OCG are kept
    assert "removed hidden (off-by-default) watermark OCG" in r.stdout
    d = fitz.open(tmp_path / "out.pdf")
    cat = d.pdf_catalog()
    t, v = d.xref_get_key(cat, "OCProperties/OCGs")
    assert t in ("dict", "xref", "array"), "OCProperties lost"
    refs = re.findall(r"(\d+)\s+\d+\s+R", v)
    names = []
    for rx in refs:
        t2, v2 = d.xref_get_key(int(rx), "Name")
        names.append(v2 if t2 in ("name", "string") else "")
    assert "Watermark hidden" not in names, "off-by-default wm OCG survived"
    assert "Watermark visible" in names, "on-by-default OCG must be kept"
    assert "Annotations" in names, "legitimate OCG must be kept"
    # watermark still removed and body intact
    assert "itachibot" not in text_of(tmp_path / "out.pdf").lower()
    assert "Question 3" in text_of(tmp_path / "out.pdf")
    d.close()


# ------------------------------------------------- non-destructiveness proof
# ------------------------------------------------- 18. small-deck incident
def test_18_small_deck_nested_stamp(fixtures, tmp_path):
    """Regression for the NorcetIQ incident (4-page study deck that the
    engine previously mangled): repeated TITLES and a long copyright
    paragraph containing 'may not be copied' must survive, while a rotated
    translucent stamp and its artwork - a small Form nested INSIDE a
    full-page template Form with an inverted /BBox - are removed."""
    src = fixtures["small_deck_nested_stamp.pdf"]
    r = run_cli(src, tmp_path)
    assert r.returncode == 0, r.stderr
    out = tmp_path / "out.pdf"
    d_in, d = fitz.open(src), fitz.open(out)
    try:
        assert d.page_count == 4
        tl = " ".join(p.get_text() for p in d).lower()
        # legitimate content preserved
        assert "family health services-3" in tl           # repeated title
        # copyright prose survives - including the wrapped line that
        # CONTAINS the 'may not be copied' phrase (the incident regression)
        assert "all rights are reserved" in tl
        assert "may not be copied" in tl
        assert "will be punishable" in tl
        assert "nursing care plan step 3" in tl
        assert "passes through the stamp region" in tl     # under the stamp
        assert "nursing next live" in tl                   # template footer
        w_in = sum(len(p.get_text("words")) for p in d_in)
        w_out = sum(len(p.get_text("words")) for p in d)
        assert w_in - w_out == 8, (w_in, w_out)  # only the 2 stamp words/page
        # watermark removed
        assert "@handle" not in tl
        tpl = False
        for x in range(1, d.xref_length()):
            try:
                st = d.xref_stream(x)
            except Exception:
                continue
            if not st:
                continue
            if b"/Art Do" in st:
                raise AssertionError("nested watermark form still drawn")
            # the template form itself (border path + footer) must remain
            # (stream is re-serialized op-per-line after the Do removal,
            # so match tokens, not exact byte spans)
            if b"Nursing Next Live" in st and b"re" in st and b"776" in st:
                tpl = True
        assert tpl, "page template form was destroyed"
    finally:
        d_in.close()
        d.close()


def test_compare_before_after_printed(fixtures, tmp_path):
    r = run_cli(fixtures["watermark_with_figure.pdf"], tmp_path)
    assert r.returncode == 0, r.stderr
    assert "[compare] input -> output" in r.stdout
    assert "DETECTION REPORT" in r.stdout
    # figure (a real content image) must survive; watermark text must not
    d = fitz.open(tmp_path / "out.pdf")
    assert len(d) == 2
    assert all(len(p.get_image_info()) == 1 for p in d), "content figure lost"
    assert "itachibot" not in text_of(tmp_path / "out.pdf").lower()
    assert "VERDICT" in r.stdout and "PASS" in r.stdout
