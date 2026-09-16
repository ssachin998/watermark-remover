#!/usr/bin/env python3
"""Minimal raw-PDF fixture builder for watermark-engine tests.

Writes structurally simple but spec-correct PDFs so tests can create exact
watermark structures (invisible text via ``3 Tr``, alpha via ``CA``,
same-position images, vector paths, link annotations, OCGs) that high-level
writer APIs cannot express.

Numbering convention (fixed, documented):
    1            catalog
    2            pages tree
    3..2+N       page objects          (page i  -> 3+i)
    3+N..3+2N-1  content streams       (page i  -> 3+N+i)
    3+2N..       extra objects         (slot i  -> 3+2N+i)
    after that   annotation objects
"""

from __future__ import annotations

import io
import random

from PIL import Image, ImageDraw, ImageFont


# --------------------------------------------------------------------------
# primitives
# --------------------------------------------------------------------------

def pdf_string(s: str) -> bytes:
    """Encode s as a PDF literal string (latin-1, escaped)."""
    out = bytearray(b"(")
    for ch in s.encode("latin-1"):
        if ch in b"()\\":
            out.append(0x5C)
            out.append(ch)
        elif 0x20 <= ch <= 0x7E:
            out.append(ch)
        else:
            out += b"\\%03o" % ch
    out.append(0x29)
    return bytes(out)


def body_line(page_no: int, text: str | None = None,
              x: int = 72, y: int = 700) -> bytes:
    """One line of legitimate body text."""
    t = text if text is not None else f"Question {page_no}: The correct answer is B."
    return (b"BT /F1 12 Tf " + str(x).encode() + b" " + str(y).encode()
            + b" Td " + pdf_string(t) + b" Tj ET\n")


def text_show(text: str, x: int, y: int, size: int = 36,
              matrix: str | None = None, invisible: bool = False,
              alpha: float | None = None) -> bytes:
    """A text-showing op, optionally rotated (matrix), invisible (3 Tr)
    and/or drawn with non-stroking alpha ``alpha`` (CA)."""
    s = ""
    if matrix:
        s += f"q {matrix} cm\n"
    if alpha is not None:
        s += f"{alpha} CA\n"
    s += f"BT /F1 {size} Tf {x} {y} Td"
    if invisible:
        s += " 3 Tr"
    s += f" {pdf_string(text).decode('latin-1')} Tj ET\n"
    if matrix:
        s += "Q\n"
    return s.encode("latin-1")


def draw_full_image(name: str, mw: int = 612, mh: int = 792) -> bytes:
    return f"q {mw} 0 0 {mh} 0 0 cm /{name} Do Q\n".encode()


def draw_rect_image(name: str, x: int, y: int, w: int, h: int) -> bytes:
    return f"q {w} 0 0 {h} {x} {y} cm /{name} Do Q\n".encode()


def uri_link_annot(rect, uri: str) -> bytes:
    return (b"<< /Type /Annot /Subtype /Link /Rect " + _rect(rect)
            + b" /Border [0 0 0] /A << /S /URI /URI "
            + pdf_string(uri) + b" >> >>")


def goto_link_annot(rect, dest_page_obj: int) -> bytes:
    return (b"<< /Type /Annot /Subtype /Link /Rect " + _rect(rect)
            + b" /Border [0 0 0] /Dest ["
            + str(dest_page_obj).encode() + b" 0 R /Fit] >>")


def _rect(r) -> bytes:
    vals = list(r)
    return b"[" + b" ".join(str(v).encode() for v in vals) + b"]"


def font_object() -> bytes:
    return b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"


def image_object(data: bytes, width: int, height: int,
                 smask_xref: int | None = None,
                 colorspace: str = "DeviceRGB") -> bytes:
    """RGB image XObject body.  If the image has an SMask, pass the xref of
    the (separately provided) gray mask object."""
    sm = f" /SMask {smask_xref} 0 R" if smask_xref else ""
    return (f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} "
            f"/ColorSpace /{colorspace} /BitsPerComponent 8 /Filter /DCTDecode"
            + sm
            + " >>\nstream\n").encode() + data + b"\nendstream"


def smask_object(data: bytes, width: int, height: int) -> bytes:
    """DeviceGray 8-bit alpha-mask XObject body (0=transparent, 255=opaque)."""
    return (f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} "
            f"/ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /DCTDecode"
            " >>\nstream\n").encode() + data + b"\nendstream"


def make_pdf(page_streams,
             page_resources,
             extra_objects=(),
             annots_per_page=(),
             media_box=(0, 0, 612, 792),
             page_extra=(),
             catalog_extra: str = "") -> bytes:
    """Assemble a PDF 1.7 file.  See module docstring for numbering.

    catalog_extra: extra keys appended to the catalog dict (e.g. /OCProperties).
    """
    n = len(page_streams)
    n_extra = len(extra_objects)
    flat_annots = [a for page in annots_per_page for a in page]

    def page_num(i): return 3 + i
    def content_num(i): return 3 + n + i
    def extra_num(i): return 3 + 2 * n + i
    def ann_num(k): return 3 + 2 * n + n_extra + k

    objs: dict[int, bytes] = {}
    objs[1] = b"<< /Type /Catalog /Pages 2 0 R " + \
        (catalog_extra.encode() if catalog_extra else b"") + b" >>"
    kids = " ".join(f"{page_num(i)} 0 R" for i in range(n))
    objs[2] = f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode()

    k = 0
    for i in range(n):
        annots = annots_per_page[i] if i < len(annots_per_page) else []
        pextra = page_extra[i] if i < len(page_extra) else ""
        if annots:
            ann_arr = " ".join(f"{ann_num(k + j)} 0 R" for j in range(len(annots)))
            k += len(annots)
        else:
            ann_arr = ""
        res = page_resources[i] if i < len(page_resources) else "<< >>"
        objs[page_num(i)] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox {list(media_box)} "
            f"/Resources {res} /Contents {content_num(i)} 0 R"
            + (f" /Annots [{ann_arr}]" if annots else "")
            + ((" " + pextra) if pextra else "")
            + " >>"
        ).encode()
        data = page_streams[i]
        objs[content_num(i)] = (
            f"<< /Length {len(data)} >>\nstream\n".encode() + data + b"\nendstream"
        )
    for j, body in enumerate(extra_objects):
        objs[extra_num(j)] = body
    for j, body in enumerate(flat_annots):
        objs[ann_num(j)] = body

    out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets: dict[int, int] = {}
    for num in sorted(objs):
        offsets[num] = len(out)
        out += f"{num} 0 obj\n".encode() + objs[num] + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for num in range(1, len(objs) + 1):
        out += f"{offsets[num]:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF\n").encode()
    return bytes(out)


