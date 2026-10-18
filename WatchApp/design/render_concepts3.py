"""B ve C'nin daha görsel ikinci sürümleri — B2 Luxury (analog), C2 Neon Trader (siber)."""
import math, random
from PIL import Image, ImageDraw, ImageFilter, ImageChops
from render_concepts import (S, F, C, OUT, pt, lerp, radial_bg, glow, ctext, moon, heart,
                             BAHN, SEG, AGB, SYM, watch, spark, font)


def shadowed(img, draw_fn, off=(6, 8), blur=6, alpha=170):
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0)); draw_fn(ImageDraw.Draw(sh), (0, 0, 0, alpha))
    sh = sh.filter(ImageFilter.GaussianBlur(blur * S))
    img.alpha_composite(sh, (int(off[0] * S), int(off[1] * S)))


# ═══════════════ B2 · LUXURY (gerçek lüks analog) ═══════════════
def face_lux2():
    img = radial_bg((26, 44, 92), (4, 8, 22))
    # giyoş: eşmerkezli dalgalı halkalar
    gl = Image.new("RGBA", (F, F), (0, 0, 0, 0)); gd = ImageDraw.Draw(gl)
    for r in range(6 * S, int(196 * S), 3 * S):
        pts = []
        for a in range(0, 361, 3):
            rr = r + math.sin(math.radians(a * 12)) * 2.2 * S
            pts.append(pt(rr, a))
        gd.line(pts, fill=(255, 255, 255, 13 if (r // (3 * S)) % 2 else 6), width=S)
    img.alpha_composite(gl)
    d = ImageDraw.Draw(img)
    G1, G2, G3 = (246, 214, 140, 255), (196, 150, 72, 255), (120, 86, 36, 255)
    # dış rehaut (dakika halkası, koyu)
    d.ellipse((4 * S, 4 * S, F - 4 * S, F - 4 * S), fill=None, outline=G3, width=2 * S)
    ring = Image.new("RGBA", (F, F), (0, 0, 0, 0)); rd = ImageDraw.Draw(ring)
    rd.ellipse((8 * S, 8 * S, F - 8 * S, F - 8 * S), fill=(10, 16, 34, 255))
    rd.ellipse((40 * S, 40 * S, F - 40 * S, F - 40 * S), fill=(0, 0, 0, 0))
    img.alpha_composite(ring); d = ImageDraw.Draw(img)
    for i in range(60):
        a = i * 6
        d.line((*pt(232 * S, a), *pt((224 if i % 5 else 220) * S, a)), fill=G2 if i % 5 == 0 else (150, 130, 90, 255), width=(2 if i % 5 == 0 else 1) * S)
    for i in range(5, 61, 5):
        ctext(d, pt(212 * S, i * 6), f"{i:02d}", BAHN(12, "SemiBold Condensed"), (200, 170, 110, 255))
    # kabartmalı altın indeksler (gölge + ışık)
    def index_poly(a, r0, r1, w):
        x0, y0 = pt(r0, a); x1, y1 = pt(r1, a)
        nx, ny = math.cos(math.radians(a)), math.sin(math.radians(a))
        return [(x0 + nx * w, y0 + ny * w), (x1 + nx * w, y1 + ny * w), (x1 - nx * w, y1 - ny * w), (x0 - nx * w, y0 - ny * w)]
    for h in range(12):
        a = h * 30
        if a in (240, 120, 180): continue          # alt kadranlarda boş
        w = (9 if h == 0 else 6) * S
        polys = [index_poly(a + o, 190 * S, 152 * S, w) for o in ((-2.2, 2.2) if h == 0 else (0,))]
        for poly in polys:
            shadowed(img, lambda dr, col, p=poly: dr.polygon(p, fill=col), off=(4, 6), blur=4)
            d = ImageDraw.Draw(img)
            d.polygon(poly, fill=G2)
            hl = [poly[0], poly[1], ((poly[1][0] + poly[2][0]) / 2, (poly[1][1] + poly[2][1]) / 2), ((poly[0][0] + poly[3][0]) / 2, (poly[0][1] + poly[3][1]) / 2)]
            d.polygon(hl, fill=G1)
    d = ImageDraw.Draw(img)
    ctext(d, (C, 128 * S), "ALSAT", SEG(26, "Semibold"), G1)
    ctext(d, (C, 152 * S), "AUTOMATIC · BIST", BAHN(11, "SemiBold Condensed"), (200, 175, 120, 255))
    # tarih penceresi
    d.rounded_rectangle((C + 118 * S, C - 14 * S, C + 156 * S, C + 14 * S), radius=3 * S, fill=(245, 240, 228, 255), outline=G2, width=2 * S)
    ctext(d, (C + 137 * S, C), "18", BAHN(20, "Bold Condensed"), (30, 30, 30, 255))

    def subdial(cx, cy, r, val, col, top, mid, bot, hand_frac):
        dd = ImageDraw.Draw(img)
        dd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(12, 20, 44, 255), outline=G2, width=3 * S)
        for rr in range(int(r * 0.25), int(r * 0.9), 2 * S):
            dd.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), outline=(255, 255, 255, 10), width=S)
        for i in range(31):
            a = 225 + i * 9
            x0, y0 = pt_c(cx, cy, r - 4 * S, a); x1, y1 = pt_c(cx, cy, r - (11 if i % 5 == 0 else 8) * S, a)
            dd.line((x0, y0, x1, y1), fill=G1 if i % 5 == 0 else (170, 150, 110, 255), width=S * (2 if i % 5 == 0 else 1))
        bb = (cx - r + 14 * S, cy - r + 14 * S, cx + r - 14 * S, cy + r - 14 * S)
        dd.arc(bb, 135, 135 + 270 * val, fill=col, width=4 * S)
        ctext(dd, (cx, cy - 20 * S), top, BAHN(10, "SemiBold Condensed"), (200, 180, 140, 255))
        ctext(dd, (cx, cy + 22 * S), mid, BAHN(16, "Bold Condensed"), (245, 236, 215, 255))
        ctext(dd, (cx, cy + 36 * S), bot, BAHN(10, "SemiBold Condensed"), (170, 160, 140, 255))
        a = 225 + 270 * hand_frac
        tip = pt_c(cx, cy, r - 16 * S, a)
        shadowed(img, lambda dr, c_: dr.line((cx, cy, *tip), fill=c_, width=3 * S), off=(2, 3), blur=2)
        dd = ImageDraw.Draw(img)
        dd.line((cx, cy, *tip), fill=G1, width=3 * S)
        dd.ellipse((cx - 5 * S, cy - 5 * S, cx + 5 * S, cy + 5 * S), fill=G2)

    def pt_c(cx, cy, r, deg):
        t = math.radians(deg - 90); return cx + r * math.cos(t), cy + r * math.sin(t)
    subdial(C - 92 * S, C + 50 * S, 52 * S, 0.62, (250, 190, 90, 255), "İKİNDİ", "01:44", "15:56", 0.62)
    subdial(C, C + 118 * S, 56 * S, 0.78, (120, 220, 160, 255), "TUPRS", "+582 ₺", "351 – 394", 0.78)
    subdial(C + 92 * S, C + 50 * S, 52 * S, 0.74, (120, 200, 140, 255), "PİL · NABIZ", "74%", "♥ 77".replace("♥", "NBZ"), 0.74)
    # dauphine akrep/yelkovan (14:32:27)
    def dauphine(angle, length, width):
        tip = pt(length, angle); base_l = pt(-22 * S, angle)
        nx, ny = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        mid = pt(length * 0.18, angle)
        left = (mid[0] - nx * width, mid[1] - ny * width); right = (mid[0] + nx * width, mid[1] + ny * width)
        full = [base_l, left, tip, right]
        shadowed(img, lambda dr, col: dr.polygon(full, fill=col), off=(8, 11), blur=7, alpha=190)
        dd = ImageDraw.Draw(img)
        dd.polygon([base_l, left, tip], fill=G1)        # ışık tarafı
        dd.polygon([base_l, right, tip], fill=G3)       # gölge tarafı
        dd.line((base_l, tip), fill=G2, width=S)
    dauphine((14 % 12) * 30 + 32 * 0.5, 128 * S, 12 * S)
    dauphine(32 * 6 + 27 * 0.1, 188 * S, 10 * S)
    d = ImageDraw.Draw(img)
    a = 27 * 6
    d.line((*pt(-36 * S, a), *pt(206 * S, a)), fill=(232, 72, 52, 255), width=2 * S)
    d.ellipse((C - 13 * S, C - 13 * S, C + 13 * S, C + 13 * S), fill=G2, outline=G1, width=2 * S)
    d.ellipse((C - 4 * S, C - 4 * S, C + 4 * S, C + 4 * S), fill=(232, 72, 52, 255))
    # cam yansıması
    gloss = Image.new("RGBA", (F, F), (0, 0, 0, 0)); gd = ImageDraw.Draw(gloss)
    gd.ellipse((-F * 0.2, -F * 0.55, F * 1.05, F * 0.42), fill=(255, 255, 255, 14))
    img.alpha_composite(gloss)
    return img


