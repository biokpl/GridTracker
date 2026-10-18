"""VFD (vakum floresan ekran) temalı kadran — normal + AOD, iki renk paleti."""
import math, random
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont
import numpy as np

S = 2; N = 480 * S; C = N / 2
OUT = Path(__file__).parent


def bf(var, sz):
    f = ImageFont.truetype("C:/Windows/Fonts/bahnschrift.ttf", int(sz * S)); f.set_variation_by_name(var); return f


def pt(rad, deg):
    t = math.radians(deg - 90); return C + rad * math.cos(t), C + rad * math.sin(t)


def bloom(img, layer, r1=4, r2=14, k=(1.0, 0.9)):
    """Floresan ışıma: keskin katman + yakın hale + uzak hale."""
    for rad, kk in ((r2, k[1]), (r1, k[0])):
        g = layer.filter(ImageFilter.GaussianBlur(rad * S))
        a = np.array(g).astype(np.float32); a[..., 3] *= kk
        img.alpha_composite(Image.fromarray(a.clip(0, 255).astype(np.uint8)))
    img.alpha_composite(layer)


# ── 7 segment ───────────────────────────────────────────────────────────────
SEG = {"0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc", "5": "afgcd",
       "6": "afgedc", "7": "abc", "8": "abcdefg", "9": "abcdfg"}


def seg_polys(x, y, w, h, t, slant=0.12):
    """Eğik 7-segment çokgenleri (x,y sol üst)."""
    def P(px, py): return (x + px + (h - py) * slant, y + py)
    hw = t / 2; g = t * 0.18
    def hseg(py):
        return [P(hw + g, py), P(w - hw - g, py), P(w - g, py + 0) if False else P(w - hw - g + hw, py), P(w - hw - g, py + 0)]
    def H(py):
        return [P(g + hw, py - hw), P(w - g - hw, py - hw), P(w - g, py), P(w - g - hw, py + hw), P(g + hw, py + hw), P(g, py)]
    def V(px, y0, y1):
        return [P(px, y0 + g), P(px + hw, y0 + g + hw), P(px + hw, y1 - g - hw), P(px, y1 - g), P(px - hw, y1 - g - hw), P(px - hw, y0 + g + hw)]
    return {"a": H(hw), "g": H(h / 2), "d": H(h - hw),
            "f": V(hw, hw, h / 2), "b": V(w - hw, hw, h / 2),
            "e": V(hw, h / 2, h - hw), "c": V(w - hw, h / 2, h - hw)}


def draw_7seg(on_d, off_d, text, x, y, w, h, t, gap, col_on, col_off):
    cx = x
    for ch in text:
        if ch == ":":
            for fy in (0.32, 0.68):
                rr = t * 0.55
                on_d.ellipse((cx + t * 0.6 - rr + h * 0.12 * (1 - fy), y + h * fy - rr, cx + t * 0.6 + rr + h * 0.12 * (1 - fy), y + h * fy + rr), fill=col_on)
            cx += t * 1.3 + gap; continue
        polys = seg_polys(cx, y, w, h, t)
        lit = SEG.get(ch, "")
        for k, poly in polys.items():
            (on_d if k in lit else off_d).polygon(poly, fill=col_on if k in lit else col_off)
        cx += w + gap
    return cx


def text_w(text, w, t, gap):
    return sum((t * 1.3 + gap) if ch == ":" else (w + gap) for ch in text) - gap


