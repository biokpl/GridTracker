"""Halka ucu işaretçisi alternatifleri (A kadranı) — önizleme."""
import math
from PIL import Image, ImageDraw, ImageFilter, ImageFont

S = 4                        # süper örnekleme
W = 450
C = W / 2
K = 450 / 480 * 1.0          # kadrandaki K ile aynı ölçek yaklaşık
R, TH = 213 * 0.9375, 18 * 0.9375
N = 42
GAP = 4
P = 0.62                     # örnek ilerleme
COLS = [(255, 85, 80), (255, 190, 60), (60, 225, 170)]


def grad(t):
    if t < .5:
        a, b, u = COLS[0], COLS[1], t / .5
    else:
        a, b, u = COLS[1], COLS[2], (t - .5) / .5
    return tuple(int(a[i] + (b[i] - a[i]) * u) for i in range(3))


def ang(t):  # 0..1 → derece (PIL: 0 = sağ, saat yönü); halka 225°'den (saat 7:30) başlar, 270° döner
    return 135 + 270 * t


def base():
    im = Image.new("RGBA", (W * S, W * S), (14, 16, 19, 255))
    d = ImageDraw.Draw(im)
    box = [(C - R) * S, (C - R) * S, (C + R) * S, (C + R) * S]
    gd = math.degrees(GAP / R)
    for i in range(N):
        t0, t1 = i / N, (i + 1) / N
        a0, a1 = ang(t0), ang(t1) - gd
        lit = t1 <= P + 1e-9 or (t0 < P)
        col = grad((t0 + t1) / 2) if lit else (38, 40, 44)
        if t0 < P < t1:
            d.arc(box, a0, ang(P), fill=col + (255,), width=int(TH * S))
            d.arc(box, ang(P), a1, fill=(38, 40, 44, 255), width=int(TH * S))
        else:
            d.arc(box, a0, a1, fill=col + (255,), width=int(TH * S))
    return im


def carc(d, a0, a1, col, w):
    """Yarıçap R'ye ORTALI yay (PIL genişliği içe doğru büyütür)."""
    rr = R + w / 2
    d.arc([(C - rr) * S, (C - rr) * S, (C + rr) * S, (C + rr) * S], a0, a1, fill=col, width=int(w * S))


def pt(t, r):
    a = math.radians(ang(t))
    return (C + r * math.cos(a)) * S, (C + r * math.sin(a)) * S


def glow(im, draw_fn, rad):
    g = Image.new("RGBA", im.size, (0, 0, 0, 0)); draw_fn(ImageDraw.Draw(g))
    im.alpha_composite(g.filter(ImageFilter.GaussianBlur(rad * S)))


def opt_current(im):
    d = ImageDraw.Draw(im)
    x, y = pt(P, R)
    d.ellipse((x - 11 * S, y - 11 * S, x + 11 * S, y + 11 * S), fill=(255, 255, 255, 255))
    # boşluk çizgisi noktanın üstünden geçiyor (mevcut sorun)
    i = int(P * N) + 1
    a = math.radians(ang(i / N) - math.degrees(GAP / R) / 2)
    d.line((C * S + (R - 14) * S * math.cos(a), C * S + (R - 14) * S * math.sin(a),
            C * S + (R + 14) * S * math.cos(a), C * S + (R + 14) * S * math.sin(a)), fill=(14, 16, 19, 255), width=GAP * S)


def opt_segment(im):
    """A: o anki segment beyaza yakın parlar (segment şeklinde, boşluklara uyar)."""
    i = int(P * N)
    box = [(C - R) * S, (C - R) * S, (C + R) * S, (C + R) * S]
    a0, a1 = ang(i / N), ang((i + 1) / N) - math.degrees(GAP / R)
    col = grad(P)
    glow(im, lambda d: carc(d, a0 - 2, a1 + 2, col + (210,), TH * 1.9), 5)
    d = ImageDraw.Draw(im)
    carc(d, a0, a1, tuple(int(c + (255 - c) * .7) for c in col) + (255,), TH)


def opt_needle(im):
    """B: ince ibre — halkanın içinden dışına geçen beyaz çizgi."""
    x0, y0 = pt(P, R - TH / 2 - 7); x1, y1 = pt(P, R + TH / 2 + 5)
    glow(im, lambda d: d.line((x0, y0, x1, y1), fill=(255, 255, 255, 200), width=6 * S), 3)
    ImageDraw.Draw(im).line((x0, y0, x1, y1), fill=(255, 255, 255, 255), width=int(2.5 * S))


def opt_triangle(im):
    """C: halkanın iç kenarında, uca bakan küçük üçgen."""
    tx, ty = pt(P, R - TH / 2 - 3); bx, by = pt(P, R - TH / 2 - 17)
    L = math.hypot(tx - bx, ty - by); ux, uy = (tx - bx) / L, (ty - by) / L
    px, py = -uy * 4.5 * S, ux * 4.5 * S
    tri = [(tx, ty), (bx + px, by + py), (bx - px, by - py)]
    col = grad(P)
    glow(im, lambda d: d.polygon(tri, fill=col + (220,)), 3)
    ImageDraw.Draw(im).polygon(tri, fill=(255, 255, 255, 255))


def opt_halo(im):
    """D: ucun kendisi parlar — yumuşak renkli hale, sert şekil yok."""
    x, y = pt(P, R); col = grad(P)
    glow(im, lambda d: d.ellipse((x - 18 * S, y - 18 * S, x + 18 * S, y + 18 * S), fill=col + (200,)), 7)
    i = int(P * N); box = [(C - R) * S, (C - R) * S, (C + R) * S, (C + R) * S]
    carc(ImageDraw.Draw(im), ang(i / N), ang(P), tuple(int(c + (255 - c) * .55) for c in col) + (255,), TH)


OPTS = [("Şu an (sorunlu)", opt_current), ("A · Parlayan segment", opt_segment),
        ("B · İnce ibre", opt_needle), ("C · Üçgen işaret", opt_triangle), ("D · Işıklı uç", opt_halo)]

if __name__ == "__main__":
    font = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 22)
    x, y = pt(P, R)
    cx, cy = x / S, y / S
    crop = (int(cx - 75), int(cy - 45), int(cx + 75), int(cy + 105))
    tiles = []
    for name, fn in OPTS:
        im = base(); fn(im)
        im = im.resize((W, W), Image.LANCZOS).crop(crop).resize((280, 280), Image.LANCZOS)
        t = Image.new("RGB", (280, 318), (8, 9, 11)); t.paste(im, (0, 38))
        ImageDraw.Draw(t).text((140, 19), name, font=font, fill=(230, 232, 236), anchor="mm")
        tiles.append(t)
    out = Image.new("RGB", (280 * 5 + 40, 318), (8, 9, 11))
    for i, t in enumerate(tiles): out.paste(t, (i * 290, 0))
    out.save("halka_isaretci.png"); print("ok")
