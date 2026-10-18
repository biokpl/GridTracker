"""Kadran konsept görselleri (tasarım önizlemesi) — PIL ile 2x süper örnekleme."""
import math, random
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

OUT = Path(__file__).parent
S = 2                 # süper örnekleme
F = 480 * S           # kadran çapı (px)
FD = "C:/Windows/Fonts/"


def font(name, size, var=None):
    f = ImageFont.truetype(FD + name, int(size * S))
    if var:
        try: f.set_variation_by_name(var)
        except Exception: pass
    return f

def BAHN(sz, var="Bold Condensed"): return font("bahnschrift.ttf", sz, var)
def SEG(sz, var="Light"):           return font("SegUIVar.ttf", sz, var)
def AGB(sz):                        return font("AGENCYB.TTF", sz)
def SYM(sz):                        return font("seguisym.ttf", sz)

def heart(d, x, y, sz, col):
    d.text((x, y), "♥", font=SYM(sz), fill=col, anchor="mm")

C = F // 2


def pt(r, deg):
    t = math.radians(deg - 90)
    return C + r * math.cos(t), C + r * math.sin(t)


def lerp(a, b, t): return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(len(a)))


def radial_bg(c_in, c_out):
    img = Image.new("RGBA", (F, F))
    px = img.load()
    for y in range(0, F, 2):
        for x in range(0, F, 2):
            d = min(1.0, math.hypot(x - C, y - C) / C)
            col = lerp(c_in, c_out, d ** 1.4) + (255,)
            px[x, y] = col; px[x + 1, y] = col; px[x, y + 1] = col; px[x + 1, y + 1] = col
    return img


def glow(base, draw_fn, radius=10, strength=2):
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(layer))
    g = layer.filter(ImageFilter.GaussianBlur(radius * S))
    for _ in range(strength):
        base.alpha_composite(g)
    base.alpha_composite(layer)


def ctext(d, xy, text, f, fill, anchor="mm"):
    d.text(xy, text, font=f, fill=fill, anchor=anchor)


def moon(d, x, y, r, col):
    d.ellipse((x - r, y - r, x + r, y + r), fill=col)
    d.ellipse((x - r + r * 0.55, y - r - r * 0.15, x + r + r * 0.55, y + r - r * 0.15), fill=(0, 0, 0, 0))


def circle_mask():
    m = Image.new("L", (F, F), 0)
    ImageDraw.Draw(m).ellipse((0, 0, F - 1, F - 1), fill=255)
    return m


def spark(n=40, seed=3):
    random.seed(seed); v = 372.0; out = []
    for i in range(n):
        v += random.uniform(-1.6, 2.2) + (0.35 if i > n * 0.6 else 0)
        out.append(v)
    out[-1] = 384.9
    return out


