#!/usr/bin/env python3
"""Generate the site icons from one source of truth: a 5x5 crossword motif.

Needs Pillow (`pip3 install pillow`); the Mac mini does not ship it, so install
it there before regenerating. Every PNG is drawn at 4x and downsampled with
LANCZOS, which is what gives the rounded cells and the soft shadow clean edges.
Re-run after changing the palette or the block pattern:

    python3 tools/make_icons.py

Outputs favicon.ico, favicon.svg, favicon-16/32.png, icon-192/512.png,
apple-touch-icon.png into the repo root. The 1200x630 social card is separate: it needs real
type, so it is rendered from tools/og_card.html by tools/make_og.sh.

Two variants of one design:

* App icons (apple-touch-icon, icon-192/512): a full-bleed, opaque square, so
  iOS and Android can apply their own corner mask. A deep diagonal gradient in
  the site's accent blue, with the grid as a single raised "card" inset to about
  two thirds of the tile. The card has rounded corners, rounded cells and a soft
  drop shadow, and its centre cell is the gold of a selected square (--cell-sel),
  so one warm spot pops against the blue.
* Favicons (16/32/48, favicon.svg): nothing masks these and they are tiny, so
  the grid fills most of a rounded blue tile with no shadow. That keeps the
  five-by-five pattern legible at 16px.
"""
import io
import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent

PAPER = (255, 255, 255)
INK = (20, 23, 26)          # --blockfill: the blocks and the grid frame
GOLD = (255, 207, 77)       # --cell-sel (#ffd75e), a touch deeper so it holds on blue
BG_TOP = (48, 150, 214)     # gradient, top-left: a lifted --accent
BG_BOTTOM = (9, 58, 96)     # gradient, bottom-right: a deepened --cell-revealed (#0f5c86)

# The motif: a 5x5 mini-grid, blocks symmetric about the centre, one accent
# square in the middle. Reads as a crossword even at 16px.
#
# The blocks sit on the diagonal, which is legal: runs of ONE are fine (that is
# an unchecked square inside the perpendicular light), runs of two are not — a
# diamond at the edge midpoints would leave eight two-letter runs. check_motif()
# below runs the motif through tools/grid_rules.py's checker.
BLOCKS = {(1, 1), (1, 3), (3, 1), (3, 3)}
ACCENTS = {(2, 2)}

SS = 4  # supersampling factor


def fill_of(r, c):
    return INK if (r, c) in BLOCKS else GOLD if (r, c) in ACCENTS else PAPER


def hexc(rgb):
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def gradient(size, top=BG_TOP, bottom=BG_BOTTOM):
    """Diagonal linear gradient, top-left to bottom-right."""
    ramp = Image.linear_gradient("L").resize((size, size))
    # Average a vertical and a horizontal ramp to get the 45-degree one.
    diag = Image.blend(ramp, ramp.transpose(Image.Transpose.ROTATE_90)
                       .transpose(Image.Transpose.FLIP_TOP_BOTTOM), 0.5)
    return Image.composite(Image.new("RGB", (size, size), bottom),
                           Image.new("RGB", (size, size), top), diag)


def draw_grid(img, x0, y0, span, frame, gap, cell_r, card_r):
    """The card: an ink rounded square, with 25 rounded cells set into it."""
    d = ImageDraw.Draw(img)
    # PIL box corners are inclusive, hence the -1s: without them every cell
    # bleeds a quarter pixel into its gridline and the 16px favicon goes grey.
    d.rounded_rectangle((x0, y0, x0 + span - 1, y0 + span - 1), card_r, fill=INK)
    cell = (span - 2 * frame - 4 * gap) / 5
    for r in range(5):
        for c in range(5):
            if (r, c) in BLOCKS:
                continue  # the ink shows through
            x = x0 + frame + c * (cell + gap)
            y = y0 + frame + r * (cell + gap)
            d.rounded_rectangle((x, y, x + cell - 1, y + cell - 1), cell_r,
                                fill=fill_of(r, c))
    # A faint top sheen on the paper cells for a little depth.
    sheen = Image.linear_gradient("L").resize((span, span))
    sheen = sheen.point(lambda v: int(28 * (1 - v / 255)))
    white = Image.new("RGB", (span, span), (255, 255, 255))
    region = img.crop((x0, y0, x0 + span, y0 + span))
    region = Image.composite(white, region, sheen)
    mask = Image.new("L", (span, span), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, span - 1, span - 1), card_r,
                                           fill=255)
    img.paste(region, (x0, y0), mask)