# ═══════════════ C2 · NEON TRADER (siber) ═══════════════
def face_neon2():
    img = radial_bg((16, 10, 34), (0, 0, 4))
    CY, MG, VI = (0, 235, 255), (255, 50, 200), (150, 80, 255)
    # synthwave perspektif ızgara (alt yarı)
    gr = Image.new("RGBA", (F, F), (0, 0, 0, 0)); gd = ImageDraw.Draw(gr)
    hy = 300 * S
    for i in range(-14, 15):
        gd.line((C + i * 10 * S, hy, C + i * 70 * S, F), fill=(*MG, 70), width=S)
    y = hy; step = 6 * S
    while y < F:
        gd.line((0, y, F, y), fill=(*MG, 60), width=S); step *= 1.25; y += step
    fade = Image.new("L", (F, F), 0); fd = ImageDraw.Draw(fade)
    for yy in range(hy, F):
        fd.line((0, yy, F, yy), fill=int(255 * min(1, (yy - hy) / (F - hy) * 1.6)))
    gr.putalpha(ImageChops.multiply(gr.split()[3], fade))
    img.alpha_composite(gr)
    # tarama çizgileri
    sl = Image.new("RGBA", (F, F), (0, 0, 0, 0)); sd = ImageDraw.Draw(sl)
    for yy in range(0, F, 4 * S): sd.line((0, yy, F, yy), fill=(0, 0, 0, 40), width=S)
    img.alpha_composite(sl)
    d = ImageDraw.Draw(img)
    # geçişli neon halka (camgöbeği → pembe) + kalan kısım soluk
    R = 222 * S; bb = (C - R, C - R, C + R, C + R); P = 0.78
    d.arc(bb, 135, 405, fill=(30, 26, 60, 255), width=5 * S)
    def neon_arc(dr):
        n = 90
        for i in range(int(n * P)):
            a0 = 135 + 270 * i / n; a1 = 135 + 270 * (i + 1.2) / n
            col = lerp(CY, MG, i / n) + (255,)
            dr.arc(bb, a0, a1, fill=col, width=6 * S)
    glow(img, neon_arc, radius=10, strength=2)
    d = ImageDraw.Draw(img)
    for i in range(0, 60):
        a = i * 6
        if 132 < (a + 360) % 360 < 228 and False: continue
        d.line((*pt(206 * S, a), *pt((198 if i % 5 == 0 else 202) * S, a)), fill=(*CY, 160) if i % 5 == 0 else (90, 80, 140, 255), width=S * (2 if i % 5 == 0 else 1))
    # HUD köşe parantezleri
    for sx, sy in ((-1, -1), (1, -1)):
        x0 = C + sx * 118 * S; y0 = 64 * S
        d.line((x0, y0, x0 - sx * 18 * S, y0), fill=(*CY, 200), width=2 * S)
        d.line((x0, y0, x0, y0 + 14 * S), fill=(*CY, 200), width=2 * S)
    ctext(d, (C, 70 * S), "PAZ 18 EKİ  //  İKİNDİ 15:56 · 01:44", BAHN(14, "SemiBold Condensed"), (170, 160, 230, 255))
    # renk kaymalı parlayan saat
    tf = AGB(116)
    def tdraw(dr, col, dx=0):
        ctext(dr, (C + dx * S, 142 * S), "14:32", tf, col)
    lay = Image.new("RGBA", (F, F), (0, 0, 0, 0)); ld = ImageDraw.Draw(lay)
    tdraw(ld, (*MG, 150), -4); tdraw(ld, (*CY, 150), 4)
    img.alpha_composite(lay)
    glow(img, lambda dr: tdraw(dr, (240, 252, 255, 255)), radius=12, strength=1)
    d = ImageDraw.Draw(img)
    ctext(d, (C + 150 * S, 124 * S), "27", BAHN(18, "Bold Condensed"), CY + (255,))
    # cam panel
    x0, x1, y0, y1 = C - 168 * S, C + 168 * S, 204 * S, 330 * S
    glass = Image.new("RGBA", (F, F), (0, 0, 0, 0)); gd = ImageDraw.Draw(glass)
    gd.rounded_rectangle((x0, y0, x1, y1), radius=18 * S, fill=(40, 30, 90, 90), outline=(*CY, 120), width=2 * S)
    img.alpha_composite(glass); d = ImageDraw.Draw(img)
    d.text((x0 + 16 * S, y0 + 10 * S), "TUPRS", font=BAHN(20, "Bold Condensed"), fill=(240, 250, 255, 255))
    d.text((x0 + 82 * S, y0 + 14 * S), "62 LOT · 5DK", font=BAHN(12, "SemiBold Condensed"), fill=(150, 140, 210, 255))
    d.text((x1 - 16 * S, y0 + 10 * S), "+582 ₺  +%2,5", font=BAHN(20, "Bold Condensed"), fill=CY + (255,), anchor="ra")
    cx0, cx1, cy0, cy1 = x0 + 14 * S, x1 - 64 * S, y0 + 42 * S, y1 - 12 * S
    sp = spark(46, 9); lo, hi = 348.0, 398.0
    def Y(v): return cy1 - (cy1 - cy0) * (v - lo) / (hi - lo)
    pts = [(cx0 + (cx1 - cx0) * i / (len(sp) - 1), Y(v)) for i, v in enumerate(sp)]
    area = Image.new("RGBA", (F, F), (0, 0, 0, 0)); ad = ImageDraw.Draw(area)
    ad.polygon(pts + [(cx1, cy1), (cx0, cy1)], fill=(*CY, 70))
    m = Image.new("L", (F, F), 0); md = ImageDraw.Draw(m)
    for yy in range(int(cy0), int(cy1)):
        md.line((0, yy, F, yy), fill=int(255 * (1 - (yy - cy0) / (cy1 - cy0))))
    area.putalpha(ImageChops.multiply(area.split()[3], m)); img.alpha_composite(area)
    d = ImageDraw.Draw(img)
    for v, col, lab in ((394.28, (90, 255, 170), "H 394,28"), (351.45, (255, 70, 110), "S 351,45")):
        yy = Y(v)
        for xx in range(int(cx0), int(cx1), 10 * S): d.line((xx, yy, xx + 5 * S, yy), fill=col + (230,), width=2 * S)
        d.text((cx0 + 2 * S, yy - 3 * S), lab, font=BAHN(12, "Bold Condensed"), fill=col + (255,), anchor="lb")
    glow(img, lambda dr: dr.line(pts, fill=CY + (255,), width=3 * S, joint="curve"), radius=6, strength=2)
    d = ImageDraw.Draw(img)
    lx, ly = pts[-1]
    glow(img, lambda dr: dr.ellipse((lx - 7 * S, ly - 7 * S, lx + 7 * S, ly + 7 * S), fill=(255, 255, 255, 255)), radius=8)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((lx + 8 * S, ly - 11 * S, lx + 58 * S, ly + 11 * S), radius=6 * S, fill=CY + (255,))
    ctext(d, (lx + 33 * S, ly), "384,90", BAHN(13, "Bold Condensed"), (10, 10, 30, 255))
    # alt durum çubuğu
    d.rounded_rectangle((C - 120 * S, 352 * S, C + 120 * S, 378 * S), radius=13 * S, fill=(20, 14, 44, 220), outline=(*VI, 160), width=2 * S)
    d.ellipse((C - 108 * S, 360 * S, C - 98 * S, 370 * S), fill=(90, 255, 170, 255))
    d.text((C - 92 * S, 365 * S), "DEVAM", font=BAHN(13, "Bold Condensed"), fill=(90, 255, 170, 255), anchor="lm")
    ctext(d, (C + 30 * S, 365 * S), "NABIZ 77  ·  PİL 74%", BAHN(13, "SemiBold Condensed"), (180, 170, 230, 255))
    return img


