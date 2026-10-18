"""7 segment VFD rakamlarını gerçek TTF yazı tipine çevirir (0-9, ':' ve boşluk).
Bitmap font (resim glifler) saatte AOD ön-hesaplamasını boğuyordu; TTF metin gibi hafif çizilir."""
import math
from pathlib import Path
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
import render_vfd as V

UPM = 1000
CAP = 840                      # rakam yüksekliği (font birimi)
ADV, COLON = 500, 220          # karakter genişlikleri
W_, T_ = 400, 100              # segment kutusu genişliği, kalınlık


def grow_convex(poly, d):
    """Dışbükey çokgeni her kenarından d kadar dışa kaydırır (parlama halesi için)."""
    n = len(poly)
    area = sum(poly[i][0] * poly[(i + 1) % n][1] - poly[(i + 1) % n][0] * poly[i][1] for i in range(n))
    sg = 1 if area > 0 else -1
    lines = []
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
        L = math.hypot(x2 - x1, y2 - y1) or 1
        nx, ny = sg * (y2 - y1) / L, -sg * (x2 - x1) / L        # dış normal
        lines.append(((x1 + nx * d, y1 + ny * d), (x2 - x1, y2 - y1)))
    out = []
    for i in range(n):
        (p, r), (q, s_) = lines[i - 1], lines[i]
        den = r[0] * s_[1] - r[1] * s_[0]
        if abs(den) < 1e-9: out.append(q); continue
        t = ((q[0] - p[0]) * s_[1] - (q[1] - p[1]) * s_[0]) / den
        out.append((p[0] + t * r[0], p[1] + t * r[1]))
    return out


def _glyph(polys, grow=0, adv=ADV):
    pen = TTGlyphPen(None)
    polys = [grow_convex(pl, grow) if grow else pl for pl in polys]
    for poly in polys:
        pts = [(round(x), round(CAP - y)) for x, y in poly]      # y aşağı → yukarı
        pen.moveTo(pts[0])
        for p in pts[1:]: pen.lineTo(p)
        pen.closePath()
    return pen.glyph()


def digit_polys(ch):
    x0 = (ADV - W_) / 2 - CAP * 0.06
    segs = V.seg_polys(x0, 0, W_, CAP, T_)
    if ch == "1":      # yatay segment yok → dikeyleri tam boya uzat (yoksa kısa görünür)
        hw, g = T_ / 2, T_ * 0.10
        P = lambda px, py: (x0 + px + (CAP - py) * 0.12, py)
        def vseg(px, y0, y1):
            return [P(px, y0 + g), P(px + hw, y0 + g + hw), P(px + hw, y1 - g - hw),
                    P(px, y1 - g), P(px - hw, y1 - g - hw), P(px - hw, y0 + g + hw)]
        return [vseg(W_ - hw, -g, CAP / 2), vseg(W_ - hw, CAP / 2, CAP + g)]
    return [segs[k] for k in V.SEG[ch]]


def colon_polys():
    r = T_ * 0.55; cx = COLON / 2
    out = []
    for fy in (0.32, 0.68):
        cy = CAP * fy; dx = CAP * 0.12 * (1 - fy)
        out.append([(cx + dx + r * math.cos(-i * math.pi / 12), cy + r * math.sin(-i * math.pi / 12)) for i in range(24)])
    return out


def build(path, family="VFD7", grow=0):
    order = [".notdef", "space", "colon"] + [f"d{i}" for i in range(10)]
    cmap = {32: "space", ord(":"): "colon", **{ord(str(i)): f"d{i}" for i in range(10)}}
    glyphs = {".notdef": TTGlyphPen(None).glyph(), "space": TTGlyphPen(None).glyph(), "colon": _glyph(colon_polys(), grow, COLON)}
    for i in range(10): glyphs[f"d{i}"] = _glyph(digit_polys(str(i)), grow)
    # lsb = glifin gerçek sol kenarı (0 yazılırsa motor glifi kaydırır: '1' sola yapışır, hale kayar)
    lsb = lambda g: getattr(glyphs[g], "xMin", 0) if getattr(glyphs[g], "numberOfContours", 0) else 0
    for g in glyphs.values():
        if getattr(g, "numberOfContours", 0): g.recalcBounds(None)
    metrics = {g: (COLON if g == "colon" else ADV, lsb(g)) for g in order}
    fb = FontBuilder(UPM, isTTF=True)
    fb.setupGlyphOrder(order); fb.setupCharacterMap(cmap); fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=CAP, descent=0, lineGap=0)
    fb.setupNameTable({"familyName": family, "styleName": "Regular"})
    fb.setupOS2(sTypoAscender=CAP, sTypoDescender=0, sTypoLineGap=0, usWinAscent=CAP, usWinDescent=0)   # satır kutusu = rakam boyu → dikeyde ortalı
    fb.setupPost()
    fb.save(str(path))


if __name__ == "__main__":
    out = Path(__file__).parent / "vfd7.ttf"; build(out); print("ok", out)
