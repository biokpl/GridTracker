"""7 segment VFD rakamlarını gerçek TTF yazı tipine çevirir (0-9, ':' ve boşluk).
Bitmap font (resim glifler) saatte AOD ön-hesaplamasını boğuyordu; TTF metin gibi hafif çizilir."""
from pathlib import Path
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
import render_vfd as V

UPM = 1000
CAP = 840                      # rakam yüksekliği (font birimi)
ADV, COLON = 500, 220          # karakter genişlikleri
W_, T_ = 400, 100              # segment kutusu genişliği, kalınlık


def _glyph(polys):
    pen = TTGlyphPen(None)
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
        hw, g = T_ / 2, T_ * 0.18
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
        out.append([(cx + dx - r, cy - r), (cx + dx + r, cy - r), (cx + dx + r, cy + r), (cx + dx - r, cy + r)])
    return out


def build(path, family="VFD7"):
    order = [".notdef", "space", "colon"] + [f"d{i}" for i in range(10)]
    cmap = {32: "space", ord(":"): "colon", **{ord(str(i)): f"d{i}" for i in range(10)}}
    glyphs = {".notdef": TTGlyphPen(None).glyph(), "space": TTGlyphPen(None).glyph(), "colon": _glyph(colon_polys())}
    for i in range(10): glyphs[f"d{i}"] = _glyph(digit_polys(str(i)))
    metrics = {g: (ADV, 0) for g in order}; metrics["colon"] = (COLON, 0); metrics[".notdef"] = (ADV, 0)
    fb = FontBuilder(UPM, isTTF=True)
    fb.setupGlyphOrder(order); fb.setupCharacterMap(cmap); fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=900, descent=-100)
    fb.setupNameTable({"familyName": family, "styleName": "Regular"})
    fb.setupOS2(sTypoAscender=900, sTypoDescender=-100, usWinAscent=900, usWinDescent=100)
    fb.setupPost()
    fb.save(str(path))


if __name__ == "__main__":
    out = Path(__file__).parent / "vfd7.ttf"; build(out); print("ok", out)