# ═══════════════════════ 1 · ULTRA PRO (spor / teknik) ═══════════════════════
def face_ultra():
    img = radial_bg((24, 30, 36), (4, 5, 6))
    # karbon dokusu
    tex = Image.new("RGBA", (F, F), (0, 0, 0, 0)); td = ImageDraw.Draw(tex)
    for k in range(-F, F, 7 * S):
        td.line((k, 0, k + F, F), fill=(255, 255, 255, 7), width=S)
    img.alpha_composite(tex)
    d = ImageDraw.Draw(img)
    # dış dakika çizgileri + rakamlar
    for i in range(60):
        a = i * 6; big = i % 5 == 0
        r0, r1 = 236 * S, (222 if big else 229) * S
        d.line((*pt(r0, a), *pt(r1, a)), fill=(150, 150, 145, 255) if big else (70, 72, 75, 255), width=(3 if big else 1) * S)
    fnum = BAHN(15, "SemiBold Condensed")
    for i in range(0, 60, 5):
        if i in (25, 30, 35):  # alt boşluk (halka açıklığı)
            continue
        ctext(d, pt(207 * S, i * 6), f"{i:02d}", fnum, (110, 112, 115, 255))
    # segmentli ilerleme yayı: stop (225°) → hedef (495°)
    P, N = 0.78, 42
    R = 186 * S
    lit = int(N * P)
    seg_w = 270 / N
    def segs(dr, only_lit):
        for i in range(N):
            a0 = 225 + i * seg_w + 0.9; a1 = a0 + seg_w - 1.8
            on = i < lit
            if only_lit and not on: continue
            t = i / (N - 1)
            col = lerp((255, 85, 80), (255, 190, 60), t * 2) if t < 0.5 else lerp((255, 190, 60), (60, 225, 170), (t - 0.5) * 2)
            col = col + (255,) if on else (38, 40, 44, 255)
            bb = (C - R, C - R, C + R, C + R)
            dr.arc(bb, a0 - 90, a1 - 90, fill=col, width=16 * S)
    segs(d, False)
    glow(img, lambda dr: segs(dr, True), radius=7, strength=1)
    d = ImageDraw.Draw(img)
    # fiyat işaretçisi
    pa = 225 + 270 * P
    px_, py_ = pt(R, pa)
    glow(img, lambda dr: dr.ellipse((px_ - 13 * S, py_ - 13 * S, px_ + 13 * S, py_ + 13 * S), fill=(255, 255, 255, 255)), radius=8)
    d = ImageDraw.Draw(img)
    # S / H uç etiketleri
    # namaz çipi
    chip = (C - 108 * S, 214 * S, C + 108 * S, 246 * S)
    d.rounded_rectangle(chip, radius=17 * S, fill=(40, 28, 8, 255), outline=(150, 100, 25, 255), width=2 * S)
    moon(d, C - 84 * S, 230 * S, 8 * S, (250, 199, 117, 255))
    ctext(d, (C + 8 * S, 230 * S), "İKİNDİ 15:56  ·  01:44", BAHN(17, "SemiBold Condensed"), (250, 199, 117, 255))
    # tarih + saat
    ctext(d, (C, 92 * S), "PAZAR  18 EKİM", BAHN(16, "SemiBold Condensed"), (140, 145, 150, 255))
    glow(img, lambda dr: ctext(dr, (C - 14 * S, 156 * S), "14:32", BAHN(118, "Bold Condensed"), (245, 245, 240, 255)), radius=12, strength=1)
    d = ImageDraw.Draw(img)
    ctext(d, (C + 128 * S, 136 * S), "27", BAHN(30, "Bold Condensed"), (60, 225, 170, 255))
    ctext(d, (C + 128 * S, 166 * S), "SN", BAHN(12, "SemiBold Condensed"), (90, 95, 100, 255))
    # pozisyon paneli
    panel = (C - 150 * S, 258 * S, C + 150 * S, 336 * S)
    d.rounded_rectangle(panel, radius=20 * S, fill=(14, 18, 22, 235), outline=(45, 52, 58, 255), width=2 * S)
    d.text((C - 132 * S, 268 * S), "TUPRS", font=BAHN(28, "Bold Condensed"), fill=(240, 240, 235, 255))
    d.text((C - 132 * S, 302 * S), "62 LOT · 384,90", font=BAHN(15, "SemiBold Condensed"), fill=(130, 135, 140, 255))
    # mini grafik
    sp = spark(); lo, hi = min(sp), max(sp)
    gx0, gx1, gy0, gy1 = C - 22 * S, C + 50 * S, 272 * S, 324 * S
    pts = [(gx0 + (gx1 - gx0) * i / (len(sp) - 1), gy1 - (gy1 - gy0) * (v - lo) / (hi - lo)) for i, v in enumerate(sp)]
    glow(img, lambda dr: dr.line(pts, fill=(60, 225, 170, 255), width=3 * S, joint="curve"), radius=5)
    d = ImageDraw.Draw(img)
    d.text((C + 140 * S, 270 * S), "+582 ₺", font=BAHN(28, "Bold Condensed"), fill=(60, 225, 170, 255), anchor="ra")
    d.text((C + 140 * S, 304 * S), "+%2,5", font=BAHN(16, "SemiBold Condensed"), fill=(60, 225, 170, 255), anchor="ra")
    # stop / hedef değerleri
    ctext(d, (C - 70 * S, 356 * S), "S 351,45", BAHN(18, "SemiBold Condensed"), (255, 120, 110, 255))
    ctext(d, (C + 70 * S, 356 * S), "H 394,28", BAHN(18, "SemiBold Condensed"), (110, 230, 170, 255))
    # nabız / pil
    fs = BAHN(15, "SemiBold Condensed")
    heart(d, C - 56 * S, 388 * S, 15, (255, 90, 110, 255)); ctext(d, (C - 36 * S, 388 * S), "77", fs, (200, 200, 200, 255))
    d.rounded_rectangle((C + 10 * S, 381 * S, C + 44 * S, 395 * S), radius=3 * S, outline=(120, 125, 130, 255), width=2 * S)
    d.rectangle((C + 13 * S, 384 * S, C + 13 * S + int(28 * S * 0.74), 392 * S), fill=(120, 220, 120, 255))
    ctext(d, (C + 66 * S, 388 * S), "74%", fs, (140, 145, 150, 255))
    return img


