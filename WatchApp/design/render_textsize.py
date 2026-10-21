"""A kadranı: yazı büyütme önizlemesi — gerçek ekran görüntüsündeki yazıları
arka plandan ayırıp verilen oranda büyütür (çerçeve/grafik aynı kalır)."""
import numpy as np
from PIL import Image, ImageDraw, ImageFont

SRC = "preview_A_saat.png"          # 480x480 gerçek ekran görüntüsü

# (ad, bölge x0,y0,x1,y1 [480 px], hiza, oran, arka plan: "row" satır medyanı | "bg" bg_ultra)
ITEMS = [
    ("tarih",       (150, 66, 330, 98),  "c", 28 / 25, "bg"),
    ("namaz",       (130, 231, 288, 260), "c", 25 / 22, "row"),
    ("kalan",       (312, 231, 378, 260), "c", 25 / 22, "row"),
    ("kz",          (262, 282, 392, 322), "r", 40 / 34, "row"),
    ("lot",         (90, 342, 262, 370),  "l", 24 / 20, "row"),
    ("yuzde",       (318, 342, 392, 370), "r", 24 / 20, "row"),
    ("stop",        (100, 394, 250, 424), "c", 28 / 24, "bg"),
    ("hedef",       (250, 394, 400, 424), "c", 28 / 24, "bg"),
]


def run():
    shot = np.asarray(Image.open(SRC).convert("RGB")).astype(np.float32)
    bgu = np.asarray(Image.open("../face_ultra/src/main/res/drawable/bg_ultra.png").convert("RGB")
                     .resize((480, 480), Image.LANCZOS)).astype(np.float32)
    out = shot.copy()
    for name, (x0, y0, x1, y1), al, f, mode in ITEMS:
        reg = shot[y0:y1, x0:x1]
        import cv2
        # yerel arka plan: geniş median filtre ince yazı çizgilerini siler
        pad = 24
        big = shot[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad].astype(np.uint8)
        kz = max(21, (y1 - y0) // 2 * 2 + 21)        # yazı boyuna göre filtre (kalın yazı izi kalmasın)
        med = cv2.medianBlur(cv2.medianBlur(big, kz), kz).astype(np.float32)
        oy, ox = y0 - max(0, y0 - pad), x0 - max(0, x0 - pad)
        bg = med[oy:oy + (y1 - y0), ox:ox + (x1 - x0)]
        d = np.abs(reg - bg).max(axis=2)
        m = d > 40
        if not m.any():
            print("yazı bulunamadı:", name); continue
        strong = d >= np.percentile(d[m], 75) if m.sum() > 3 else m   # kenar yumuşatması rengi koyulaştırmasın
        col = reg[strong].mean(axis=0)
        span = np.maximum(np.abs(col - bg).max(axis=2), 1)
        alpha = np.clip(d / span, 0, 1)
        alpha[d < 18] = 0
        ys, xs = np.nonzero(alpha > 0.15)
        bx0, bx1, by0, by1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
        # yazıyı sil → çevresinden doldur (inpaint; panel ışığı/desen korunur)
        import cv2
        mk = np.zeros(out.shape[:2], np.uint8)
        mk[y0:y1, x0:x1] = (alpha > 0.05).astype(np.uint8) * 255
        mk = cv2.dilate(mk, np.ones((3, 3), np.uint8), iterations=2)
        out = cv2.inpaint(np.clip(out, 0, 255).astype(np.uint8), mk, 4, cv2.INPAINT_TELEA).astype(np.float32)
        # yazı katmanı (renk + alfa) — büyüt
        a_img = Image.fromarray((alpha[by0:by1, bx0:bx1] * 255).astype(np.uint8))
        w, h = a_img.size
        nw, nh = round(w * f), round(h * f)
        a_big = np.asarray(a_img.resize((nw, nh), Image.LANCZOS)).astype(np.float32) / 255
        cy = y0 + (by0 + by1) / 2
        if al == "l":   nx = x0 + bx0
        elif al == "r": nx = x0 + bx1 - nw
        else:           nx = x0 + (bx0 + bx1) / 2 - nw / 2
        nx, ny = int(round(nx)), int(round(cy - nh / 2))
        tgt = out[ny:ny + nh, nx:nx + nw]
        out[ny:ny + nh, nx:nx + nw] = tgt * (1 - a_big[..., None]) + col * a_big[..., None]
    after = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))
    before = Image.open(SRC).convert("RGB")
    # yan yana + başlık
    font = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 22)
    canvas = Image.new("RGB", (480 * 2 + 30, 520), (10, 11, 13))
    canvas.paste(before, (0, 40)); canvas.paste(after, (510, 40))
    dd = ImageDraw.Draw(canvas)
    dd.text((240, 20), "Şu an", font=font, fill=(220, 222, 226), anchor="mm")
    dd.text((750, 20), "Yazılar büyütülmüş", font=font, fill=(220, 222, 226), anchor="mm")
    canvas.save("yazi_boyut_onizleme.png")
    after.save("yazi_boyut_sonra.png")
    print("ok")


if __name__ == "__main__":
    run()
