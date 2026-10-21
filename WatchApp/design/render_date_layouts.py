"""A kadranı: tarih yerleşimi seçenekleri (gerçek ekran görüntüsü üzerinde)."""
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

SRC = "preview_A_saat.png"
GRAY, ICE = (160, 165, 170), (170, 235, 255)
F = "C:/Windows/Fonts/bahnschrift.ttf"


def bfont(px, wght=600, wdth=75):
    f = ImageFont.truetype(F, px)
    try: f.set_variation_by_axes([wght, wdth])
    except Exception: pass
    return f


def clean():
    im = np.asarray(Image.open(SRC).convert("RGB"))
    x0, y0, x1, y1 = 120, 66, 330, 100
    reg = im[y0:y1, x0:x1].astype(np.float32)
    big = im[y0 - 24:y1 + 24, x0 - 24:x1 + 24]
    med = cv2.medianBlur(cv2.medianBlur(big, 41), 41).astype(np.float32)[24:-24, 24:-24]
    m = (np.abs(reg - med).max(2) > 18).astype(np.uint8) * 255
    mk = np.zeros(im.shape[:2], np.uint8); mk[y0:y1, x0:x1] = m
    mk = cv2.dilate(mk, np.ones((3, 3), np.uint8), iterations=2)
    return Image.fromarray(cv2.inpaint(im, mk, 4, cv2.INPAINT_TELEA))


def opt_a(im):
    """A: büyük sayı solda, sağında ay üstte / gün altta."""
    d = ImageDraw.Draw(im)
    fn, fs = bfont(42, 700), bfont(19, 600)
    cx = 240
    nw = d.textlength("21", font=fn)
    sw = max(d.textlength("Ekim", font=fs), d.textlength("Çarşamba", font=fs))
    x = cx - (nw + 8 + sw) / 2
    d.text((x, 99), "21", font=fn, fill=ICE, anchor="ls")
    d.text((x + nw + 8, 79), "Ekim", font=fs, fill=GRAY, anchor="ls")
    d.text((x + nw + 8, 98), "Çarşamba", font=fs, fill=GRAY, anchor="ls")


def opt_b(im):
    """B: üç satır ortalı (21 / Ekim / Çarşamba)."""
    d = ImageDraw.Draw(im)
    d.text((240, 72), "21", font=bfont(24, 700), fill=ICE, anchor="ms")
    d.text((240, 86), "Ekim", font=bfont(14, 600), fill=GRAY, anchor="ms")
    d.text((240, 100), "Çarşamba", font=bfont(14, 600), fill=GRAY, anchor="ms")


if __name__ == "__main__":
    base = Image.open(SRC).convert("RGB")
    tiles = [("Şu an", base)]
    for name, fn in (("A · Takvim bloğu", opt_a), ("B · Üç satır", opt_b)):
        im = clean(); fn(im); tiles.append((name, im))
    font = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 22)
    W = 480; canvas = Image.new("RGB", (W * 3 + 40, 520 + 260), (10, 11, 13))
    dd = ImageDraw.Draw(canvas)
    for i, (n, im) in enumerate(tiles):
        canvas.paste(im, (i * (W + 20), 40))
        dd.text((i * (W + 20) + W // 2, 20), n, font=font, fill=(220, 222, 226), anchor="mm")
        z = im.crop((110, 30, 370, 120)).resize((W, 166), Image.LANCZOS)   # yakın plan
        canvas.paste(z, (i * (W + 20), 540))
    dd.text((10, 530), "Yakın plan:", font=ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 16), fill=(150, 152, 156))
    canvas.save("tarih_yerlesim.png"); print("ok")