# ═══════════════════════ 2 · LUXURY (lüks kronograf) ═══════════════════════
def face_lux():
    img = radial_bg((22, 30, 52), (3, 4, 10))
    sun = Image.new("RGBA", (F, F), (0, 0, 0, 0)); sd = ImageDraw.Draw(sun)
    for a in range(0, 360, 2):
        sd.line((C, C, *pt(F, a)), fill=(255, 255, 255, 6), width=S)
    img.alpha_composite(sun)
    d = ImageDraw.Draw(img)
    GOLD, GOLD2 = (222, 184, 110, 255), (150, 118, 62, 255)
    d.ellipse((6 * S, 6 * S, F - 6 * S, F - 6 * S), outline=GOLD2, width=2 * S)
    for i in range(60):
        a = i * 6
        if i % 5 == 0:
            x0, y0 = pt(226 * S, a); x1, y1 = pt(200 * S, a)
            d.line((x0, y0, x1, y1), fill=GOLD, width=6 * S)
        else:
            d.line((*pt(226 * S, a), *pt(218 * S, a)), fill=(120, 110, 90, 255), width=S)
    # alt kadranlar
    def subdial(cx, cy, r, frac, col, top, mid, bot):
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(8, 10, 20, 255), outline=(70, 66, 56, 255), width=2 * S)
        bb = (cx - r + 8 * S, cy - r + 8 * S, cx + r - 8 * S, cy + r - 8 * S)
        d.arc(bb, -225 + 0, -225 + 270, fill=(40, 42, 55, 255), width=6 * S)
        d.arc(bb, 135, 135 + 270 * frac, fill=col, width=6 * S)
        ctext(d, (cx, cy - 18 * S), top, BAHN(11, "SemiBold Condensed"), (150, 140, 120, 255))
        ctext(d, (cx, cy + 4 * S), mid, BAHN(20, "Bold Condensed"), (240, 230, 210, 255))
        ctext(d, (cx, cy + 24 * S), bot, BAHN(11, "SemiBold Condensed"), (150, 140, 120, 255))
    subdial(C - 110 * S, C + 40 * S, 56 * S, 0.62, (250, 190, 90, 255), "İKİNDİ", "01:44", "15:56")
    subdial(C + 110 * S, C + 40 * S, 56 * S, 0.74, (120, 200, 140, 255), "NABIZ", "77", "PİL 74%")
    # orta pozisyon kadranı (büyük)
    cx, cy, r = C, C + 128 * S, 70 * S
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(8, 10, 20, 255), outline=GOLD2, width=2 * S)
    bb = (cx - r + 9 * S, cy - r + 9 * S, cx + r - 9 * S, cy + r - 9 * S)
    d.arc(bb, 135, 135 + 270, fill=(40, 42, 55, 255), width=8 * S)
    glow(img, lambda dr: dr.arc(bb, 135, 135 + 270 * 0.78, fill=GOLD, width=8 * S), radius=6, strength=1)
    d = ImageDraw.Draw(img)
    ctext(d, (cx, cy - 26 * S), "TUPRS", BAHN(16, "Bold Condensed"), GOLD)
    ctext(d, (cx, cy + 2 * S), "+582 ₺", BAHN(26, "Bold Condensed"), (120, 220, 160, 255))
    ctext(d, (cx, cy + 28 * S), "351 – 394", BAHN(12, "SemiBold Condensed"), (150, 140, 120, 255))
    # saat
    ctext(d, (C, 104 * S), "PAZAR · 18 EKİM", BAHN(15, "SemiBold Condensed"), GOLD)
    glow(img, lambda dr: ctext(dr, (C, 168 * S), "14:32", SEG(104, "Light"), (248, 244, 236, 255)), radius=10, strength=1)
    return img


