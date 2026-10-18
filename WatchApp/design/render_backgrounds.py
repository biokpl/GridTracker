"""Arka plan seçenekleri — P1 saatli gerçek kadran üzerinde (eski zemin piksel bazında değiştirilir)."""
import math, random
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageChops
import numpy as np
import render_time_styles as r
import render_time_styles3 as r3

S, N = r.S, r.N
C = N / 2


def vignette(img, strength=0.75):
    y, x = np.mgrid[0:N, 0:N]; d = np.sqrt((x - C) ** 2 + (y - C) ** 2) / C
    v = np.clip(1 - strength * d ** 2.2, 0.15, 1)
    a = np.array(img).astype(np.float32); a[..., :3] *= v[..., None]
    return Image.fromarray(a.clip(0, 255).astype(np.uint8))


def bg_carbon():
    t = 14 * S; tile = Image.new("RGB", (2 * t, 2 * t))
    td = ImageDraw.Draw(tile)
    for i in range(2):
        for j in range(2):
            x0, y0 = i * t, j * t
            for k in range(t):
                c = int(18 + 22 * (k / t)) if (i + j) % 2 == 0 else int(40 - 22 * (k / t))
                if (i + j) % 2 == 0: td.line((x0 + k, y0, x0 + k, y0 + t), fill=(c, c + 2, c + 5))
                else: td.line((x0, y0 + k, x0 + t, y0 + k), fill=(c, c + 2, c + 5))
    img = Image.new("RGB", (N, N))
    for y in range(0, N, 2 * t):
        for x in range(0, N, 2 * t): img.paste(tile, (x, y))
    img = img.rotate(45, resample=Image.BICUBIC, expand=False, fillcolor=(20, 22, 26))
    return vignette(img, 0.7)


def bg_titanium():
    rng = np.random.default_rng(3)
    y, x = np.mgrid[0:N, 0:N]; ang = np.arctan2(y - C, x - C)
    streak = np.sin(ang * 900 + rng.normal(0, 1, (N, N)) * 0.6) * 6 + rng.normal(0, 3, (N, N))
    base = 44 + streak
    grad = 1 - 0.35 * ((y - 0) / N)
    a = np.stack([base * grad * 0.95, base * grad, base * grad * 1.06], -1)
    return vignette(Image.fromarray(a.clip(0, 255).astype(np.uint8)), 0.8)


def bg_topo():
    y, x = np.mgrid[0:N, 0:N] / N
    f = (np.sin(x * 7 + np.sin(y * 3) * 1.5) + np.sin(y * 6 + np.cos(x * 4) * 1.2) + 0.6 * np.sin((x + y) * 11)) * 0.5
    lines = np.abs(((f * 9) % 1) - 0.5) < 0.035
    a = np.zeros((N, N, 3)) + [16, 19, 22]
    a[lines] = [52, 66, 70]
    img = Image.fromarray(a.astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.6 * S))
    return vignette(img, 0.75)


def bg_hex():
    img = Image.new("RGB", (N, N), (16, 18, 22)); d = ImageDraw.Draw(img)
    s = 20 * S; h = math.sqrt(3) * s
    for row in range(-1, int(N / h) + 2):
        for col in range(-1, int(N / (1.5 * s)) + 2):
            cx = col * 1.5 * s; cy = row * h + (h / 2 if col % 2 else 0)
            pts = [(cx + s * math.cos(math.radians(a)), cy + s * math.sin(math.radians(a))) for a in range(0, 360, 60)]
            d.polygon(pts, outline=(36, 42, 48), width=S)
    return vignette(img, 0.8)


def bg_chart():
    img = Image.new("RGB", (N, N), (14, 17, 20)); d = ImageDraw.Draw(img)
    for k in range(0, N, 40 * S): d.line((0, k, N, k), fill=(24, 28, 32), width=S); d.line((k, 0, k, N), fill=(24, 28, 32), width=S)
    random.seed(4); v = N * 0.62; w = 14 * S
    for i in range(int(N / w) + 1):
        o = v; c = v + random.uniform(-26, 24) * S; hi = min(o, c) - random.uniform(4, 18) * S; lo = max(o, c) + random.uniform(4, 18) * S
        col = (24, 70, 58) if c < o else (78, 34, 34)
        xc = i * w + w / 2; d.line((xc, hi, xc, lo), fill=col, width=S)
        d.rectangle((xc - w * 0.3, min(o, c), xc + w * 0.3, max(o, c)), fill=col); v = c
    return vignette(img, 0.7)


def bg_aurora():
    y, x = np.mgrid[0:N, 0:N]
    a = np.zeros((N, N, 3)) + [10, 12, 15]
    for (cx, cy, rad, col) in ((0.18, 0.95, 0.55, (120, 50, 30)), (0.85, 0.9, 0.5, (20, 110, 85)), (0.5, -0.1, 0.6, (40, 46, 60))):
        dd = np.sqrt((x - cx * N) ** 2 + (y - cy * N) ** 2) / (rad * N)
        g = np.clip(1 - dd, 0, 1) ** 2
        a += g[..., None] * np.array(col)
    return vignette(Image.fromarray(a.clip(0, 255).astype(np.uint8)), 0.5)


def swap_bg(face_rgba, new_bg):
    old = Image.open(r.BG).convert("RGB").resize((N, N), Image.LANCZOS)
    fa = np.array(face_rgba.convert("RGB")).astype(np.int16); oa = np.array(old).astype(np.int16)
    m = (np.abs(fa - oa).max(-1) < 7).astype(np.uint8) * 255
    mask = Image.fromarray(m).filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.8 * S))
    out = face_rgba.convert("RGB").copy(); out.paste(new_bg.convert("RGB"), (0, 0), mask)
    return out


if __name__ == "__main__":
    face = r3.p1()
    opts = [("1 · Karbon fiber örgü", bg_carbon()), ("2 · Fırçalanmış titanyum", bg_titanium()),
            ("3 · Topografik harita", bg_topo()), ("4 · Altıgen petek", bg_hex()),
            ("5 · Silik borsa grafiği", bg_chart()), ("6 · Halka renginde ışık", bg_aurora())]
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
    cv.save(Path(__file__).parent / "arka_planlar.png"); print("ok")