if __name__ == "__main__":
    faces = [("B · LUXURY  (yeni)", "Giyoş desen, kabartmalı altın indeksler, gölgeli dauphine ibreler, tarih penceresi", face_lux2()),
             ("C · NEON TRADER  (yeni)", "Synthwave ızgara, geçişli neon halka, renk kaymalı saat, cam panelde alan grafiği", face_neon2())]
    tiles = [watch(f) for _, _, f in faces]
    tw = tiles[0].width; gap = 70 * S
    W = tw * 2 + gap * 3; H = tw + 190 * S
    cv = Image.new("RGBA", (W, H), (22, 22, 24, 255)); dd = ImageDraw.Draw(cv)
    for i, (name, sub, _) in enumerate(faces):
        x = gap + i * (tw + gap)
        cv.alpha_composite(tiles[i], (x, 40 * S))
        dd.text((x + tw / 2, tw + 80 * S), name, font=BAHN(30, "Bold Condensed"), fill=(240, 240, 235, 255), anchor="mm")
        dd.text((x + tw / 2, tw + 122 * S), sub, font=BAHN(18, "SemiCondensed"), fill=(150, 150, 150, 255), anchor="mm")
    cv.resize((W // S, H // S), Image.LANCZOS).convert("RGB").save(OUT / "kadran_BC_v2.png", quality=95)
    print("ok")
