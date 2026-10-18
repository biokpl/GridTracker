"""Özgün arka planlar — borsa, Selçuklu geometrisi, İstanbul, fiyat dalgaları, radar, kristal."""
import math, random
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter
import numpy as np
import render_time_styles as r
import render_time_styles3 as r3
from render_backgrounds import swap_bg, vignette

S, N = r.S, r.N
C = N / 2


def bg_heatmap():
    img = Image.new("RGB", (N, N), (12, 14, 17)); d = ImageDraw.Draw(img)
    random.seed(21)
    def split(x0, y0, x1, y1, depth):
        if depth == 0 or (x1 - x0) < 60 * S or (y1 - y0) < 60 * S:
            ch = random.gauss(0, 1.6)
            k = min(1, abs(ch) / 3)
            col = (int(14 + 70 * k), 18, 20) if ch < 0 else (14, int(20 + 60 * k), int(18 + 34 * k))
            d.rectangle((x0 + 2 * S, y0 + 2 * S, x1 - 2 * S, y1 - 2 * S), fill=col)
            return
        if (x1 - x0) > (y1 - y0):
            m = x0 + (x1 - x0) * random.uniform(0.3, 0.7); split(x0, y0, m, y1, depth - 1); split(m, y0, x1, y1, depth - 1)
        else:
            m = y0 + (y1 - y0) * random.uniform(0.3, 0.7); split(x0, y0, x1, m, depth - 1); split(x0, m, x1, y1, depth - 1)
    split(0, 0, N, N, 7)
    return vignette(img, 0.75)


def bg_selcuk():
    img = Image.new("RGB", (N, N), (14, 16, 20)); d = ImageDraw.Draw(img)
    s = 46 * S; GOLD = (78, 64, 38)
    for gy in range(-1, int(N / s) + 2):
        for gx in range(-1, int(N / s) + 2):
            cx, cy = gx * s, gy * s
            r0 = s * 0.42
            for rot in (0, 45):
                pts = [(cx + r0 * math.cos(math.radians(a + rot)), cy + r0 * math.sin(math.radians(a + rot))) for a in (45, 135, 225, 315)]
                d.polygon(pts, outline=GOLD, width=S)
            r1 = s * 0.16
            d.polygon([(cx + r1 * math.cos(math.radians(a)), cy + r1 * math.sin(math.radians(a))) for a in range(0, 360, 45)], outline=(60, 50, 32), width=S)
            for a in (0, 90, 180, 270):
                d.line((cx + r0 * 0.75 * math.cos(math.radians(a)), cy + r0 * 0.75 * math.sin(math.radians(a)),
                        cx + s * 0.5 * math.cos(math.radians(a)), cy + s * 0.5 * math.sin(math.radians(a))), fill=GOLD, width=S)
    return vignette(img, 0.7)


def bg_istanbul():
    y, x = np.mgrid[0:N, 0:N]
    t = y / N
    sky = np.stack([10 + 30 * t ** 2, 12 + 14 * t ** 2, 22 + 10 * t ** 2], -1)
    glow = np.clip(1 - np.sqrt((x - C) ** 2 + (y - N * 0.86) ** 2) / (N * 0.5), 0, 1) ** 2
    sky += glow[..., None] * np.array([70, 36, 14])
    img = Image.fromarray(sky.clip(0, 255).astype(np.uint8)); d = ImageDraw.Draw(img)
    random.seed(2)
    for i in range(140):       # yıldızlar
        sx, sy = random.uniform(0, N), random.uniform(0, N * 0.5); d.point((sx, sy), fill=(90, 96, 110))
    base = N * 0.80; SIL = (8, 9, 12)
    def mosque(cx, w, h):
        d.rectangle((cx - w / 2, base - h * 0.35, cx + w / 2, N), fill=SIL)
        d.pieslice((cx - w * 0.36, base - h * 0.35 - w * 0.36, cx + w * 0.36, base - h * 0.35 + w * 0.36), 180, 360, fill=SIL)
        d.line((cx, base - h * 0.35 - w * 0.36, cx, base - h * 0.35 - w * 0.46), fill=SIL, width=2 * S)
        for sx in (-0.62, 0.62):
            mx = cx + w * sx; d.rectangle((mx - 4 * S, base - h, mx + 4 * S, N), fill=SIL)
            d.polygon([(mx - 5 * S, base - h), (mx + 5 * S, base - h), (mx, base - h - 26 * S)], fill=SIL)
            d.rectangle((mx - 7 * S, base - h * 0.7, mx + 7 * S, base - h * 0.7 + 3 * S), fill=SIL)
        for sx in (-0.33, 0.33):
            ccx = cx + w * sx; rr = w * 0.15; d.pieslice((ccx - rr, base - h * 0.32 - rr, ccx + rr, base - h * 0.32 + rr), 180, 360, fill=SIL)
    mosque(C - 150 * S, 150 * S, 230 * S)
    mosque(C + 160 * S, 120 * S, 190 * S)
    d.rectangle((0, base + 20 * S, N, N), fill=SIL)
    tower = C + 20 * S; d.rectangle((tower - 10 * S, base - 120 * S, tower + 10 * S, N), fill=SIL)
    d.polygon([(tower - 13 * S, base - 120 * S), (tower + 13 * S, base - 120 * S), (tower, base - 160 * S)], fill=SIL)
    return vignette(img, 0.6)


