"""Saat (HH:MM) için görsel stil önerileri — gerçek kadran ekran görüntüsü üzerinde."""
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops

D = Path(__file__).parent
SHOT = D / "preview_A_saat.png"                         # 450px gerçek ekran
BG = D.parent / "face_ultra/src/main/res/drawable/bg_ultra.png"
S = 2; N = 480 * S
TXT = "19:03"


def font(sz):
    f = ImageFont.truetype("C:/Windows/Fonts/bahnschrift.ttf", int(sz * S)); f.set_variation_by_name("Bold Condensed"); return f


def base():
    face = Image.open(SHOT).convert("RGBA").resize((N, N), Image.LANCZOS)
    bg = Image.open(BG).convert("RGBA").resize((N, N), Image.LANCZOS)
    box = (int(112 * S), int(104 * S), int(334 * S), int(212 * S))   # eski saati sil
    face.paste(bg.crop(box), box[:2])
    return face


CX, CY, SZ = 220 * S, 158 * S, 118


def mask_text(sz=SZ, dx=0, dy=0, stroke=0):
    m = Image.new("L", (N, N), 0)
    ImageDraw.Draw(m).text((CX + dx, CY + dy), TXT, font=font(sz), fill=255, anchor="mm", stroke_width=stroke)
    return m


def vgrad(c0, c1, y0=CY - 58 * S, y1=CY + 58 * S, stops=None):
    g = Image.new("RGBA", (N, N)); px = ImageDraw.Draw(g)
    for y in range(N):
        t = min(1, max(0, (y - y0) / (y1 - y0)))
        if stops:
            for (ta, ca), (tb, cb) in zip(stops, stops[1:]):
                if ta <= t <= tb:
                    u = (t - ta) / (tb - ta) if tb > ta else 0
                    col = tuple(int(ca[i] + (cb[i] - ca[i]) * u) for i in range(3)); break
        else:
            col = tuple(int(c0[i] + (c1[i] - c0[i]) * t) for i in range(3))
        px.line((0, y, N, y), fill=col + (255,))
    return g


def fill(img, m, src):
    layer = Image.new("RGBA", (N, N), (0, 0, 0, 0)); layer.paste(src, (0, 0), m); img.alpha_composite(layer)


def shadow(img, m, off=(6, 9), blur=8, a=200):
    sh = Image.new("RGBA", (N, N), (0, 0, 0, 0)); sh.paste(Image.new("RGBA", (N, N), (0, 0, 0, a)), (0, 0), m)
    sh = sh.filter(ImageFilter.GaussianBlur(blur * S)); img.alpha_composite(sh, (off[0] * S, off[1] * S))


def glow(img, m, col, r=10, k=2):
    g = Image.new("RGBA", (N, N), (0, 0, 0, 0)); g.paste(Image.new("RGBA", (N, N), col + (255,)), (0, 0), m)
    g = g.filter(ImageFilter.GaussianBlur(r * S))
    for _ in range(k): img.alpha_composite(g)


# 1 · Metalik krom
def v_chrome():
    img = base(); m = mask_text()
    shadow(img, m)
    fill(img, m, vgrad(None, None, stops=[(0, (255, 255, 255)), (0.45, (200, 205, 212)), (0.5, (120, 126, 134)), (0.62, (215, 220, 226)), (1, (150, 155, 162))]))
    hl = Image.new("L", (N, N), 0); ImageDraw.Draw(hl).rectangle((0, CY - 58 * S, N, CY - 30 * S), fill=90)
    fill(img, ImageChops.multiply(m, hl), Image.new("RGBA", (N, N), (255, 255, 255, 255)))
    edge = ImageChops.subtract(mask_text(stroke=2 * S), m)
    fill(img, edge, Image.new("RGBA", (N, N), (70, 74, 80, 255)))
    return img


# 2 · Halkayla uyumlu gradyan + parlama
def v_grad():
    img = base(); m = mask_text()
    glow(img, m, (60, 225, 170), r=14, k=1)
    fill(img, m, vgrad(None, None, stops=[(0, (255, 255, 255)), (0.55, (220, 255, 240)), (1, (60, 225, 170))]))
    return img


# 3 · Neon dış hat
def v_neon():
    img = base()
    outer = mask_text(stroke=3 * S); inner = mask_text()
    ring = ImageChops.subtract(outer, ImageChops.subtract(inner, mask_text(sz=SZ, stroke=0).filter(ImageFilter.MinFilter(9))))
    line = ImageChops.subtract(outer, inner.filter(ImageFilter.MinFilter(2 * S + 1)))
    glow(img, line, (0, 230, 255), r=9, k=3)
    fill(img, line, Image.new("RGBA", (N, N), (220, 252, 255, 255)))
    fill(img, inner.filter(ImageFilter.MinFilter(2 * S + 1)), Image.new("RGBA", (N, N), (0, 40, 60, 140)))
    return img


# 4 · 3D blok + sönük LED zemin
def v_3d():
    img = base()
    ghost = Image.new("L", (N, N), 0); ImageDraw.Draw(ghost).text((CX, CY), "88:88", font=font(SZ), fill=255, anchor="mm")
    fill(img, ghost, Image.new("RGBA", (N, N), (255, 255, 255, 18)))
    m = mask_text()
    for i in range(10, 0, -1):          # katmanlı derinlik
        layer = Image.new("RGBA", (N, N), (0, 0, 0, 0))
        layer.paste(Image.new("RGBA", (N, N), (int(40 + 6 * (10 - i)), int(110 + 8 * (10 - i)), int(90 + 7 * (10 - i)), 255)), (0, 0), m)
        img.alpha_composite(layer, (int(i * 0.9 * S), int(i * 1.1 * S)))
    fill(img, m, vgrad(None, None, stops=[(0, (255, 255, 255)), (1, (225, 230, 228))]))
    return img


if __name__ == "__main__":
    vs = [("1 · Metalik krom", v_chrome()), ("2 · Gradyan + parlama", v_grad()),
          ("3 · Neon dış hat", v_neon()), ("4 · 3D blok + sönük LED", v_3d())]
    t = 360; gap = 30
    W = gap + len(vs) * (t + gap); H = t + 80
    cv = Image.new("RGB", (W, H), (22, 22, 24)); d = ImageDraw.Draw(cv)
    lab = ImageFont.truetype("C:/Windows/Fonts/bahnschrift.ttf", 22); lab.set_variation_by_name("SemiBold Condensed")
    msk = Image.new("L", (t, t), 0); ImageDraw.Draw(msk).ellipse((0, 0, t - 1, t - 1), fill=255)
    for i, (name, im) in enumerate(vs):
        x = gap + i * (t + gap)
        cv.paste(im.resize((t, t), Image.LANCZOS).convert("RGB"), (x, 20), msk)
        d.text((x + t / 2, t + 50), name, font=lab, fill=(235, 235, 230), anchor="mm")
    cv.save(D / "saat_stilleri.png"); print("ok")