# ── kadran ──────────────────────────────────────────────────────────────────
def face(pal, aod=False):
    MAIN, ACC, WARN, GOOD = pal["main"], pal["acc"], pal["warn"], pal["good"]
    base = Image.new("RGBA", (N, N), (0, 0, 0, 255))
    if not aod:
        y, x = np.mgrid[0:N, 0:N]; dd = np.sqrt((x - C) ** 2 + (y - C) ** 2) / C
        tint = np.array(pal["bg"]) * np.clip(1 - dd ** 1.6, 0, 1)[..., None]
        base = Image.fromarray(np.dstack([tint.clip(0, 255), np.full((N, N), 255)]).astype(np.uint8))
    glow_l = Image.new("RGBA", (N, N), (0, 0, 0, 0)); gd = ImageDraw.Draw(glow_l)
    ghost_l = Image.new("RGBA", (N, N), (0, 0, 0, 0)); hd = ImageDraw.Draw(ghost_l)
    dim = 0.55 if aod else 1.0
    def c(col, a=255): return tuple(int(v * dim) for v in col) + (a,)
    GH = tuple(int(v * 0.10) for v in MAIN) + (255,)

    # halka: 42 segment, yanan / sönük
    R = 212 * S; P = 0.78; Nn = 42
    for i in range(Nn):
        a0 = 225 + i * 270 / Nn + 1.0; a1 = a0 + 270 / Nn - 2.0
        bb = (C - R, C - R, C + R, C + R)
        if i < int(Nn * P):
            t = i / (Nn - 1)
            col = pal["ring"][0] if t < 0.33 else pal["ring"][1] if t < 0.66 else pal["ring"][2]
            gd.arc(bb, a0 - 90, a1 - 90, fill=c(col), width=14 * S)
        elif not aod:
            hd.arc(bb, a0 - 90, a1 - 90, fill=GH, width=14 * S)
    px_, py_ = pt(R, 225 + 270 * P)
    gd.ellipse((px_ - 9 * S, py_ - 9 * S, px_ + 9 * S, py_ + 9 * S), fill=c((255, 255, 255)))

    # saat (7 segment)
    w, h, t, gap = 44 * S, 90 * S, 10 * S, 9 * S
    tw = text_w("19:03", w, t, gap)
    x0 = C - tw / 2 - 20 * S; y0 = 112 * S
    if not aod: draw_7seg(hd, hd, "88:88", x0, y0, w, h, t, gap, GH, GH)
    draw_7seg(gd, hd if not aod else ImageDraw.Draw(Image.new("RGBA", (1, 1))), "19:03", x0, y0, w, h, t, gap, c(MAIN), GH)
    if not aod:
        sw, sh_, st = 16 * S, 30 * S, 4 * S
        draw_7seg(hd, hd, "88", x0 + tw + 12 * S, y0 + 4 * S, sw, sh_, st, 4 * S, GH, GH)
        draw_7seg(gd, hd, "53", x0 + tw + 12 * S, y0 + 4 * S, sw, sh_, st, 4 * S, c(ACC), GH)

    f = bf("SemiBold Condensed", 22); fb = bf("Bold Condensed", 30); fs = bf("SemiBold Condensed", 18)
    gd.text((C, 88 * S), "PAZ  18 EKİM", font=f, fill=c(MAIN), anchor="mm")
    # namaz kutusu (VFD çerçeve)
    bx0, by0, bx1, by1 = C - 128 * S, 222 * S, C + 128 * S, 260 * S
    if not aod: gd.rounded_rectangle((bx0, by0, bx1, by1), radius=8 * S, outline=c(WARN, 200), width=2 * S)
    gd.text((C - 40 * S, 241 * S), "YATSI 19:46", font=bf("SemiBold Condensed", 23), fill=c(WARN), anchor="mm")
    if not aod: gd.line((C + 50 * S, by0 + 8 * S, C + 50 * S, by1 - 8 * S), fill=c(WARN, 160), width=2 * S)
    gd.text((C + 90 * S, 241 * S), "00:42", font=bf("SemiBold Condensed", 23), fill=c(WARN), anchor="mm")
    # pozisyon paneli
    if not aod:
        gd.rounded_rectangle((C - 140 * S, 272 * S, C + 140 * S, 358 * S), radius=10 * S, outline=c(MAIN, 120), width=2 * S)
        for xx in range(int(C - 132 * S), int(C + 132 * S), 6 * S): hd.point((xx, 314 * S), fill=GH)
    gd.text((C - 124 * S, 296 * S), "TUPRS", font=fb, fill=c(MAIN), anchor="lm")
    gd.text((C + 124 * S, 296 * S), "+582 ₺", font=fb, fill=c(GOOD), anchor="rm")
    if not aod:
        gd.text((C - 124 * S, 336 * S), "62 LOT · 375,50", font=fs, fill=c(MAIN, 200), anchor="lm")
        gd.text((C + 124 * S, 336 * S), "+%2,5", font=fs, fill=c(GOOD, 220), anchor="rm")
        random.seed(5); v = 0.5; pts = []
        for i in range(30):
            v = min(0.95, max(0.05, v + random.uniform(-0.12, 0.13))); pts.append((C - 30 * S + i * 2.2 * S, 312 * S - v * 26 * S))
        gd.line(pts, fill=c(GOOD), width=2 * S)
    gd.text((C - 70 * S, 384 * S), "S: 351,45", font=bf("SemiBold Condensed", 22), fill=c(pal["bad"]), anchor="mm")
    gd.text((C + 70 * S, 384 * S), "H: 394,28", font=bf("SemiBold Condensed", 22), fill=c(GOOD), anchor="mm")
    if not aod:
        gd.text((C - 40 * S, 414 * S), "♥ 76".replace("♥", "NBZ"), font=fs, fill=c(MAIN, 200), anchor="mm")
        gd.text((C + 40 * S, 414 * S), "PİL 46%", font=fs, fill=c(MAIN, 200), anchor="mm")

    img = base
    img.alpha_composite(ghost_l)
    bloom(img, glow_l, r1=3, r2=12 if not aod else 9, k=(1.1, 1.0))
    if not aod:   # VFD ızgara (ince metal ağ)
        mesh = Image.new("RGBA", (N, N), (0, 0, 0, 0)); md = ImageDraw.Draw(mesh)
        for k in range(0, N, 5 * S):
            md.line((k, 0, k, N), fill=(0, 0, 0, 55), width=1); md.line((0, k, N, k), fill=(0, 0, 0, 55), width=1)
        img.alpha_composite(mesh)
        gloss = Image.new("RGBA", (N, N), (0, 0, 0, 0)); ImageDraw.Draw(gloss).ellipse((-N * 0.25, -N * 0.6, N * 1.05, N * 0.38), fill=(255, 255, 255, 9))
        img.alpha_composite(gloss)
    m = Image.new("L", (N, N), 0); ImageDraw.Draw(m).ellipse((0, 0, N - 1, N - 1), fill=255)
    out = Image.new("RGBA", (N, N), (0, 0, 0, 0)); out.paste(img, (0, 0), m)
    return out


