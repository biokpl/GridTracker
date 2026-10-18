"""Premium saat işçiliği: gömme pencere, katmanlı gölge, pah, sönük segment, vurgu iki nokta."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops
import render_time_styles as r
import render_time_styles2 as r2

S, N = r.S, r.N
TEAL = (60, 225, 170)
bf = r2.bf


def L(): return Image.new("L", (N, N), 0)
def solid(col): return Image.new("RGBA", (N, N), col)
def put(img, mask, col, blur=0, off=(0, 0)):
    m = mask.filter(ImageFilter.GaussianBlur(blur * S)) if blur else mask
    lay = Image.new("RGBA", (N, N), (0, 0, 0, 0)); lay.paste(solid(col), (0, 0), m)
    img.alpha_composite(lay, (int(off[0] * S), int(off[1] * S)))


def digits_mask(font, cy=158, gap=8, colon_w=14):
    """HH ve MM maskesi + iki nokta konumu."""
    m = L(); d = ImageDraw.Draw(m)
    wh = d.textlength("19", font=font); wm = d.textlength("03", font=font)
    total = wh + wm + 2 * gap * S + colon_w * S
    x0 = 225 * S - total / 2; y = cy * S
    d.text((x0, y), "19", font=font, fill=255, anchor="lm")
    d.text((x0 + wh + 2 * gap * S + colon_w * S, y), "03", font=font, fill=255, anchor="lm")
    return m, x0, total, x0 + wh + gap * S + colon_w * S / 2, y


def ghost_mask(font, x0, y):
    m = L(); ImageDraw.Draw(m).text((x0, y), "88", font=font, fill=255, anchor="lm")
    d = ImageDraw.Draw(m); wh = d.textlength("19", font=font)
    d.text((x0 + wh + 2 * 8 * S + 14 * S, y), "88", font=font, fill=255, anchor="lm")
    return m


def premium_digits(img, m, top=(255, 255, 255), bot=(196, 202, 206)):
    """Katmanlı gölge + dikey gradyan gövde + üst ışık + alt pah."""
    put(img, m, (0, 0, 0, 120), blur=14, off=(0, 10))          # uzak yumuşak gölge
    put(img, m, (0, 0, 0, 200), blur=3, off=(0, 3))            # yakın keskin gölge
    body = r.vgrad(None, None, stops=[(0, top), (1, bot)])
    lay = Image.new("RGBA", (N, N), (0, 0, 0, 0)); lay.paste(body, (0, 0), m); img.alpha_composite(lay)
    hi = ImageChops.subtract(m, ImageChops.offset(m, 0, 2 * S))   # üst kenar ışığı
    put(img, hi, (255, 255, 255, 230))
    lo = ImageChops.subtract(m, ImageChops.offset(m, 0, -2 * S))  # alt kenar pahı
    put(img, lo, (120, 126, 132, 255))


def colon(img, cx, y, col=TEAL, glow=True):
    m = L(); d = ImageDraw.Draw(m)
    for dy in (-19, 19):
        d.rounded_rectangle((cx - 6 * S, y + dy * S - 6 * S, cx + 6 * S, y + dy * S + 6 * S), radius=3 * S, fill=255)
    if glow: put(img, m, col + (160,), blur=6)
    put(img, m, (0, 0, 0, 180), blur=2, off=(0, 2))
    put(img, m, col + (255,))


def recessed_window(img, box, rad=22):
    """Kadrana gömülü pencere: koyu iç, üstte iç gölge, altta ışık çizgisi."""
    x0, y0, x1, y1 = [v * S for v in box]
    m = L(); ImageDraw.Draw(m).rounded_rectangle((x0, y0, x1, y1), radius=rad * S, fill=255)
    put(img, m, (6, 8, 10, 235))
    inner = ImageChops.subtract(m, ImageChops.offset(m, 0, 7 * S)).filter(ImageFilter.GaussianBlur(5 * S))
    put(img, inner, (0, 0, 0, 255))
    edge = L(); ImageDraw.Draw(edge).rounded_rectangle((x0, y0, x1, y1), radius=rad * S, outline=255, width=2 * S)
    bottom = ImageChops.multiply(edge, ImageChops.subtract(m, ImageChops.offset(m, 0, -int((y1 - y0) * 0.5))))
    put(img, edge, (40, 44, 48, 255))
    put(img, bottom, (95, 102, 108, 255))


def sec_box(img, x, y, txt="53", accent=TEAL):
    recessed_window(img, (x, y - 17, x + 44, y + 17), rad=9)
    d = ImageDraw.Draw(img)
    d.text(((x + 22) * S, y * S), txt, font=bf("Bold Condensed", 22), fill=accent + (255,), anchor="mm")
    d.text(((x + 22) * S, (y + 26) * S), "SN", font=bf("SemiBold Condensed", 11), fill=(110, 116, 122, 255), anchor="mm")


# P1 · Gömme pencere + sönük segment
def p1():
    img = r2.base_no_sec()
    f = bf("Bold Condensed", 104)
    m, x0, tot, cx, y = digits_mask(f, cy=160)
    recessed_window(img, (int(x0 / S) - 16, 112, int((x0 + tot) / S) + 16, 210))
    put(img, ghost_mask(f, x0, y), (255, 255, 255, 14))
    premium_digits(img, m)
    colon(img, cx, y)
    sec_box(img, int((x0 + tot) / S) + 24, 146)
    return img


# P2 · Katmanlı derinlik (penceresiz)
def p2():
    img = r2.base_no_sec()
    f = bf("Bold Condensed", 120)
    m, x0, tot, cx, y = digits_mask(f, cy=158)
    for i in range(8, 0, -1):                                  # uzun yumuşak gölge
        put(img, m, (0, 0, 0, 22), blur=2, off=(i * 0.8, i * 1.4))
    premium_digits(img, m, top=(255, 255, 255), bot=(210, 214, 218))
    colon(img, cx, y)
    d = ImageDraw.Draw(img)
    d.text(((x0 + tot) / S * S + 12 * S, 134 * S), "53", font=bf("Bold Condensed", 26), fill=TEAL + (255,), anchor="lm")
    d.text(((x0 + tot) / S * S + 14 * S, 160 * S), "SN", font=bf("SemiBold Condensed", 11), fill=(110, 116, 122, 255), anchor="lm")
    return img


# P3 · Çift katman (vurgu rengi ofset gölge)
def p3():
    img = r2.base_no_sec()
    f = bf("Bold Condensed", 116)
    m, x0, tot, cx, y = digits_mask(f, cy=158)
    put(img, m, (0, 0, 0, 150), blur=10, off=(0, 8))
    put(img, m, TEAL + (90,), off=(5, 5))                       # renkli ofset katman
    edge = ImageChops.subtract(m.filter(ImageFilter.MaxFilter(5)), m)
    put(img, m, (240, 242, 240, 255))
    put(img, edge, (20, 24, 28, 255))
    hi = ImageChops.subtract(m, ImageChops.offset(m, 0, 2 * S)); put(img, hi, (255, 255, 255, 255))
    colon(img, cx, y, glow=False)
    sec_box(img, int((x0 + tot) / S) + 22, 146)
    return img


if __name__ == "__main__":
    vs = [("P1 · Gömme pencere + sönük segment", p1()), ("P2 · Katmanlı derinlik", p2()), ("P3 · Çift katman", p3())]
    t = 460; gap = 36
    W = gap + len(vs) * (t + gap); H = t + 80
    cv = Image.new("RGB", (W, H), (22, 22, 24)); dd = ImageDraw.Draw(cv)
    lab = bf("SemiBold Condensed", 12)
    msk = Image.new("L", (t, t), 0); ImageDraw.Draw(msk).ellipse((0, 0, t - 1, t - 1), fill=255)
    for i, (name, im) in enumerate(vs):
        x = gap + i * (t + gap)
        cv.paste(im.resize((t, t), Image.LANCZOS).convert("RGB"), (x, 20), msk)
        dd.text((x + t / 2, t + 50), name, font=lab, fill=(235, 235, 230), anchor="mm")
    cv.save(Path(__file__).parent / "saat_stilleri3.png"); print("ok")
