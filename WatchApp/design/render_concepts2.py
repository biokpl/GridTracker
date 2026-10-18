"""Ek premium kadran konseptleri — D Taktik, E Hibrit Analog, F Retro LCD."""
import math, random
from PIL import Image, ImageDraw, ImageFilter
from render_concepts import (S, F, C, OUT, pt, lerp, radial_bg, glow, ctext, moon, heart,
                             BAHN, SEG, AGB, SYM, watch, spark, font)


# ═══════════════ D · TAKTİK (Oogly / askeri) ═══════════════
def face_tactical():
    img = radial_bg((46, 52, 34), (10, 12, 8))
    # kamuflaj lekeleri
    cam = Image.new("RGBA", (F, F), (0, 0, 0, 0)); cd = ImageDraw.Draw(cam)
    random.seed(11)
    for _ in range(70):
        x, y, r = random.randint(0, F), random.randint(0, F), random.randint(25, 70) * S
        cd.ellipse((x - r, y - r * 0.6, x + r, y + r * 0.6), fill=random.choice([(70, 78, 48, 60), (30, 34, 22, 70), (88, 84, 60, 45)]))
    cam = cam.filter(ImageFilter.GaussianBlur(6 * S)); img.alpha_composite(cam)
    d = ImageDraw.Draw(img)
    KH, OR, LG = (200, 190, 140, 255), (255, 150, 40, 255), (150, 160, 110, 255)
    # dış pusula çerçevesi
    d.ellipse((8 * S, 8 * S, F - 8 * S, F - 8 * S), outline=(20, 22, 15, 255), width=34 * S)
    for i in range(0, 360, 5):
        big = i % 45 == 0
        d.line((*pt(234 * S, i), *pt((218 if big else 226) * S, i)), fill=KH if big else (120, 120, 90, 255), width=(3 if big else 1) * S)
    for lbl, a in (("K", 0), ("D", 90), ("G", 180), ("B", 270)):
        ctext(d, pt(205 * S, a), lbl, BAHN(16, "Bold Condensed"), OR if lbl == "K" else KH)
    # tehlike şeritli üst bant
    band = Image.new("RGBA", (F, F), (0, 0, 0, 0)); bd = ImageDraw.Draw(band)
    for k in range(-40, 40):
        x = C + k * 14 * S
        bd.polygon([(x, 118 * S), (x + 7 * S, 118 * S), (x + 15 * S, 104 * S), (x + 8 * S, 104 * S)], fill=(255, 150, 40, 120))
    m = Image.new("L", (F, F), 0); ImageDraw.Draw(m).rectangle((C - 95 * S, 104 * S, C + 95 * S, 118 * S), fill=255)
    img.paste(band, (0, 0), Image.composite(band.split()[3], Image.new("L", (F, F), 0), m))
    d = ImageDraw.Draw(img)
    ctext(d, (C, 92 * S), "PZ  18.10  ·  ALSAT OPS", BAHN(16, "Bold Condensed"), KH)
    # saat (stencil hissi: dar + boşluklu)
    t = "14:32"
    glow(img, lambda dr: ctext(dr, (C, 176 * S), t, BAHN(112, "Bold Condensed"), (225, 220, 180, 255)), radius=6, strength=1)
    d = ImageDraw.Draw(img)
    for yy in range(130, 222, 9):   # stencil kesikleri
        d.line((C - 120 * S, yy * S, C + 120 * S, yy * S), fill=(30, 34, 22, 120), width=S)
    # namaz şeridi
    d.rectangle((C - 112 * S, 232 * S, C + 112 * S, 258 * S), fill=(20, 22, 15, 230), outline=OR, width=2 * S)
    moon(d, C - 92 * S, 245 * S, 7 * S, OR)
    ctext(d, (C + 6 * S, 245 * S), "İKİNDİ 15:56  ·  01:44", BAHN(16, "Bold Condensed"), OR)
    # hedef tespit ölçeği (stop → hedef)
    x0, x1, y = C - 140 * S, C + 140 * S, 300 * S
    d.line((x0, y, x1, y), fill=LG, width=3 * S)
    for k in range(11):
        xx = x0 + (x1 - x0) * k / 10
        d.line((xx, y - (10 if k % 5 == 0 else 5) * S, xx, y + (10 if k % 5 == 0 else 5) * S), fill=LG, width=2 * S)
    px = x0 + (x1 - x0) * 0.78
    d.polygon([(px, y - 6 * S), (px - 10 * S, y - 24 * S), (px + 10 * S, y - 24 * S)], fill=OR)
    d.text((x0, y + 16 * S), "S 351,45", font=BAHN(15, "Bold Condensed"), fill=(230, 110, 90, 255))
    d.text((x1, y + 16 * S), "H 394,28", font=BAHN(15, "Bold Condensed"), fill=(170, 210, 120, 255), anchor="ra")
    d.text((x0, 268 * S), "TUPRS", font=BAHN(22, "Bold Condensed"), fill=KH)
    d.text((x1, 268 * S), "+582 ₺", font=BAHN(22, "Bold Condensed"), fill=(170, 210, 120, 255), anchor="ra")
    # alt göstergeler
    for i, (lab, val) in enumerate((("NBZ", "77"), ("PİL", "74"), ("LOT", "62"))):
        cx = C + (i - 1) * 78 * S; cy = 372 * S
        d.rectangle((cx - 32 * S, cy - 20 * S, cx + 32 * S, cy + 20 * S), outline=LG, width=2 * S, fill=(20, 22, 15, 200))
        ctext(d, (cx, cy - 8 * S), lab, BAHN(11, "Bold Condensed"), (140, 140, 105, 255))
        ctext(d, (cx, cy + 8 * S), val, BAHN(17, "Bold Condensed"), KH)
    return img