# ═══════════════════════ 3 · NEON TRADER (grafik) ═══════════════════════
def face_neon():
    img = radial_bg((10, 12, 22), (0, 0, 0))
    d = ImageDraw.Draw(img)
    CY, MG = (0, 230, 255, 255), (255, 60, 200, 255)
    # ince neon halka (ilerleme)
    R = 222 * S; bb = (C - R, C - R, C + R, C + R)
    d.arc(bb, 135, 135 + 270, fill=(25, 30, 45, 255), width=6 * S)
    glow(img, lambda dr: dr.arc(bb, 135, 135 + 270 * 0.78, fill=CY, width=6 * S), radius=9, strength=2)
    d = ImageDraw.Draw(img)
    # saat (dijital)
    ctext(d, (C, 82 * S), "PAZ 18 EKİ  ·  İKİNDİ 15:56", BAHN(15, "SemiBold Condensed"), (120, 130, 160, 255))
    glow(img, lambda dr: ctext(dr, (C, 152 * S), "14:32", AGB(120), (235, 250, 255, 255)), radius=12, strength=2)
    d = ImageDraw.Draw(img)
    # grafik paneli: mumlar + stop/hedef çizgileri
    x0, x1, y0, y1 = C - 160 * S, C + 160 * S, 226 * S, 330 * S
    d.rounded_rectangle((x0 - 10 * S, y0 - 14 * S, x1 + 10 * S, y1 + 10 * S), radius=16 * S, fill=(10, 14, 26, 255), outline=(35, 45, 70, 255), width=2 * S)
    for k in range(1, 4):
        yy = y0 + (y1 - y0) * k / 4
        d.line((x0, yy, x1, yy), fill=(30, 38, 60, 255), width=S)
    lo, hi = 348.0, 398.0
    def Y(v): return y1 - (y1 - y0) * (v - lo) / (hi - lo)
    d.line((x0, Y(351.45), x1, Y(351.45)), fill=(255, 80, 90, 255), width=2 * S)
    d.line((x0, Y(394.28), x1, Y(394.28)), fill=(90, 240, 160, 255), width=2 * S)
    d.text((x1, Y(394.28) - 3 * S), "H 394,28", font=BAHN(12, "SemiBold Condensed"), fill=(90, 240, 160, 255), anchor="rb")
    d.text((x1, Y(351.45) + 3 * S), "S 351,45", font=BAHN(12, "SemiBold Condensed"), fill=(255, 80, 90, 255), anchor="rt")
    random.seed(7); v = 366.0; n = 18; w = (x1 - x0 - 70 * S) / n
    for i in range(n):
        o = v; c = v + random.uniform(-4, 5) + (1.2 if i > 10 else 0); h = max(o, c) + random.uniform(0.5, 2.5); l = min(o, c) - random.uniform(0.5, 2.5)
        if i == n - 1: c = 384.9
        xc = x0 + 8 * S + i * w + w / 2; col = CY if c >= o else MG
        d.line((xc, Y(h), xc, Y(l)), fill=col, width=S)
        d.rectangle((xc - w * 0.32, Y(max(o, c)), xc + w * 0.32, Y(min(o, c)) + 1), fill=col)
        v = c
    glow(img, lambda dr: dr.ellipse((xc - 6 * S, Y(384.9) - 6 * S, xc + 6 * S, Y(384.9) + 6 * S), fill=(255, 255, 255, 255)), radius=6)
    d = ImageDraw.Draw(img)
    # alt bilgi
    d.text((C - 150 * S, 352 * S), "TUPRS", font=BAHN(26, "Bold Condensed"), fill=(235, 250, 255, 255))
    d.text((C + 150 * S, 352 * S), "+582 ₺  +%2,5", font=BAHN(24, "Bold Condensed"), fill=CY, anchor="ra")
    ctext(d, (C, 404 * S), "DEVAM  ·  62 LOT  ·  NABIZ 77  ·  PİL 74%", BAHN(14, "SemiBold Condensed"), (110, 120, 150, 255))
    return img