AQUA = {"main": (90, 255, 220), "acc": (255, 210, 120), "warn": (255, 190, 90), "good": (120, 255, 170), "bad": (255, 110, 120),
        "ring": [(255, 120, 110), (255, 210, 110), (90, 255, 210)], "bg": (4, 26, 24)}
AMBER = {"main": (255, 196, 92), "acc": (120, 255, 190), "warn": (120, 255, 200), "good": (150, 255, 140), "bad": (255, 100, 70),
         "ring": [(255, 90, 60), (255, 190, 80), (150, 255, 140)], "bg": (30, 16, 4)}

if __name__ == "__main__":
    vs = [("Camgöbeği · normal", face(AQUA)), ("Camgöbeği · AOD", face(AQUA, True)),
          ("Amber · normal", face(AMBER)), ("Amber · AOD", face(AMBER, True))]
    t = 400; gap = 30
    W = gap + 4 * (t + gap); H = t + 80
    cv = Image.new("RGB", (W, H), (22, 22, 24)); dd = ImageDraw.Draw(cv)
    lab = bf("SemiBold Condensed", 11)
    for i, (name, im) in enumerate(vs):
        x = gap + i * (t + gap)
        cv.paste(im.resize((t, t), Image.LANCZOS), (x, 20), im.resize((t, t), Image.LANCZOS))
        dd.text((x + t / 2, t + 50), name, font=lab, fill=(235, 235, 230), anchor="mm")
    cv.save(OUT / "vfd_kadran.png"); print("ok")
