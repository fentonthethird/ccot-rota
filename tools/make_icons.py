"""Generate the PWA icons without any imaging library.

Draws a rounded blue tile with a white calendar page and a tick, anti-aliased from
signed distance functions, and writes PNGs with zlib. Run: python3 tools/make_icons.py
"""
import math, struct, zlib, os

BLUE = (0, 94, 184)      # NHS blue
WHITE = (255, 255, 255)
LIGHT = (218, 232, 247)

def sd_round_rect(px, py, cx, cy, hw, hh, r):
    dx = abs(px - cx) - hw + r
    dy = abs(py - cy) - hh + r
    return math.hypot(max(dx, 0), max(dy, 0)) + min(max(dx, dy), 0) - r

def sd_segment(px, py, ax, ay, bx, by, r):
    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    t = max(0.0, min(1.0, (wx * vx + wy * vy) / (vx * vx + vy * vy)))
    return math.hypot(wx - t * vx, wy - t * vy) - r

def cov(d):
    return max(0.0, min(1.0, 0.5 - d))

def blend(base, col, a):
    return tuple(round(b * (1 - a) + c * a) for b, c in zip(base, col))

def render(size, tile_radius_frac, bg_full):
    s = size
    rows = []
    for y in range(s):
        row = bytearray()
        for x in range(s):
            px, py = x + 0.5, y + 0.5
            if bg_full:
                pix, alpha = BLUE, 1.0
            else:
                d = sd_round_rect(px, py, s / 2, s / 2, s / 2, s / 2, s * tile_radius_frac)
                alpha = cov(d)
                pix = BLUE
            # calendar page
            pw, ph = s * 0.30, s * 0.27
            cx, cy = s / 2, s * 0.54
            d = sd_round_rect(px, py, cx, cy, pw, ph, s * 0.05)
            pix = blend(pix, WHITE, cov(d))
            # header band
            d = sd_round_rect(px, py, cx, cy - ph + s * 0.06, pw, s * 0.06, s * 0.0)
            band = cov(d) * cov(sd_round_rect(px, py, cx, cy, pw, ph, s * 0.05))
            pix = blend(pix, LIGHT, band)
            # rings
            for rx in (cx - pw * 0.5, cx + pw * 0.5):
                d = sd_segment(px, py, rx, cy - ph - s * 0.04, rx, cy - ph + s * 0.03, s * 0.022)
                pix = blend(pix, BLUE, cov(d))
            # tick
            d1 = sd_segment(px, py, cx - pw * 0.42, cy + ph * 0.12, cx - pw * 0.08, cy + ph * 0.5, s * 0.035)
            d2 = sd_segment(px, py, cx - pw * 0.08, cy + ph * 0.5, cx + pw * 0.48, cy - ph * 0.2, s * 0.035)
            pix = blend(pix, BLUE, cov(min(d1, d2)))
            row += bytes(pix) + bytes([round(alpha * 255)])
        rows.append(bytes(row))
    return rows

def write_png(path, size, rows):
    raw = b"".join(b"\x00" + r for r in rows)
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)

if __name__ == "__main__":
    out = os.path.join(os.path.dirname(__file__), "..", "docs", "icons")
    os.makedirs(out, exist_ok=True)
    write_png(os.path.join(out, "icon-192.png"), 192, render(192, 0.2, False))
    write_png(os.path.join(out, "icon-512.png"), 512, render(512, 0.2, False))
    write_png(os.path.join(out, "maskable-512.png"), 512, render(512, 0.0, True))
    write_png(os.path.join(out, "apple-touch-icon.png"), 180, render(180, 0.0, True))
    print("icons written to", os.path.abspath(out))
