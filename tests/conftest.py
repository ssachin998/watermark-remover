"""Shared fixtures: generate the test PDFs and run the CLI."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tests"))

import pdfgen  # noqa: E402
from pdfgen import (  # noqa: E402
    body_line, content_figure_jpeg, draw_at, draw_full_image,
    draw_rect_image, encrypt_pdf, extra_num, extgstate_object, font_object,
    form_object, goto_link_annot, image_object, logo_jpeg, make_pdf,
    photo_jpeg, smask_object, smask_pair, gray_stamp_jpeg, text_show,
    uri_link_annot,
)

FIX = "itachibot"  # known watermark needle used in most fixtures


def _font_resources(n_pages: int, extra: str = "") -> list[str]:
    fnum = extra_num(n_pages, 0)
    return [f"<< /Font << /F1 {fnum} 0 R >> {extra} >>" for _ in range(n_pages)]


def build_all(tmp: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}

    def save(name: str, data: bytes) -> Path:
        p = tmp / name
        p.write_bytes(data)
        out[name] = p
        return p

    # 1. normal (known) text watermark, 6 pages
    n = 6
    streams, res = [], _font_resources(n)
    for i in range(n):
        streams.append(body_line(i + 1) + text_show(f"itachibot - watermark", 150, 380))
    save("text_watermark.pdf", make_pdf(streams, res, [font_object()]))

    # 2. rotated/diagonal text watermark, 6 pages (centered, away from the
    #    body line at the top - a real watermark would overlap content, but
    #    this test isolates the ROTATION signal)
    n = 6
    streams, res = [], _font_resources(n)
    for i in range(n):
        streams.append(body_line(i + 1)
                       + text_show(f"itachibot diagonal", 0, 0, size=40,
                                   matrix="0.7071 0.7071 -0.7071 0.7071 180 330"))
    save("rotated_text.pdf", make_pdf(streams, res, [font_object()]))

    # 3. semi-transparent (alpha 0.35) text, non-needle string, 6 pages.
    #    Area < 2%, not rotated -> only the low-alpha repeated-text channel
    #    can classify this.
    n = 6
    streams, res = [], _font_resources(n)
    for i in range(n):
        streams.append(body_line(i + 1) + text_show("FAINTMARK", 150, 380, size=36,
                                                    alpha=0.35))
    save("alpha_text.pdf", make_pdf(streams, res, [font_object()]))

    # 4. full-page image watermark (shared XObject), 6 pages
    n = 6
    img = gray_stamp_jpeg(612, 792, "itachibot")
    streams, res = [], []
    fnum = extra_num(n, 0)
    inum = fnum + 1
    for i in range(n):
        streams.append(body_line(i + 1) + draw_full_image("Im1"))
        res.append(f"<< /Font << /F1 {fnum} 0 R >> /XObject << /Im1 {inum} 0 R >> >>")
    save("image_watermark.pdf", make_pdf(
        streams, res, [font_object(), image_object(img, 612, 792)]))

    # 5. transparent (SMask) image watermark, same position, 4 pages
    n = 4
    base, mask = smask_pair(500, 500, "MARK")
    streams, res = [], []
    fnum = extra_num(n, 0)
    inum, mnum = fnum + 1, fnum + 2
    for i in range(n):
        streams.append(body_line(i + 1) + draw_rect_image("Im1", 56, 146, 500, 500))
        res.append(f"<< /Font << /F1 {fnum} 0 R >> /XObject << /Im1 {inum} 0 R >> >>")
    save("alpha_image.pdf", make_pdf(
        streams, res,
        [font_object(), image_object(base, 500, 500, smask_xref=mnum),
         smask_object(mask, 500, 500)]))

    # 6. repeated vector watermark: low-alpha filled rectangle, 6 pages
    n = 6
    streams, res = [], _font_resources(n)
    for i in range(n):
        s = body_line(i + 1)
        s += b"0.7 g 0.4 CA\n100 100 m 500 100 l 500 500 l 100 500 l h f\n"
        streams.append(s)
    save("vector_watermark.pdf", make_pdf(streams, res, [font_object()]))

    # 7. repeated watermark across many pages: 12 pages, image + known text
    n = 12
    img = gray_stamp_jpeg(612, 792, "Sold by itachibot")
    streams, res = [], []
    fnum = extra_num(n, 0)
    inum = fnum + 1
    for i in range(n):
        streams.append(body_line(i + 1) + draw_full_image("Im1")
                       + text_show(f"Sold by itachibot", 150, 60, size=18))
        res.append(f"<< /Font << /F1 {fnum} 0 R >> /XObject << /Im1 {inum} 0 R >> >>")
    save("multi_page_repeated.pdf", make_pdf(
        streams, res, [font_object(), image_object(img, 612, 792)]))

    # 8. watermark text WITH a hyperlink on it + a legitimate link, 3 pages
    n = 3
    streams, res = [], _font_resources(n)
    annots = [[
        uri_link_annot((150, 380, 528, 416), "https://itachibot.example/buy-now"),
        uri_link_annot((72, 720, 240, 736), "https://www.ncbi.nlm.nih.gov/"),
    ], [], []]
    for i in range(n):
        streams.append(body_line(i + 1) + text_show(f"itachibot - watermark", 150, 380))
    save("link_watermark.pdf", make_pdf(
        streams, res, [font_object()], annots_per_page=annots))

    # 9. invisible (3 Tr) watermark + a VISIBLE identical string that must
    #    survive, 6 pages
    n = 6
    streams, res = [], _font_resources(n)
    for i in range(n):
        s = body_line(i + 1)
        s += text_show("SECRET-MARKER-123 (visible copy)", 72, 650, size=12)
        s += text_show("SECRET-MARKER-123", 0, 0, size=10, invisible=True)
        streams.append(s)
    save("hidden_text.pdf", make_pdf(streams, res, [font_object()]))

    # 10. legitimate links that must NOT be deleted (watermark present so
    #     processing runs), 3 pages: 2 external URIs + 1 internal GoTo
    n = 3
    streams, res = [], _font_resources(n)
    dest_page_obj = 3 + 1  # page 2 object number
    annots = [[
        uri_link_annot((72, 720, 260, 736), "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12345/"),
        uri_link_annot((72, 690, 200, 706), "https://doi.org/10.1000/xyz123"),
        goto_link_annot((72, 660, 160, 676), dest_page_obj),
    ], [], []]
    for i in range(n):
        streams.append(body_line(i + 1) + text_show(f"itachibot - watermark", 150, 380))
    save("legit_links.pdf", make_pdf(
        streams, res, [font_object()], annots_per_page=annots))

    # 11. legitimate small corner logo image that must NOT be deleted,
    #     4 pages (logo area ~2% < 25% same-position threshold)
    n = 4
    logo = logo_jpeg()
    streams, res = [], []
    fnum = extra_num(n, 0)
    inum = fnum + 1
    for i in range(n):
        streams.append(body_line(i + 1) + draw_rect_image("Logo", 500, 690, 100, 100)
                       + text_show(f"itachibot - watermark", 150, 380))
        res.append(f"<< /Font << /F1 {fnum} 0 R >> /XObject << /Logo {inum} 0 R >> >>")
    save("legit_image.pdf", make_pdf(
        streams, res, [font_object(), image_object(logo, 100, 100)]))

    # 12. tables + selectable text (two DIFFERENT tables so nothing repeats),
    #     rotated watermark on both pages
    def table_stream(label: str, values: list[str]) -> bytes:
        s = body_line(1, text=f"{label} table:")
        # grid: 4 cols x 3 rows (kept in the upper part of the page)
        x0, y0, cw, rh = 80, 650, 140, 40
        for r in range(3):
            for c in range(4):
                s += (f"{x0 + c * cw} {y0 - r * rh} m {x0 + (c + 1) * cw} "
                      f"{y0 - r * rh} l S\n"
                      f"{x0 + c * cw} {y0 - r * rh} m {x0 + c * cw} "
                      f"{y0 - (r + 1) * rh} l S\n").encode()
        for c, v in enumerate(["HeaderA", "HeaderB", "HeaderC", "HeaderD"]):
            s += (f"BT /F1 11 Tf {x0 + c * cw + 6} {y0 - 8} Td "
                  f"({v}) Tj ET\n").encode()
        for r, row in enumerate(values, start=1):
            for c, v in enumerate(row):
                s += (f"BT /F1 10 Tf {x0 + c * cw + 6} {y0 - r * rh - 8} Td "
                      f"({v}) Tj ET\n").encode()
        # centered rotated watermark, below the table
        s += text_show("itachibot table", 0, 0, size=36,
                       matrix="0.7071 0.7071 -0.7071 0.7071 200 260")
        return s

    streams = [table_stream("First", [["r1a", "r1b", "r1c", "r1d"],
                                      ["r2a", "r2b", "r2c", "r2d"]]),
               table_stream("Second", [["q1x", "q1y", "q1z", "q1w"],
                                       ["q2x", "q2y", "q2z", "q2w"]])]
    save("table_text.pdf", make_pdf(streams, _font_resources(2),
                                    [font_object()]))

    # 13. multi-page plain document, 20 pages, known watermark on every page
    n = 20
    streams, res = [], _font_resources(n)
    for i in range(n):
        streams.append(body_line(i + 1, text=f"Chapter note {i + 1}: the answer is C.")
                       + text_show(f"itachibot - watermark", 150, 380))
    save("multi_page_plain.pdf", make_pdf(streams, res, [font_object()]))

    # 14. scanned/image-only PDF with NO watermark -> must be REFUSED
    n = 4
    streams, res = [], ["<< >>" for _ in range(n)]
    extra = []
    for i in range(n):
        streams.append(draw_full_image(f"Im{i}"))
        extra.append(image_object(photo_jpeg(612, 792, seed=100 + i), 612, 792))
        res[i] = f"<< /XObject << /Im{i} {extra_num(n, i)} 0 R >> >>"
    save("scan_clean.pdf", make_pdf(streams, res, extra))

    # 15. malformed PDFs
    save("malformed_garbage.pdf", b"this is not a pdf at all - just text garbage\n")
    good = out["text_watermark.pdf"].read_bytes()
    save("malformed_header_only.pdf",
         b"%PDF-1.7\n% truncated/corrupt: no objects, no xref, no trailer\n")
    save("malformed_truncated.pdf", good[: len(good) // 2])

    # 16. password-protected PDF (must be refused, never bypassed)
    enc = tmp / "encrypted.pdf"
    encrypt_pdf(out["text_watermark.pdf"].read_bytes(), enc, "secret", "owner")
    out["encrypted.pdf"] = enc

    # 17. OCG (PDF layer) handling: 3 pages with a known watermark plus
    #     three layers: "Watermark hidden" (OFF by default -> must be
    #     removed), "Watermark visible" (ON by default -> logged only, kept),
    #     "Annotations" (legitimate, kept)
    n = 3
    streams, res = [], _font_resources(n)
    for i in range(n):
        streams.append(body_line(i + 1)
                       + text_show(f"itachibot - watermark", 150, 380))
    o_off, o_on, o_legit = extra_num(n, 1), extra_num(n, 2), extra_num(n, 3)
    catalog = (
        f"/OCProperties << /OCGs [{o_off} 0 R {o_on} 0 R {o_legit} 0 R] "
        f"/D << /Order [{o_off} 0 R {o_on} 0 R {o_legit} 0 R] "
        f"/ON [{o_on} 0 R {o_legit} 0 R] /OFF [{o_off} 0 R] >> >>"
    )
    save("ocgs.pdf", make_pdf(
        streams, res,
        [font_object(),
         b"<< /Type /OCG /Name (Watermark hidden) >>",
         b"<< /Type /OCG /Name (Watermark visible) >>",
         b"<< /Type /OCG /Name (Annotations) >>"],
        catalog_extra=catalog))

    # extras: a clean PDF with a content figure (used by app tests)
    n = 2
    fig = content_figure_jpeg()
    streams, res = [], []
    fnum = extra_num(n, 0)
    inum = fnum + 1
    for i in range(n):
        streams.append(body_line(i + 1) + draw_rect_image("Fig", 200, 400, 300, 220)
                       + text_show(f"itachibot - watermark", 150, 150, size=24))
        res.append(f"<< /Font << /F1 {fnum} 0 R >> /XObject << /Fig {inum} 0 R >> >>")
    save("watermark_with_figure.pdf", make_pdf(
        streams, res, [font_object(), image_object(fig, 300, 220)]))

    # 18. small slide-deck (the NorcetIQ incident): 4 pages where EVERY
    #     page repeats the same title line and a long copyright paragraph
    #     that legitimately contains "may not be copied", plus a rotated
    #     30%-alpha "@handle wm" stamp whose axis-aligned bbox covers a
    #     quarter of the page, and stamp ARTWORK drawn as a small nested
    #     form INSIDE a full-page template form (inverted /BBox).
    #     Expectations: title/copyright/body lines and the template (border
    #     + footer text) survive; the stamp text and its artwork go.
    n = 4
    fnum = extra_num(n, 0)
    logox = extra_num(n, 1)
    tplx = extra_num(n, 2)
    artx = extra_num(n, 3)
    gs_stamp = extra_num(n, 4)     # page-level alpha 0.30 for the stamp text
    gs_art = extra_num(n, 5)       # alpha 0.18 inside the art form
    title = "Family Health Services-3: General and Geriatric Nursing"
    # wrapped like a real typeset copyright strip: each line its own Tj,
    # <=140 chars, and the MIDDLE line contains the 'may not be copied'
    # phrase - the old engine deleted exactly such lines doc-wide
    rights_lines = [
        "All rights are reserved. These notes are the copyright of the "
        "publisher; reproduction, photocopying, printing, scanning or",
        "circulating of these notes by any form or by any means, electronic "
        "or mechanical, may not be copied or shared without written",
        "permission and will be treated as violation of the Copyright Act. "
        "Any person involved directly or indirectly will be punishable.",
    ]
    art_stream = draw_at("Im0", 0, 0, 370, 290, gs_name="GSa")
    tpl_stream = (
        b"0.85 0.15 0.15 RG 3 w 8 8 596 776 re S\n"
        b"BT /F1 10 Tf 30 24 Td (Nursing Next Live - education) Tj ET\n"
        b"q 1 0 0 1 120 250 cm /Art Do Q\n")
    streams, res = [], []
    for i in range(n):
        streams.append(
            b"q 1 0 0 1 0 0 cm /Tpl Do Q\n"
            + text_show(title, 60, 640, size=20)
            + text_show(rights_lines[0], 40, 560, size=10)
            + text_show(rights_lines[1], 40, 546, size=10)
            + text_show(rights_lines[2], 40, 532, size=10)
            + body_line(i + 1, f"Nursing care plan step {i + 1} continues "
                                f"here with important body content.",
                        x=60, y=470)
            + body_line(i + 1, f"Line {i + 1} passes through the stamp "
                               f"region and must survive intact.",
                        x=60, y=380)
            + text_show("@handle wm", 0, 0, size=60,
                        matrix="0.7071 0.7071 -0.7071 0.7071 150 250",
                        gs_name="GS1"))
        res.append(f"<< /Font << /F1 {fnum} 0 R >> /ExtGState << /GS1 "
                   f"{gs_stamp} 0 R >> /XObject << /Tpl {tplx} 0 R >> >>")
    save("small_deck_nested_stamp.pdf", make_pdf(
        streams, res, [
            font_object(),
            image_object(logo_jpeg(100, 100), 100, 100),
            form_object(tpl_stream, resources=(
                f"<< /Font << /F1 {fnum} 0 R >> /XObject << /Art {artx} 0 R "
                ">> >>"), inverted_bbox=True),
            form_object(art_stream, bbox=(0, 0, 370, 290), resources=(
                f"<< /XObject << /Im0 {logox} 0 R >> /ExtGState << /GSa "
                f"{gs_art} 0 R >> >>")),
            extgstate_object(0.30, 0.30),
            extgstate_object(0.18, 0.18),
        ]))

    return out


@pytest.fixture(scope="session")
def fixtures(tmp_path_factory) -> dict[str, Path]:
    d = tmp_path_factory.mktemp("fixtures")
    return build_all(d)


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


def run_cli(input_pdf: Path, out_dir: Path, *extra: str,
            timeout: int = 300) -> subprocess.CompletedProcess:
    cmd = [
        sys.executable, "-u", str(REPO_ROOT / "fix_pdf.py"), str(input_pdf),
        "--output", str(out_dir / "out.pdf"),
        "--intermediate", str(out_dir / "step1.pdf"),
        "--skip-ocr", "--samples", "1,2",
        *extra,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          cwd=str(REPO_ROOT))