def app_icon(size):
    """Full-bleed opaque square for iOS/Android: they apply the corner mask."""
    S = size * SS
    img = gradient(S)
    span = round(S * 0.64)
    x0 = (S - span) // 2
    y0 = x0 - round(S * 0.012)  # optically centred: the shadow weighs it down
    card_r = round(span * 0.11)
    # Soft shadow below the card.
    sh = Image.new("L", (S, S), 0)
    off = round(S * 0.03)
    ImageDraw.Draw(sh).rounded_rectangle(
        (x0, y0 + off, x0 + span, y0 + span + off), card_r, fill=150)
    sh = sh.filter(ImageFilter.GaussianBlur(S * 0.035))
    img = Image.composite(Image.new("RGB", (S, S), (2, 18, 30)), img, sh)
    draw_grid(img, x0, y0, span, frame=round(span * 0.04),
              gap=round(span * 0.022), cell_r=round(span * 0.03), card_r=card_r)
    return img.resize((size, size), Image.Resampling.LANCZOS)


def tab_icon(size):
    """Favicon: rounded blue tile, grid filling most of it, no shadow."""
    S = size * SS
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    tile = gradient(S)
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, S - 1, S - 1), round(S * 0.22),
                                           fill=255)
    img.paste(tile, (0, 0), mask)
    # Pixel-snapped: one-pixel gridlines and frame, whole-pixel cells, so the
    # pattern stays crisp after downsampling. At 16px that is 5x2 + 6 = 16, so
    # the grid fills the tile; larger sizes leave a blue margin.
    cell = max(2, (round(size * 0.85) - 6) // 5)
    span = (5 * cell + 6) * SS
    x0 = (size - (5 * cell + 6)) // 2 * SS
    draw_grid(img, x0, x0, span, frame=SS, gap=SS,
              cell_r=SS // 2 if cell > 3 else 0, card_r=SS * (1 if cell < 3 else 2))
    # BOX, not LANCZOS: on pixel-aligned art it averages exactly, no ringing.
    return img.resize((size, size), Image.Resampling.BOX)


def png_bytes(img):
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def write_ico(path, sizes):
    """ICO with PNG-compressed entries (every browser since IE11 groks this)."""
    images = [(s, png_bytes(tab_icon(s))) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for s, data in images:
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32,
                               len(data), offset)
        blobs += data
        offset += len(data)
    path.write_bytes(header + entries + blobs)


def write_svg(path):
    """favicon.svg: the favicon variant, from the same BLOCKS and colours."""
    side, span = 64, 51.2
    x0 = (side - span) / 2
    frame = gap = round(span * 0.035, 2)
    cell = round((span - 2 * frame - 4 * gap) / 5, 2)
    squares = []
    for r in range(5):
        for c in range(5):
            if (r, c) in BLOCKS:
                continue
            x = round(x0 + frame + c * (cell + gap), 2)
            y = round(x0 + frame + r * (cell + gap), 2)
            squares.append(f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" '
                           f'rx="1" fill="{hexc(fill_of(r, c))}"/>')
    rows = "\n  ".join(squares)
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img"\n'
        '     aria-label="Cryptic Teacher">\n'
        '  <!-- GENERATED by tools/make_icons.py from BLOCKS/ACCENTS. Don\'t edit. -->\n'
        '  <defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{hexc(BG_TOP)}"/>'
        f'<stop offset="1" stop-color="{hexc(BG_BOTTOM)}"/></linearGradient></defs>\n'
        f'  <rect width="{side}" height="{side}" rx="14" fill="url(#bg)"/>\n'
        f'  <rect x="{x0}" y="{x0}" width="{span}" height="{span}" '
        f'rx="{round(span * 0.08, 2)}" fill="{hexc(INK)}"/>\n'
        f'  {rows}\n</svg>\n', encoding="utf-8")


def check_motif():
    """Refuse to draw a mini-grid that isn't a legal one, by tools/grid_rules.py's
    checker."""
    from grid_rules import check
    check([[(r, c) not in BLOCKS for c in range(5)] for r in range(5)])


if __name__ == "__main__":
    check_motif()
    for name, img in (("favicon-16.png", tab_icon(16)),
                      ("favicon-32.png", tab_icon(32)),
                      ("icon-192.png", app_icon(192)),
                      ("apple-touch-icon.png", app_icon(180)),
                      ("icon-512.png", app_icon(512))):
        (ROOT / name).write_bytes(png_bytes(img))
        print("wrote", name)
    write_ico(ROOT / "favicon.ico", (16, 32, 48))
    print("wrote favicon.ico")
    write_svg(ROOT / "favicon.svg")
    print("wrote favicon.svg")