def watch(face):
    """Galaxy Watch Ultra benzeri yastık kasa + yüz."""
    W = int(F * 1.22)
    case = Image.new("RGBA", (W, W), (0, 0, 0, 0)); cd = ImageDraw.Draw(case)
    for k in range(40):
        t = k / 39
        col = lerp((95, 98, 102), (40, 42, 45), t) + (255,)
        inset = int(k * S * 0.6)
        cd.rounded_rectangle((inset, inset, W - inset, W - inset), radius=int(W * 0.30), outline=col, width=3 * S)
    cd.rounded_rectangle((24 * S, 24 * S, W - 24 * S, W - 24 * S), radius=int(W * 0.27), fill=(18, 18, 20, 255))
    o = (W - F) // 2
    cd.ellipse((o - 10 * S, o - 10 * S, o + F + 10 * S, o + F + 10 * S), fill=(8, 8, 9, 255))
    face_c = Image.new("RGBA", (F, F)); face_c.paste(face, (0, 0), circle_mask())
    case.alpha_composite(face_c, (o, o))
    cd.rounded_rectangle((W - 6 * S, int(W * 0.38), W + 0, int(W * 0.50)), radius=4 * S, fill=(230, 110, 40, 255))
    return case


def single(face, name, path):
    t = watch(face); W = t.width + 120 * S; H = t.height + 130 * S
    cv = Image.new("RGBA", (W, H), (22, 22, 24, 255)); cv.alpha_composite(t, (60 * S, 30 * S))
    ImageDraw.Draw(cv).text((W / 2, t.height + 75 * S), name, font=BAHN(30, "Bold Condensed"), fill=(240, 240, 235, 255), anchor="mm")
    cv.resize((W // S, H // S), Image.LANCZOS).convert("RGB").save(path, quality=95)


if __name__ == "__main__" and "--a" in __import__("sys").argv:
    single(face_ultra(), "A · ULTRA PRO (namaz saatin altında)", OUT / "kadran_A_v2.png"); raise SystemExit

if __name__ == "__main__":
    faces = [("A · ULTRA PRO", "Spor / teknik: segmentli renkli gösterge, dakika skalası, mini grafik", face_ultra()),
             ("B · LUXURY", "Lüks kronograf: güneş ışını doku, altın indeksler, 3 alt kadran", face_lux()),
             ("C · NEON TRADER", "Borsa ekranı: canlı mum grafiği, stop/hedef çizgileri, neon", face_neon())]
    tiles = [watch(f) for _, _, f in faces]
    tw = tiles[0].width
    gap = 60 * S
    W = tw * 3 + gap * 4; H = tw + 190 * S
    canvas = Image.new("RGBA", (W, H), (22, 22, 24, 255)); cd = ImageDraw.Draw(canvas)
    for i, (name, sub, _) in enumerate(faces):
        x = gap + i * (tw + gap)
        canvas.alpha_composite(tiles[i], (x, 40 * S))
        cd.text((x + tw / 2, tw + 80 * S), name, font=BAHN(30, "Bold Condensed"), fill=(240, 240, 235, 255), anchor="mm")
        cd.text((x + tw / 2, tw + 122 * S), sub, font=BAHN(18, "SemiCondensed"), fill=(150, 150, 150, 255), anchor="mm")
    canvas = canvas.resize((W // S, H // S), Image.LANCZOS)
    canvas.convert("RGB").save(OUT / "kadran_konseptleri_v2.png", quality=95)
    print("ok", canvas.size)
