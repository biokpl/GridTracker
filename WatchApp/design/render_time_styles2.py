"""Saat için profesyonel tipografi seçenekleri (efekt yerine tipografi)."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops
import render_time_styles as r

S, N = r.S, r.N
HH, MM = "19", "03"
TEAL = (60, 225, 170)


def bf(var, sz):
    f = ImageFont.truetype("C:/Windows/Fonts/bahnschrift.ttf", int(sz * S)); f.set_variation_by_name(var); return f


def base_no_sec():
    img = r.base()
    bg = Image.open(r.BG).convert("RGBA").resize((N, N), Image.LANCZOS)
    box = (int(330 * S), int(112 * S), int(380 * S), int(196 * S))      # eski saniyeyi de sil
    img.paste(bg.crop(box), box[:2])
    return img


def draw_time(img, hh_font, mm_font, hh_col, mm_col, colon, cy=158, gap=10, colon_mode="dots", shadow=True):
    d = ImageDraw.Draw(img)
    wh = d.textlength(HH, font=hh_font); wm = d.textlength(MM, font=mm_font)
    cw = 16 * S
    total = wh + gap * S + cw + gap * S + wm
    x0 = 225 * S - total / 2; y = cy * S
    if shadow:
        sh = Image.new("RGBA", (N, N), (0, 0, 0, 0)); sd = ImageDraw.Draw(sh)
        sd.text((x0, y), HH, font=hh_font, fill=(0, 0, 0, 170), anchor="lm")
        sd.text((x0 + wh + 2 * gap * S + cw, y), MM, font=mm_font, fill=(0, 0, 0, 170), anchor="lm")
        img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(5 * S)), (3 * S, 5 * S)); d = ImageDraw.Draw(img)
    d.text((x0, y), HH, font=hh_font, fill=hh_col, anchor="lm")
    cx = x0 + wh + gap * S + cw / 2
    if colon_mode == "dots":
        for dy in (-20, 20):
            d.rounded_rectangle((cx - 6 * S, y + dy * S - 6 * S, cx + 6 * S, y + dy * S + 6 * S), radius=2 * S, fill=colon)
    else:
        d.line((cx, y - 34 * S, cx, y + 34 * S), fill=colon, width=3 * S)
    d.text((x0 + wh + 2 * gap * S + cw, y), MM, font=mm_font, fill=mm_col, anchor="lm")
    return x0, total


def sec_pill(img, x, y, txt="53"):
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((x * S, (y - 15) * S, (x + 40) * S, (y + 15) * S), radius=15 * S, fill=(10, 40, 32, 255), outline=TEAL + (255,), width=2 * S)
    d.text(((x + 20) * S, y * S), txt, font=bf("Bold Condensed", 20), fill=TEAL + (255,), anchor="mm")


# A · Kalın saat / ince dakika
def a():
    img = base_no_sec()
    x0, tot = draw_time(img, bf("Bold Condensed", 120), bf("Light Condensed", 120), (246, 246, 242, 255), (246, 246, 242, 255), TEAL + (255,))
    d = ImageDraw.Draw(img)
    d.text(((x0 + tot) / S * S + 10 * S, 132 * S), "53", font=bf("SemiBold Condensed", 26), fill=TEAL + (255,), anchor="lm")
    return img


# B · İki ton + saniye kapsülü
def b():
    img = base_no_sec()
    x0, tot = draw_time(img, bf("Bold Condensed", 118), bf("Bold Condensed", 118), (246, 246, 242, 255), TEAL + (255,), (120, 128, 134, 255), colon_mode="bar")
    sec_pill(img, int((x0 + tot) / S) + 10, 140)
    return img


# C · Gravür (kadrana işlenmiş)
def c():
    img = base_no_sec()
    m = Image.new("L", (N, N), 0); md = ImageDraw.Draw(m)
    f = bf("Bold Condensed", 122)
    md.text((225 * S, 158 * S), "19:03", font=f, fill=255, anchor="mm")
    # iç gölge (üst kenar koyu), alt kenar ışık
    dark = ImageChops.subtract(m, ImageChops.offset(m, 0, 3 * S))
    light = ImageChops.subtract(m, ImageChops.offset(m, 0, -3 * S))
    body = Image.new("RGBA", (N, N), (0, 0, 0, 0)); body.paste(Image.new("RGBA", (N, N), (226, 228, 230, 255)), (0, 0), m)
    img.alpha_composite(body)
    for msk, col in ((dark, (90, 95, 100, 255)), (light, (255, 255, 255, 255))):
        l = Image.new("RGBA", (N, N), (0, 0, 0, 0)); l.paste(Image.new("RGBA", (N, N), col), (0, 0), msk.filter(ImageFilter.GaussianBlur(S)))
        img.alpha_composite(l)
    d = ImageDraw.Draw(img)
    d.text((352 * S, 134 * S), "53", font=bf("SemiBold Condensed", 24), fill=(150, 156, 160, 255), anchor="mm")
    return img


# D · Saniye çubuğu
def d_():
    img = base_no_sec()
    x0, tot = draw_time(img, bf("SemiBold Condensed", 120), bf("SemiBold Condensed", 120), (246, 246, 242, 255), (246, 246, 242, 255), TEAL + (255,))
    d = ImageDraw.Draw(img)
    y = 213 * S; xa, xb = x0, x0 + tot
    d.rounded_rectangle((xa, y - 2 * S, xb, y + 2 * S), radius=2 * S, fill=(50, 54, 58, 255))
    d.rounded_rectangle((xa, y - 2 * S, xa + (xb - xa) * 53 / 60, y + 2 * S), radius=2 * S, fill=TEAL + (255,))
    for k in range(0, 61, 15):
        xx = xa + (xb - xa) * k / 60; d.line((xx, y - 6 * S, xx, y + 6 * S), fill=(110, 116, 122, 255), width=S)
    return img


if __name__ == "__main__":
    vs = [("A · Kalın saat / ince dakika", a()), ("B · İki ton + saniye kapsülü", b()),
          ("C · Gravür (kadrana işlenmiş)", c()), ("D · Saniye çubuğu", d_())]
    t = 380; gap = 30
    W = gap + len(vs) * (t + gap); H = t + 80
    cv = Image.new("RGB", (W, H), (22, 22, 24)); dd = ImageDraw.Draw(cv)
    lab = bf("SemiBold Condensed", 11)
    msk = Image.new("L", (t, t), 0); ImageDraw.Draw(msk).ellipse((0, 0, t - 1, t - 1), fill=255)
    for i, (name, im) in enumerate(vs):
        x = gap + i * (t + gap)
        cv.paste(im.resize((t, t), Image.LANCZOS).convert("RGB"), (x, 20), msk)
        dd.text((x + t / 2, t + 50), name, font=lab, fill=(235, 235, 230), anchor="mm")
    cv.save(Path(__file__).parent / "saat_stilleri2.png"); print("ok")
