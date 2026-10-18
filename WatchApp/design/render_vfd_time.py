"""Mevcut A kadranı korunur; yalnız SAAT bölümü VFD (floresan) olur. Normal + AOD."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter
import numpy as np
import render_time_styles as r
import render_time_styles2 as r2
import render_time_styles3 as r3
import render_vfd as v

S, N = r.S, r.N
OUT = Path(__file__).parent


def vfd_time(img, col, ghost_a=26, window=True, mesh=True, sec=True, dim=1.0):
    w, h, t, gap = 42 * S, 86 * S, 10 * S, 8 * S
    tw = v.text_w("19:03", w, t, gap)
    x0 = 225 * S - tw / 2 - 12 * S; y0 = 114 * S
    if window:
        r3.recessed_window(img, (int(x0 / S) - 14, 103, int((x0 + tw) / S) + 14, 211))
    glow_l = Image.new("RGBA", (N, N), (0, 0, 0, 0)); gd = ImageDraw.Draw(glow_l)
    ghost_l = Image.new("RGBA", (N, N), (0, 0, 0, 0)); hd = ImageDraw.Draw(ghost_l)
    c = tuple(int(x * dim) for x in col) + (255,)
    GH = tuple(int(x * 0.16) for x in col) + (ghost_a * 6 if ghost_a else 0,)
    if ghost_a: v.draw_7seg(hd, hd, "88:88", x0, y0, w, h, t, gap, GH, GH)
    v.draw_7seg(gd, hd if ghost_a else ImageDraw.Draw(Image.new("RGBA", (1, 1))), "19:03", x0, y0, w, h, t, gap, c, GH)
    img.alpha_composite(ghost_l)
    v.bloom(img, glow_l, r1=3, r2=11, k=(1.1, 0.95))
    if mesh:
        mm = Image.new("RGBA", (N, N), (0, 0, 0, 0)); md = ImageDraw.Draw(mm)
        X0, X1 = int(x0 - 12 * S), int(x0 + tw + 12 * S)
        for k in range(X0, X1, 4 * S): md.line((k, 104 * S, k, 210 * S), fill=(0, 0, 0, 60), width=1)
        for k in range(104 * S, 210 * S, 4 * S): md.line((X0, k, X1, k), fill=(0, 0, 0, 60), width=1)
        img.alpha_composite(mm)
    if sec:
        sx = int((x0 + tw) / S) + 22
        r3.recessed_window(img, (sx, 126, sx + 40, 162), rad=8)
        sl = Image.new("RGBA", (N, N), (0, 0, 0, 0)); sd = ImageDraw.Draw(sl)
        sh_l = Image.new("RGBA", (N, N), (0, 0, 0, 0)); shd = ImageDraw.Draw(sh_l)
        v.draw_7seg(shd, shd, "88", (sx + 7) * S, 132 * S, 11 * S, 24 * S, 3 * S, 3 * S, GH, GH)
        v.draw_7seg(sd, shd, "53", (sx + 7) * S, 132 * S, 11 * S, 24 * S, 3 * S, 3 * S, c, GH)
        img.alpha_composite(sh_l); v.bloom(img, sl, r1=2, r2=6)
        ImageDraw.Draw(img).text(((sx + 20) * S, 172 * S), "SN", font=r2.bf("SemiBold Condensed", 11), fill=(110, 116, 122, 255), anchor="mm")
    return img


def aod(face_rgba, col):
    """Yaklaşık AOD: zemin siyah, diğer öğeler soluk, saat parlak floresan."""
    old = Image.open(r.BG).convert("RGB").resize((N, N), Image.LANCZOS)
    fa = np.array(face_rgba.convert("RGB")).astype(np.int16); oa = np.array(old).astype(np.int16)
    bgmask = (np.abs(fa - oa).max(-1) < 7)
    a = fa.astype(np.float32) * 0.42; a[bgmask] = 0
    img = Image.fromarray(a.clip(0, 255).astype(np.uint8)).convert("RGBA")
    vfd_time(img, col, ghost_a=0, window=False, mesh=False, sec=False, dim=1.0)
    m = Image.new("L", (N, N), 0); ImageDraw.Draw(m).ellipse((0, 0, N - 1, N - 1), fill=255)
    out = Image.new("RGBA", (N, N), (0, 0, 0, 255)); out.paste(img, (0, 0), m)
    return out


AQUA = (90, 255, 215)
ICE = (170, 235, 255)

if __name__ == "__main__":
    n1 = vfd_time(r2.base_no_sec(), AQUA)
    n2 = vfd_time(r2.base_no_sec(), ICE)
    vs = [("Buz mavisi floresan · normal", n2), ("Buz mavisi floresan · AOD", aod(r2.base_no_sec(), ICE))]
    t = 400; gap = 30
    W = gap + len(vs) * (t + gap); H = t + 80
    cv = Image.new("RGB", (W, H), (22, 22, 24)); dd = ImageDraw.Draw(cv)
    lab = r2.bf("SemiBold Condensed", 11)
    msk = Image.new("L", (t, t), 0); ImageDraw.Draw(msk).ellipse((0, 0, t - 1, t - 1), fill=255)
    for i, (name, im) in enumerate(vs):
        x = gap + i * (t + gap)
        cv.paste(im.resize((t, t), Image.LANCZOS).convert("RGB"), (x, 20), msk)
        dd.text((x + t / 2, t + 50), name, font=lab, fill=(235, 235, 230), anchor="mm")
    cv.save(OUT / "vfd_saat.png"); print("ok")
