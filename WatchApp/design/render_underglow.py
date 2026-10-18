"""TUPRS paneline alt ışık süzmesi + yansıma denemeleri (buz mavisi VFD saatli kadran üzerinde)."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageChops
import numpy as np
import render_time_styles2 as r2
import render_vfd_time as vt

S, N = vt.S, vt.N
OUT = Path(__file__).parent
PX0, PY0, PX1, PY1 = 78, 275, 402, 378          # panel kutusu (480 ölçeğinde, ekran görüntüsünden ölçüldü)


def panel_mask(pad=0):
    m = Image.new("L", (N, N), 0)
    ImageDraw.Draw(m).rounded_rectangle(((PX0 - pad) * S, (PY0 - pad) * S, (PX1 + pad) * S, (PY1 + pad) * S), radius=22 * S, fill=255)
    return m


def underglow(img, col, strength=1.0):
    glow = Image.new("RGBA", (N, N), (0, 0, 0, 0)); gd = ImageDraw.Draw(glow)
    gd.ellipse(((PX0 + 30) * S, (PY1 - 18) * S, (PX1 - 30) * S, (PY1 + 34) * S), fill=col + (int(150 * strength),))
    glow = glow.filter(ImageFilter.GaussianBlur(18 * S))
    inside = panel_mask(); a = np.array(glow); a[..., 3] = (a[..., 3] * (1 - np.array(inside) / 255 * 0.85)).astype(np.uint8)
    img.alpha_composite(Image.fromarray(a))
    strip = Image.new("RGBA", (N, N), (0, 0, 0, 0)); sd = ImageDraw.Draw(strip)
    sd.line(((PX0 + 26) * S, PY1 * S, (PX1 - 26) * S, PY1 * S), fill=col + (255,), width=3 * S)
    img.alpha_composite(strip.filter(ImageFilter.GaussianBlur(5 * S)))
    img.alpha_composite(strip.filter(ImageFilter.GaussianBlur(1.5 * S)))
    # zemindeki yansıma: panelin altına soluk, aşağı doğru sönen ışık şeridi
    ref = Image.new("RGBA", (N, N), (0, 0, 0, 0)); rd = ImageDraw.Draw(ref)
    for k in range(26):
        a_ = int(55 * strength * (1 - k / 26) ** 2)
        rd.line(((PX0 + 50 + k * 2) * S, (PY1 + 4 + k) * S, (PX1 - 50 - k * 2) * S, (PY1 + 4 + k) * S), fill=col + (a_,), width=S)
    img.alpha_composite(ref.filter(ImageFilter.GaussianBlur(2 * S)))
    return img


def upglow(img, col, strength=0.35, below=0.22):
    """Işık panelin alt kenarında: içeri YUKARI süzülür, ortada güçlü kenarlarda soluk;
    altına da hafif bir taşma."""
    inside = np.array(panel_mask()).astype(np.float32) / 255
    yy = np.arange(N)[:, None].astype(np.float32); xx = np.arange(N)[None, :].astype(np.float32)
    cx = (PX0 + PX1) / 2 * S; half = (PX1 - PX0) / 2 * S
    hfall = np.exp(-((xx - cx) / (half * 0.55)) ** 2)                # yatay: kenarlarda soluk
    h = (PY1 - PY0) * S
    t = np.clip(((PY1 * S) - yy) / (h * 0.6), 0, 1)
    up = (1 - t) ** 2.2 * inside * hfall
    tb = np.clip((yy - PY1 * S) / (22 * S), 0, 1)
    down = np.where(yy > PY1 * S, (1 - tb) ** 2, 0) * hfall * (1 - inside)
    a = (up * 150 * strength + down * 150 * below).clip(0, 255)
    lay = np.zeros((N, N, 4), np.uint8); lay[..., :3] = col; lay[..., 3] = a.astype(np.uint8)
    img.alpha_composite(Image.fromarray(lay).filter(ImageFilter.GaussianBlur(4 * S)))
    # alt kenar ışık çizgisi — ortadan kenarlara sönen
    strip = np.zeros((N, N, 4), np.uint8); y0 = int((PY1 - 1) * S)
    sa = (hfall[0] * 230 * strength).clip(0, 255).astype(np.uint8)
    for dy in range(-S, S + 1):
        strip[y0 + dy, :, :3] = col; strip[y0 + dy, :, 3] = sa
    strip[:, : int((PX0 + 24) * S), 3] = 0; strip[:, int((PX1 - 24) * S):, 3] = 0
    st = Image.fromarray(strip)
    img.alpha_composite(st.filter(ImageFilter.GaussianBlur(3 * S)))
    img.alpha_composite(st.filter(ImageFilter.GaussianBlur(1 * S)))
    return img


def glass(img):
    hl = Image.new("RGBA", (N, N), (0, 0, 0, 0)); hd = ImageDraw.Draw(hl)
    hd.rounded_rectangle(((PX0 + 3) * S, (PY0 + 3) * S, (PX1 - 3) * S, (PY0 + 30) * S), radius=19 * S, fill=(255, 255, 255, 22))
    hd.line(((PX0 + 20) * S, (PY0 + 2) * S, (PX1 - 20) * S, (PY0 + 2) * S), fill=(255, 255, 255, 110), width=S)
    img.alpha_composite(hl)
    return img


def base():
    return vt.vfd_time(r2.base_no_sec(), vt.ICE)


if __name__ == "__main__":
    v1 = upglow(base(), (150, 220, 255))
    v2 = upglow(base(), (60, 225, 170))
    v2r = upglow(base(), (255, 80, 90))
    v3 = glass(upglow(base(), (235, 240, 255), 0.28))
    vs = [("1 · Buz mavisi (yukarı)", v1), ("2 · K/Z ışığı kârda (yukarı)", v2), ("2 · K/Z ışığı zararda (yukarı)", v2r), ("3 · Cam yansıması (yukarı)", v3)]
    t = 400; gap = 30
    W = gap + len(vs) * (t + gap); H = t + 80
    cv = Image.new("RGB", (W, H), (22, 22, 24)); dd = ImageDraw.Draw(cv)
    lab = r2.bf("SemiBold Condensed", 11)
    msk = Image.new("L", (t, t), 0); ImageDraw.Draw(msk).ellipse((0, 0, t - 1, t - 1), fill=255)
    for i, (name, im) in enumerate(vs):
        x = gap + i * (t + gap)
        cv.paste(im.resize((t, t), Image.LANCZOS).convert("RGB"), (x, 20), msk)
        dd.text((x + t / 2, t + 50), name, font=lab, fill=(235, 235, 230), anchor="mm")
    cv.save(OUT / "panel_isik.png"); print("ok")