# ═══════════════ E · HİBRİT ANALOG (S4U / Matteo Dini lüks) ═══════════════
def face_hybrid():
    img = radial_bg((58, 60, 66), (14, 15, 18))
    # dikey fırçalanmış metal dokusu
    br = Image.new("RGBA", (F, F), (0, 0, 0, 0)); bd = ImageDraw.Draw(br)
    random.seed(5)
    for x in range(0, F, S):
        a = random.randint(0, 14); bd.line((x, 0, x, F), fill=(255, 255, 255, a))
    img.alpha_composite(br)
    d = ImageDraw.Draw(img)
    SIL, BLUE, TEAL = (225, 228, 232, 255), (70, 140, 230, 255), (60, 225, 170, 255)
    # saat rakamları (büyük, uygulama hissi)
    for h in range(1, 13):
        a = h * 30
        if h in (6,):
            continue
        ctext(d, pt(196 * S, a), str(h), SEG(30, "Semibold"), SIL)
    for i in range(60):
        if i % 5: d.line((*pt(234 * S, i * 6), *pt(226 * S, i * 6)), fill=(150, 152, 158, 255), width=S)
    # alt pencere: pozisyon (dijital)
    d.rounded_rectangle((C - 92 * S, C + 72 * S, C + 92 * S, C + 150 * S), radius=14 * S, fill=(10, 11, 14, 255), outline=(120, 122, 128, 255), width=2 * S)
    ctext(d, (C, C + 90 * S), "TUPRS", BAHN(16, "Bold Condensed"), (180, 182, 188, 255))
    ctext(d, (C, C + 114 * S), "+582 ₺", BAHN(26, "Bold Condensed"), TEAL)
    # stop→hedef ince bar
    bx0, bx1, by = C - 70 * S, C + 70 * S, C + 138 * S
    d.line((bx0, by, bx1, by), fill=(60, 62, 70, 255), width=4 * S)
    d.line((bx0, by, bx0 + (bx1 - bx0) * 0.78, by), fill=TEAL, width=4 * S)
    # sol alt kadran: namaz
    cx, cy, r = C - 92 * S, C - 6 * S, 48 * S
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(18, 20, 26, 255), outline=(140, 142, 148, 255), width=2 * S)
    d.arc((cx - r + 6 * S, cy - r + 6 * S, cx + r - 6 * S, cy + r - 6 * S), -90, -90 + 360 * 0.62, fill=(250, 190, 90, 255), width=4 * S)
    moon(d, cx, cy - 20 * S, 6 * S, (250, 190, 90, 255))
    ctext(d, (cx, cy + 2 * S), "01:44", BAHN(18, "Bold Condensed"), SIL)
    ctext(d, (cx, cy + 22 * S), "İKİNDİ", BAHN(11, "SemiBold Condensed"), (160, 162, 168, 255))
    # sağ alt kadran: tarih + nabız
    cx = C + 92 * S
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(18, 20, 26, 255), outline=(140, 142, 148, 255), width=2 * S)
    ctext(d, (cx, cy - 12 * S), "PAZ", BAHN(13, "SemiBold Condensed"), (160, 162, 168, 255))
    ctext(d, (cx, cy + 10 * S), "18", BAHN(28, "Bold Condensed"), BLUE)
    ctext(d, (C, 112 * S), "ALSAT · EDITION", SEG(12, "Semibold"), (150, 152, 158, 255))
    # akrep, yelkovan, saniye (14:32:27)
    def hand(angle, length, width, col, tail=18):
        x1, y1 = pt(length, angle); x0, y0 = pt(-tail * S, angle)
        nx, ny = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        w = width / 2
        poly = [(x0 + nx * w, y0 + ny * w), (x1 + nx * w * 0.5, y1 + ny * w * 0.5), (x1 - nx * w * 0.5, y1 - ny * w * 0.5), (x0 - nx * w, y0 - ny * w)]
        sh = Image.new("RGBA", (F, F), (0, 0, 0, 0)); ImageDraw.Draw(sh).polygon([(p[0] + 6 * S, p[1] + 8 * S) for p in poly], fill=(0, 0, 0, 160))
        img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(5 * S)))
        ImageDraw.Draw(img).polygon(poly, fill=col)
    hand((14 % 12) * 30 + 32 * 0.5, 120 * S, 16 * S, SIL)
    hand(32 * 6 + 27 * 0.1, 178 * S, 11 * S, SIL)
    d = ImageDraw.Draw(img)
    a = 27 * 6
    d.line((*pt(-30 * S, a), *pt(200 * S, a)), fill=(255, 120, 40, 255), width=3 * S)
    d.ellipse((C - 12 * S, C - 12 * S, C + 12 * S, C + 12 * S), fill=SIL)
    d.ellipse((C - 5 * S, C - 5 * S, C + 5 * S, C + 5 * S), fill=(255, 120, 40, 255))
    return img