def extra_num(n_pages: int, i: int) -> int:
    return 3 + 2 * n_pages + i


# --------------------------------------------------------------------------
# raster image generators (JPEG, via PIL)
# --------------------------------------------------------------------------

def _save_jpeg(img: Image.Image, quality: int = 88) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, subsampling=1)
    return buf.getvalue()


def _font(size: int) -> "ImageFont.FreeTypeFont":
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def gray_stamp_jpeg(w: int, h: int, text: str) -> bytes:
    """Light-gray stamp text on white - classic raster watermark."""
    img = Image.new("RGB", (w, h), (255, 255, 255))
    d = ImageDraw.Draw(img)
    f = _font(max(20, h // 12))
    d.text((w // 6, h // 2), text, fill=(205, 205, 205), font=f)
    return _save_jpeg(img)


def smask_pair(w: int, h: int, text: str):
    """(base_jpeg, smask_jpeg) - gray text, transparent background.

    Base: light-gray text on white.  SMask: 255 where text is (opaque),
    0 in the background (fully transparent) -> a true alpha PNG-style image.
    """
    img = Image.new("RGB", (w, h), (255, 255, 255))
    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(img)
    dm = ImageDraw.Draw(mask)
    f = _font(max(24, h // 8))
    d.text((w // 6, h // 2), text, fill=(190, 190, 190), font=f)
    dm.text((w // 6, h // 2), text, fill=255, font=f)
    return _save_jpeg(img), _save_jpeg(mask)


def photo_jpeg(w: int, h: int, seed: int) -> bytes:
    """Page of 'photo' content: noise + dark shapes, different per seed.

    Carries real ink (~2-4%) so it is content, not a watermark stamp.
    """
    rng = random.Random(seed)
    base = (rng.randint(228, 246),) * 3
    img = Image.new("RGB", (w, h), base)
    d = ImageDraw.Draw(img)
    for _ in range(rng.randint(4, 9)):
        x0, y0 = rng.randint(0, w - 60), rng.randint(0, h - 60)
        col = (rng.randint(20, 120),) * 3
        kind = rng.choice(["rect", "ellipse", "line"])
        if kind == "rect":
            d.rectangle([x0, y0, x0 + rng.randint(20, 120),
                         y0 + rng.randint(20, 120)], outline=col,
                        width=rng.randint(1, 4))
        elif kind == "ellipse":
            d.ellipse([x0, y0, x0 + rng.randint(20, 100),
                       y0 + rng.randint(20, 100)], outline=col, width=2)
        else:
            d.line([x0, y0, x0 + rng.randint(40, 200),
                    y0 + rng.randint(40, 200)], fill=col,
                   width=rng.randint(1, 3))
    # light noise so per-page pixels differ
    px = img.load()
    for _ in range(w * h // 30):
        x, y = rng.randint(0, w - 1), rng.randint(0, h - 1)
        v = rng.randint(-12, 12)
        r, g, b = px[x, y]
        px[x, y] = (max(0, min(255, r + v)), max(0, min(255, g + v)),
                    max(0, min(255, b + v)))
    return _save_jpeg(img, quality=85)


def logo_jpeg(w: int = 100, h: int = 100) -> bytes:
    """Small solid gray square - a legitimate corner logo."""
    img = Image.new("RGB", (w, h), (150, 150, 160))
    d = ImageDraw.Draw(img)
    d.line([0, 0, w, h], fill=(90, 90, 100), width=4)
    d.line([0, h, w, 0], fill=(90, 90, 100), width=4)
    return _save_jpeg(img)


def content_figure_jpeg(w: int = 300, h: int = 220, seed: int = 1) -> bytes:
    """A figure with real ink (bars) - must never be removed."""
    rng = random.Random(seed)
    img = Image.new("RGB", (w, h), (255, 255, 255))
    d = ImageDraw.Draw(img)
    for i in range(6):
        bh = rng.randint(30, h - 20)
        x = 10 + i * (w // 6)
        d.rectangle([x, h - bh, x + w // 12, h - 10],
                    fill=(rng.randint(60, 140), rng.randint(60, 140),
                          rng.randint(60, 160)))
    return _save_jpeg(img)


def encrypt_pdf(plain: bytes, out_path, user_pw: str, owner_pw: str) -> None:
    """Re-save a plain PDF with a user password (encryption ON)."""
    import pymupdf as fitz
    doc = fitz.open(stream=plain, filetype="pdf")
    doc.save(out_path, encryption=fitz.PDF_ENCRYPT_AES_256,
             user_pw=user_pw, owner_pw=owner_pw)
    doc.close()