def bg_waves():
    img = Image.new("RGBA", (N, N), (11, 13, 16, 255))
    for k, (col, amp, ph, yb) in enumerate((((60, 225, 170), 40, 0.0, 0.62), ((255, 150, 60), 30, 1.7, 0.70), ((120, 140, 255), 26, 3.1, 0.55), ((60, 225, 170), 22, 4.4, 0.78))):
        lay = Image.new("RGBA", (N, N), (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
        pts = []
        for xx in range(0, N + 1, 4 * S):
            u = xx / N
            yy = N * yb + amp * S * (math.sin(u * 7 + ph) + 0.5 * math.sin(u * 17 + ph * 2) + 0.25 * math.sin(u * 37 + ph))
            pts.append((xx, yy))
        d.polygon(pts + [(N, N), (0, N)], fill=col + (16,))
        d.line(pts, fill=col + (90,), width=2 * S)
        img.alpha_composite(lay.filter(ImageFilter.GaussianBlur(0.6 * S)))
    return vignette(img.convert("RGB"), 0.65)


def bg_radar():
    y, x = np.mgrid[0:N, 0:N]
    ang = (np.degrees(np.arctan2(y - C, x - C)) + 360 + 90) % 360
    sweep = np.clip(1 - ((300 - ang) % 360) / 70, 0, 1) ** 2
    a = np.zeros((N, N, 3)) + [10, 14, 16]
    a += sweep[..., None] * np.array([10, 60, 46])
    img = Image.fromarray(a.clip(0, 255).astype(np.uint8)); d = ImageDraw.Draw(img)
    for rr in range(40, 240, 40):
        d.ellipse((C - rr * S, C - rr * S, C + rr * S, C + rr * S), outline=(28, 52, 46), width=S)
    d.line((C, 0, C, N), fill=(24, 42, 38), width=S); d.line((0, C, N, C), fill=(24, 42, 38), width=S)
    random.seed(9)
    for _ in range(7):
        rr = random.uniform(60, 210) * S; aa = random.uniform(0, 360)
        px, py = C + rr * math.cos(math.radians(aa)), C + rr * math.sin(math.radians(aa))
        d.ellipse((px - 3 * S, py - 3 * S, px + 3 * S, py + 3 * S), fill=(60, 160, 120))
    return vignette(img, 0.6)


def bg_crystal():
    img = Image.new("RGB", (N, N)); d = ImageDraw.Draw(img)
    random.seed(13); g = 60 * S
    pts = {(i, j): (i * g + random.uniform(-0.35, 0.35) * g, j * g + random.uniform(-0.35, 0.35) * g)
           for i in range(-1, int(N / g) + 3) for j in range(-1, int(N / g) + 3)}
    for i in range(-1, int(N / g) + 2):
        for j in range(-1, int(N / g) + 2):
            a, b, c, e = pts[(i, j)], pts[(i + 1, j)], pts[(i, j + 1)], pts[(i + 1, j + 1)]
            for tri in ((a, b, c), (b, e, c)):
                cy = sum(p[1] for p in tri) / 3; cx = sum(p[0] for p in tri) / 3
                l = 16 + 18 * (1 - cy / N) + random.uniform(-5, 5) + 8 * math.cos((cx - C) / N * 3)
                d.polygon(tri, fill=(int(l), int(l + 3), int(l + 9)), outline=(int(l + 6), int(l + 9), int(l + 15)))
    return vignette(img, 0.7)


if __name__ == "__main__":
    face = r3.p1()
    opts = [("1 · BIST ısı haritası", bg_heatmap()), ("2 · Selçuklu yıldızı", bg_selcuk()),
            ("3 · İstanbul silueti", bg_istanbul()), ("4 · Fiyat dalgaları", bg_waves()),
            ("5 · Radar taraması", bg_radar()), ("6 · Kristal yüzeyler", bg_crystal())]
    t = 400; gap = 30; cols = 3
    W = gap + cols * (t + gap); H = 2 * (t + 70) + gap
    cv = Image.new("RGB", (W, H), (22, 22, 24)); dd = ImageDraw.Draw(cv)
    lab = r3.bf("SemiBold Condensed", 11)
    msk = Image.new("L", (t, t), 0); ImageDraw.Draw(msk).ellipse((0, 0, t - 1, t - 1), fill=255)
    for i, (name, bg) in enumerate(opts):
        im = swap_bg(face, bg)
        x = gap + (i % cols) * (t + gap); y = 20 + (i // cols) * (t + 70)
        cv.paste(im.resize((t, t), Image.LANCZOS), (x, y), msk)
        dd.text((x + t / 2, y + t + 30), name, font=lab, fill=(235, 235, 230), anchor="mm")
    cv.save(Path(__file__).parent / "arka_planlar2.png"); print("ok")