# ═══════════════ F · RETRO LCD (G-Shock / Ballozi) ═══════════════
def face_lcd():
    img = radial_bg((26, 28, 30), (6, 6, 7))
    d = ImageDraw.Draw(img)
    LCD_BG, ON, GHOST = (150, 165, 140, 255), (22, 28, 20, 255), (128, 142, 120, 255)
    RED = (210, 60, 40, 255)
    # dış bezel yazıları
    for txt_, a in (("TRADER", 315), ("PRO", 45), ("ALSAT", 135), ("BIST", 225)):
        ctext(d, pt(212 * S, a), txt_, BAHN(15, "Bold Condensed"), (200, 60, 50, 255) if txt_ == "ALSAT" else (150, 150, 150, 255))
    # LCD paneli
    def lcd(box, r=10):
        d.rounded_rectangle(box, radius=r * S, fill=LCD_BG, outline=(60, 64, 60, 255), width=3 * S)
    lcd((C - 160 * S, 120 * S, C + 160 * S, 250 * S), 18)
    lcd((C - 160 * S, 262 * S, C + 160 * S, 340 * S), 12)
    f7 = AGB(96)
    ctext(d, (C - 10 * S, 188 * S), "88:88", f7, GHOST)          # sönük segmentler
    ctext(d, (C - 10 * S, 188 * S), "14:32", f7, ON)
    ctext(d, (C + 132 * S, 204 * S), "27", AGB(34), ON)
    d.text((C - 148 * S, 128 * S), "PZ  10-18", font=BAHN(16, "Bold Condensed"), fill=ON)
    d.text((C + 148 * S, 128 * S), "İKİ 15:56", font=BAHN(16, "Bold Condensed"), fill=ON, anchor="ra")
    # alt LCD: pozisyon
    d.text((C - 148 * S, 270 * S), "TUPRS", font=BAHN(22, "Bold Condensed"), fill=ON)
    d.text((C + 148 * S, 270 * S), "+582", font=AGB(34), fill=ON, anchor="ra")
    # segment bar stop→hedef
    n = 20
    for i in range(n):
        xx = C - 148 * S + i * 15 * S
        d.rectangle((xx, 312 * S, xx + 11 * S, 328 * S), fill=ON if i < int(n * 0.78) else GHOST)
    # kenar göstergeleri
    ctext(d, (C - 120 * S, 362 * S), "S 351", BAHN(16, "Bold Condensed"), (230, 120, 100, 255))
    ctext(d, (C, 362 * S), "01:44 KALAN", BAHN(14, "Bold Condensed"), (180, 180, 180, 255))
    ctext(d, (C + 120 * S, 362 * S), "H 394", BAHN(16, "Bold Condensed"), (150, 220, 140, 255))
    heart(d, C - 30 * S, 392 * S, 13, RED); ctext(d, (C - 12 * S, 392 * S), "77", BAHN(14, "Bold Condensed"), (180, 180, 180, 255))
    ctext(d, (C + 30 * S, 392 * S), "74%", BAHN(14, "Bold Condensed"), (180, 180, 180, 255))
    d.ellipse((C - 6 * S, 88 * S, C + 6 * S, 100 * S), fill=RED)
    return img


if __name__ == "__main__":
    faces = [("D · TAKTİK", "Oogly tarzı: kamuflaj, pusula, tehlike şeridi, hedef ölçeği", face_tactical()),
             ("E · HİBRİT ANALOG", "S4U / Matteo Dini tarzı: fırçalanmış metal, gerçek akrep-yelkovan", face_hybrid()),
             ("F · RETRO LCD", "G-Shock / Ballozi tarzı: sönük segmentli LCD, segment gösterge", face_lcd())]
    tiles = [watch(f) for _, _, f in faces]
    tw = tiles[0].width; gap = 60 * S
    W = tw * 3 + gap * 4; H = tw + 190 * S
    cv = Image.new("RGBA", (W, H), (22, 22, 24, 255)); dd = ImageDraw.Draw(cv)
    for i, (name, sub, _) in enumerate(faces):
        x = gap + i * (tw + gap)
        cv.alpha_composite(tiles[i], (x, 40 * S))
        dd.text((x + tw / 2, tw + 80 * S), name, font=BAHN(30, "Bold Condensed"), fill=(240, 240, 235, 255), anchor="mm")
        dd.text((x + tw / 2, tw + 122 * S), sub, font=BAHN(18, "SemiCondensed"), fill=(150, 150, 150, 255), anchor="mm")
    cv.resize((W // S, H // S), Image.LANCZOS).convert("RGB").save(OUT / "kadran_konseptleri_v3.png", quality=95)
    print("ok")
