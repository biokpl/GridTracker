"""
gen_faces.py — Premium kadranları (WFF) tasarım ölçülerinden üretir.

Her kadran ayrı bir Gradle modülüdür (ayrı paket → saatte ayrı kadran):
  face_ultra  → A · Ultra Pro
(B, C sonra eklenecek)

Üretilenler: res/raw/watchface.xml, res/drawable/*.png (arka plan, ikonlar,
bitmap font glifleri), manifest, strings, watch_face_info, build.gradle.kts.
Bitmap font: Bahnschrift glifleri RESİM olarak gömülür (font dosyası dağıtılmaz);
renk WFF tarafında BitmapFont color ile verilir (beyaz glif + renk).
"""
import math, random, shutil, time
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops

ROOT = Path(__file__).resolve().parent.parent      # WatchApp
FD = "C:/Windows/Fonts/"
W = 450                                            # WFF kanvas
K = W / 480                                        # tasarım (480) → WFF (450)
CH = ("0123456789:.,+-−%₺ ·/½()"
      "ABCÇDEFGĞHIİJKLMNOÖPQRSŞTUÜVWXYZ"
      "abcçdefgğhıijklmnoöpqrsştuüvwxyz")


def k(v): return int(round(v * K))


def bfont(var, px):
    f = ImageFont.truetype(FD + "bahnschrift.ttf", px)
    f.set_variation_by_name(var)
    return f


TR_DATE = "".join(sorted(set("0123456789 Ocak Şubat Mart Nisan Mayıs Haziran Temmuz Ağustos Eylül Ekim Kasım Aralık "
                             "Pazartesi Salı Çarşamba Perşembe Cuma Cumartesi Pazar")))


def glyph_set(drawable, prefix, var, px, italic=0.0, chars_src=None):
    """Beyaz glif PNG'leri + <BitmapFont> XML'i döndürür. px = çizim boyu.
    italic>0: Bahnschrift'in italiği yok → glif tabandan sağa eğilir (eğim = italic, ~0.21 ≈ 12°)."""
    f = bfont(var, px)
    asc, desc = f.getmetrics()
    h = asc + desc
    # eğim payı: glif genişliği aynı zamanda harf aralığı → payı küçük tut, eğimi ortadan yap
    extra = int(math.ceil(italic * asc * 0.4)) if italic else 0
    chars = []
    for ch in (chars_src or CH):
        w = max(1, round(f.getlength(ch))) + extra
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        if ch == "−":   # Bahnschrift'te "−" glifi yok (kutu çiziliyordu): "+" genişliğinde, "-" kalınlığında çiz
            w = max(1, round(f.getlength("+"))); img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            def _ink(c):   # çizilmiş glifin gerçek kutusu (getbbox dikeyde yanıltıyor)
                t = Image.new("L", (w * 2, h)); ImageDraw.Draw(t).text((0, 0), c, font=f, fill=255); return t.getbbox()
            mb, pb = _ink("-"), _ink("+")
            th = mb[3] - mb[1]; cy = (pb[1] + pb[3]) / 2
            ImageDraw.Draw(img).rectangle((pb[0], round(cy - th / 2), pb[2] - 1, round(cy + th / 2) - 1), fill=(255, 255, 255, 255))
        else:
            ImageDraw.Draw(img).text((0, 0), ch, font=f, fill=(255, 255, 255, 255))
        if italic:   # üst sağa, taban sola; kayma payın iki yanına eşit dağılır
            off = (italic * asc - extra) / 2
            src = Image.new("RGBA", img.size, (0, 0, 0, 0)); src.paste(img, (0, 0))
            img = src.transform(img.size, Image.AFFINE, (1, italic, -italic * asc + off, 0, 1, 0), resample=Image.BICUBIC)
        name = f"{prefix}_u{ord(ch):04x}"
        img.save(drawable / f"{name}.png")
        cname = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}.get(ch, ch)
        chars.append(f'            <Character name="{cname}" resource="{name}" width="{w}" height="{h}" />')
    return (f'        <BitmapFont name="{prefix}">\n' + "\n".join(chars) + "\n        </BitmapFont>", h)


def module(mod, pkg, label):
    d = ROOT / mod
    if (d / "src").exists():
        shutil.rmtree(d / "src")
    for sub in ("raw", "xml", "drawable", "values"):
        (d / "src/main/res" / sub).mkdir(parents=True, exist_ok=True)
    (d / "build.gradle.kts").write_text(f'''plugins {{
    id("com.android.application")
}}

android {{
    namespace = "{pkg}"
    compileSdk = 35
    buildToolsVersion = "35.0.0"
    defaultConfig {{
        applicationId = "{pkg}"
        minSdk = 33
        targetSdk = 35
        versionCode = {int(time.time() // 60)}   // her üretimde yeni sürüm: saat çalışma zamanı önbelleğini tazeler
        versionName = "1.0"
    }}
}}
''', encoding="utf-8")
    (d / "src/main/AndroidManifest.xml").write_text('''<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <uses-feature android:name="android.hardware.type.watch" />
    <application android:hasCode="false" android:label="@string/wf_name">
        <meta-data android:name="com.google.android.wearable.standalone" android:value="true" />
        <property android:name="com.google.wear.watchface.format.version" android:value="2" />
        <property android:name="com.google.wear.watchface.format.publisher" android:value="biokpl" />
    </application>
</manifest>
''', encoding="utf-8")
    (d / "src/main/res/values/strings.xml").write_text(f'''<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="wf_name">{label}</string>
    <string name="slot_alsat">AL/SAT</string>
    <string name="slot_ezan">Namaz vakti</string>
    <string name="slot_kalan">Vakte kalan</string>
    <string name="slot_grafik">Grafik</string>
</resources>
''', encoding="utf-8")
    (d / "src/main/res/xml/watch_face_info.xml").write_text('''<?xml version="1.0" encoding="utf-8"?>
<WatchFaceInfo>
    <Preview value="@drawable/preview" />
    <Editable value="true" />
    <MultipleInstancesAllowed value="false" />
</WatchFaceInfo>
''', encoding="utf-8")
    return d


# ── WFF XML yardımcıları ─────────────────────────────────────────────────────
APP = "com.biokpl.gridwatch/com.biokpl.gridwatch."
EZAN = "com.mobilexsoft.ezanvakti/com.mobilexsoft.ezanvakti.complications."


def amb(alpha):
    return f'<Variant mode="AMBIENT" target="alpha" value="{alpha}" />'


def text(x, y, w, h, tpl, params, font, size, color, align="CENTER", aod=0):
    p = "".join(f'<Parameter expression="{e}" />' for e in params)
    return (f'<PartText x="{x}" y="{y}" width="{w}" height="{h}">{amb(aod)}'
            f'<Text align="{align}"><BitmapFont family="{font}" size="{size}" color="{color}">'
            + (f'<Template>{tpl}{p}</Template>' if params else tpl) + '</BitmapFont></Text></PartText>')


def slot(sid, x, y, w, h, types, provider, ptype, name, body, bound=None):
    b = bound or f'<BoundingBox x="0" y="0" width="{w}" height="{h}" />'
    return (f'<ComplicationSlot slotId="{sid}" x="{x}" y="{y}" width="{w}" height="{h}" '
            f'supportedTypes="{types}" isCustomizable="TRUE" displayName="@string/{name}">'
            f'<DefaultProviderPolicy defaultSystemProvider="EMPTY" defaultSystemProviderType="{ptype}" '
            f'primaryProvider="{provider}" primaryProviderType="{ptype}" />{b}'
            f'<Complication type="{ptype}">{body}</Complication></ComplicationSlot>')


def hexc(rgb, a=255): return "#%02x%02x%02x%02x" % (a, *rgb)


# ── A: floresan (VFD) saat + K/Z ışığı yardımcıları ─────────────────────────
ICE = (170, 235, 255)
VFD = dict(x=91, y=104, cell=50, colon=22, h=96, dw=40, dh=84, t=10)      # WFF px
VFDS = dict(x=335, y=127, cell=15, h=30, dw=11, dh=24, t=3)
WIN = (81, 100, 323, 204); SWIN = (331, 124, 369, 160)


VFD_GLOW = float(__import__("os").environ.get("VFD_GLOW", "1"))   # 0 = parlama yok
VFD_MESH = __import__("os").environ.get("VFD_MESH", "1") == "1"


def _vfd_cell(ch, cell, h, dw, dh, t, col, ghost=False):
    import render_vfd as V
    q = 4
    W_, H_ = cell * q, h * q
    on = Image.new("RGBA", (W_, H_), (0, 0, 0, 0)); od = ImageDraw.Draw(on)
    off = od if ghost else ImageDraw.Draw(Image.new("RGBA", (W_, H_)))   # yanmayan segmentler: ghost'ta çiz, normalde atla
    if ch == ":":
        V.draw_7seg(od, off, ":", (W_ - t * q * 1.3) / 2 - t * q * 0.1, (H_ - dh * q) / 2, dw * q, dh * q, t * q, 0, col, col)
    else:
        V.draw_7seg(od, off, ch, (W_ - dw * q) / 2 - dh * q * 0.06, (H_ - dh * q) / 2, dw * q, dh * q, t * q, 0, col, col)
    if not ghost and VFD_GLOW > 0:
        out = Image.new("RGBA", (W_, H_), (0, 0, 0, 0))
        for rad in (6 * q / 2 * VFD_GLOW, 2 * q / 2):
            g = on.filter(ImageFilter.GaussianBlur(rad))
            # çok soluk parlama piksellerini at (yarı saydam alanı küçült → hafif çizim)
            a_ = g.split()[3].point(lambda v: v if v > 24 else 0); g.putalpha(a_)
            out.alpha_composite(g)
        out.alpha_composite(on); on = out
    res = on.resize((cell, h), Image.LANCZOS)
    if not ghost and h >= 60 and VFD_MESH:   # büyük saat gliflerine VFD ızgarası
        a = res.split()[3]; md = ImageDraw.Draw(a)
        lay = Image.new("L", res.size, 255); ld = ImageDraw.Draw(lay)
        for xx in range(0, res.size[0], 4): ld.line((xx, 0, xx, res.size[1]), fill=185)
        for yy in range(0, res.size[1], 4): ld.line((0, yy, res.size[0], yy), fill=185)
        res.putalpha(ImageChops.multiply(a, lay))
    return res


def vfd_cells(spec, cells, size, aod_main, aod_halo):
    """Her rakam kendi kutusunda ortalı: Samsung motoru TTF yan boşluklarını tutarsız uyguluyor,
    tek kutuda 'hh:mm' yazınca '1' kayıyor ve hale katmanı rakamla örtüşmüyordu.
    cells: (x_ofs, genişlik, ifade | sabit metin, sönük_metin)"""
    out = []
    m, g1, g2 = VFD_FONTS
    layers = ((m, "#a01b2528", 0, "ghost"), (g2, "#1caaebff", aod_halo // 2, None),
              (g1, "#36aaebff", aod_halo, None), (m, "#ffaaebff", aod_main, None))
    for fam, col, a_, kind in layers:
        for xo, w, expr, ghost in cells:
            if kind == "ghost":
                if not ghost: continue
                body = ghost
            elif expr.startswith("="):
                body = f'<Template>%s<Parameter expression="{expr[1:]}" /></Template>'
            else:
                body = expr
            out.append(f'          <PartText x="{spec["x"] + xo}" y="{spec["y"]}" width="{w}" height="{spec["h"]}">{amb(a_)}'
                       f'<Text align="CENTER"><Font family="{fam}" size="{size}" color="{col}">{body}</Font></Text></PartText>')
    return "\n".join(out)


def vfd_font(dr, prefix, spec, col):
    chars = []
    for ch in "0123456789:":
        cw = spec.get("colon", spec["cell"]) if ch == ":" else spec["cell"]
        img = _vfd_cell(ch, cw, spec["h"], spec["dw"], spec["dh"], spec["t"], col + (255,))
        name = f"{prefix}_u{ord(ch):04x}"; img.save(dr / f"{name}.png")
        chars.append(f'            <Character name="{ch}" resource="{name}" width="{cw}" height="{spec["h"]}" />')
    return f'        <BitmapFont name="{prefix}">\n' + "\n".join(chars) + "\n        </BitmapFont>"


def _ghost_strip(spec, text, col):
    xs = 0; parts = []
    for ch in text:
        cw = spec.get("colon", spec["cell"]) if ch == ":" else spec["cell"]
        parts.append((xs, _vfd_cell(ch, cw, spec["h"], spec["dw"], spec["dh"], spec["t"], col, ghost=True))); xs += cw
    img = Image.new("RGBA", (xs, spec["h"]), (0, 0, 0, 0))
    for x, im in parts: img.alpha_composite(im, (x, 0))
    return img


def vfd_ghost(dr, name, spec, text, col):
    xs = 0; parts = []
    for ch in text:
        cw = spec.get("colon", spec["cell"]) if ch == ":" else spec["cell"]
        parts.append((xs, _vfd_cell(ch, cw, spec["h"], spec["dw"], spec["dh"], spec["t"], col, ghost=True))); xs += cw
    img = Image.new("RGBA", (xs, spec["h"]), (0, 0, 0, 0))
    for x, im in parts: img.alpha_composite(im, (x, 0))
    img.save(dr / f"{name}.png"); return xs


def recessed(g, box, rad, S2):
    x0, y0, x1, y1 = [v * S2 for v in box]
    m = Image.new("L", g.size, 0); ImageDraw.Draw(m).rounded_rectangle((x0, y0, x1, y1), radius=rad * S2, fill=255)
    g.paste(Image.new("RGBA", g.size, (6, 8, 10, 255)), (0, 0), m)
    sh = ImageChops.subtract(m, ImageChops.offset(m, 0, 7 * S2)).filter(ImageFilter.GaussianBlur(5 * S2))
    g.paste(Image.new("RGBA", g.size, (0, 0, 0, 255)), (0, 0), sh)
    edge = Image.new("L", g.size, 0); ImageDraw.Draw(edge).rounded_rectangle((x0, y0, x1, y1), radius=rad * S2, outline=255, width=2 * S2)
    g.paste(Image.new("RGBA", g.size, (40, 44, 48, 255)), (0, 0), edge)
    low = ImageChops.multiply(edge, ImageChops.subtract(m, ImageChops.offset(m, 0, -int((y1 - y0) * 0.5))))
    g.paste(Image.new("RGBA", g.size, (95, 102, 108, 255)), (0, 0), low)


def mesh_png(dr, box, name="vfd_mesh", alpha=80):
    """Pencere içi VFD ızgarası; çizgiler bg_ultra'daki ızgarayla aynı yerde (4 px)."""
    w, h = box[2] - box[0], box[3] - box[1]
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    for kk in range(4, w - 3, 4): d.line((kk, 3, kk, h - 3), fill=(0, 0, 0, alpha))
    for kk in range(4, h - 3, 4): d.line((3, kk, w - 3, kk), fill=(0, 0, 0, alpha))
    img.save(dr / f"{name}.png")


def glow_png(dr, name, w, h, below, rad, col, strength=0.35, below_k=0.22):
    import numpy as np
    q = 2; W_, H_ = w * q, (h + below) * q
    yy = np.arange(H_)[:, None].astype(np.float32); xx = np.arange(W_)[None, :].astype(np.float32)
    m = Image.new("L", (W_, H_), 0); ImageDraw.Draw(m).rounded_rectangle((0, 0, W_ - 1, h * q - 1), radius=rad * q, fill=255)
    inside = np.array(m).astype(np.float32) / 255
    hfall = np.exp(-((xx - W_ / 2) / (W_ / 2 * 0.55)) ** 2)
    t = np.clip((h * q - yy) / (h * q * 0.6), 0, 1)
    up = (1 - t) ** 2.2 * inside * hfall
    tb = np.clip((yy - h * q) / (below * q), 0, 1)
    down = np.where(yy > h * q, (1 - tb) ** 2, 0) * hfall
    a = (up * 150 * strength + down * 150 * below_k)
    y0 = int(h * q - 2)
    for dy in range(-q, q + 1):
        if 0 <= y0 + dy < H_: a[y0 + dy] = np.maximum(a[y0 + dy], hfall[0] * 230 * strength)
    lay = np.zeros((H_, W_, 4), np.uint8); lay[..., :3] = col; lay[..., 3] = a.clip(0, 255).astype(np.uint8)
    Image.fromarray(lay).filter(ImageFilter.GaussianBlur(2 * q)).resize((w, h + below), Image.LANCZOS).save(dr / f"{name}.png")


# ═════════════════════════ A · ULTRA PRO ═════════════════════════
def face_ultra():
    d = module("face_ultra", "com.biokpl.gridwatch.face.ultra", "AL/SAT Ultra Pro")
    dr = d / "src/main/res/drawable"
    # İç içerik büyütme: halka kenara taşındığı için iç öğeler merkeze göre Z kat.
    # k() boyutları Z ile ölçekler; üst düzey öğelerin x/y'sine yazımdan sonra
    # O = 225·(1−Z) ofseti eklenir (_center_scale).
    Z = 1.13
    def k(v): return int(round(v * K * Z))
    # ── arka plan PNG (2x çiz, küçült) ──
    S2 = 2; F = W * S2; C = F / 2
    bg = Image.new("RGBA", (F, F), (0, 0, 0, 255)); px = bg.load()
    for y in range(F):
        for x in range(F):
            t = min(1.0, math.hypot(x - C, y - C) / C) ** 1.4
            px[x, y] = (int(24 + (4 - 24) * t), int(30 + (5 - 30) * t), int(36 + (6 - 36) * t), 255)
    tex = Image.new("RGBA", (F, F), (0, 0, 0, 0)); td = ImageDraw.Draw(tex)
    for kk in range(-F, F, 7 * S2):
        td.line((kk, 0, kk + F, F), fill=(255, 255, 255, 7), width=S2)
    bg.alpha_composite(tex)
    g = ImageDraw.Draw(bg)

    # (dakika çizgileri/rakamları kaldırıldı — kadran doğrudan halkayla başlıyor)
    m = Image.new("L", (F, F), 0); ImageDraw.Draw(m).ellipse((0, 0, F - 1, F - 1), fill=255)
    out = Image.new("RGBA", (F, F), (0, 0, 0, 0)); out.paste(bg, (0, 0), m)
    recessed(out, WIN, 18, S2); recessed(out, SWIN, 8, S2)
    # yanmayan halka segmentleri (eskiden her karede çizilen kesikli yay)
    Rb = 213 * K * S2; THb = 18 * K * S2; gap_deg = math.degrees(4 * S2 / Rb)
    od_ = ImageDraw.Draw(out)
    for i in range(42):
        a0 = 225 + i * 270 / 42; a1 = a0 + 270 / 42 - gap_deg
        Ro = Rb + THb / 2   # PIL yay kalınlığı içe doğru: dış yarıçapı merkez + yarım kalınlık al
        od_.arc((C - Ro, C - Ro, C + Ro, C + Ro), a0 - 90, a1 - 90, fill=(38, 40, 44, 255), width=int(THb))
    # sönük 88:88 (pencerenin içinde)
    gh = Image.new("RGBA", (0, 0)) if False else None
    out_small = out.resize((W, W), Image.LANCZOS)
    # VFD ızgarası pencere içinde
    md_ = ImageDraw.Draw(out_small)
    for xx in range(WIN[0] + 4, WIN[2] - 3, 4): md_.line((xx, WIN[1] + 3, xx, WIN[3] - 3), fill=(0, 0, 0, 90))
    for yy in range(WIN[1] + 4, WIN[3] - 3, 4): md_.line((WIN[0] + 3, yy, WIN[2] - 3, yy), fill=(0, 0, 0, 90))
    out_small.save(dr / "bg_ultra.png")
    # halka boşluk maskesi: boşluk bölgelerinde arka planın kendisi (yanan yayın üstüne biner)
    gm = Image.new("L", (F, F), 0); gdm = ImageDraw.Draw(gm)
    for i in range(43):
        a1 = 225 + i * 270 / 42 - gap_deg
        if i == 0: continue
        Rg = Rb + THb / 2 + S2
        gdm.arc((C - Rg, C - Rg, C + Rg, C + Rg), a1 - 90, a1 + gap_deg - 90, fill=255, width=int(THb + 2 * S2))
    gm = gm.resize((W, W), Image.LANCZOS)
    gaps = Image.new("RGBA", (W, W), (0, 0, 0, 0)); gaps.paste(out_small, (0, 0), gm)
    gaps.save(dr / "ring_gaps.png")
    # ikonlar
    ic = Image.new("RGBA", (40, 40), (0, 0, 0, 0)); idr = ImageDraw.Draw(ic)
    idr.ellipse((4, 4, 36, 36), fill=(250, 199, 117, 255)); idr.ellipse((14, 0, 46, 32), fill=(0, 0, 0, 0))
    ic.save(dr / "ic_moon.png")
    hi = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    ImageDraw.Draw(hi).text((20, 21), "\u2665", font=ImageFont.truetype(FD + "seguisym.ttf", 36), fill=(255, 90, 110, 255), anchor="mm")
    hi.save(dr / "ic_heart.png")
    # bitmap fontlar
    fb, hb = glyph_set(dr, "bc", "Bold Condensed", 44)      # kullanım ~36 px
    fs, hs = glyph_set(dr, "sc", "SemiBold Condensed", 30)  # kullanım ~21-26 px
    fbi = glyph_set(dr, "bci", "Bold Condensed", 44, 0.21, "0123456789")[0]     # tarih: italik gün sayısı
    fsi = glyph_set(dr, "sci", "SemiBold Condensed", 30, 0.21, "".join(sorted(set(TR_DATE + "ONLINEOFF"))))[0]      # tarih: italik ay / gün adı
    # VFD rakamları: gerçek TTF (bitmap glifler AOD geçişinde CPU'yu kilitliyordu)
    import build_vfd_font
    (d / "src/main/res/font").mkdir(parents=True, exist_ok=True)
    # yazı tipi adı her üretimde değişir: saat çalışma zamanı fontları ada göre önbellekliyor
    global VFD_FONTS
    tag = format(int(time.time()) % 46656, "x")
    VFD_FONTS = (f"vfd7_{tag}", f"vfd7g1_{tag}", f"vfd7g2_{tag}")
    fd = d / "src/main/res/font"
    for old in fd.glob("vfd7*.ttf"): old.unlink()
    build_vfd_font.build(fd / f"{VFD_FONTS[0]}.ttf", f"VFD7{tag}")
    build_vfd_font.build(fd / f"{VFD_FONTS[1]}.ttf", f"VFD7G1{tag}", grow=30)   # parlama halesi (TimeText'te OutGlow yok)
    build_vfd_font.build(fd / f"{VFD_FONTS[2]}.ttf", f"VFD7G2{tag}", grow=60)
    mesh_png(dr, WIN); mesh_png(dr, SWIN, "vfd_mesh_s")
    ghost_w = 4 * VFD["cell"] + VFD["colon"]
    # önizleme: saatin gerçek ekran görüntüsü (design/preview_A_saat.png)
    shutil.copy(ROOT / "design/preview_A_saat.png", dr / "preview.png")

    # ── geometri ──
    R = 213 * K; TH = 18 * K
    L = 2 * math.pi * R * 0.75; seg = L / 42
    dash = f"{seg - 4:.2f} 4"
    arc_box = f'centerX="225" centerY="225" width="{round(2 * R)}" height="{round(2 * R)}"'
    grad = (f'<SweepGradient centerX="225" centerY="225" startAngle="225" endAngle="495" '
            f'colors="#ffff5550 #ffffbe3c #ff3ce1aa" positions="0 0.5 1" />')
    prog = "([COMPLICATION.RANGED_VALUE_VALUE] - [COMPLICATION.RANGED_VALUE_MIN]) / ([COMPLICATION.RANGED_VALUE_MAX] - [COMPLICATION.RANGED_VALUE_MIN])"
    TEAL, RED, GREEN, AMBER, GRAY, WHITE = "#ff3ce1aa", "#ffff7a6e", "#ff6ee6aa", "#fffac775", "#ff8c9196", "#fff5f5f0"

    SEG = 270 / 42; GAPD = math.degrees(4 / R)
    seg_a0 = f"(225 + {SEG:.4f} * clamp(floor({prog} * 42), 0, 41))"
    # yumuşak hale: yuvarlak uçlu, dışa doğru soluklaşan 3 katman (WFF'de bulanıklık yok)
    def _gg(al):
        return (f'<SweepGradient centerX="225" centerY="225" startAngle="225" endAngle="495" '
                f'colors="#{al}ff5550 #{al}ffbe3c #{al}3ce1aa" positions="0 0.5 1" />')
    glow_0, glow_1, glow_2, glow_3, glow_4 = _gg("12"), _gg("1c"), _gg("2a"), _gg("40"), _gg("60")
    grad_core0 = (f'<SweepGradient centerX="225" centerY="225" startAngle="225" endAngle="495" '
                  f'colors="#90ff9c95 #90ffd690 #9080eac2" positions="0 0.5 1" />')   # çekirdek dış kademe
    grad_body = _gg("d8")
    grad_core = (f'<SweepGradient centerX="225" centerY="225" startAngle="225" endAngle="495" '
                 f'colors="#e6ffb3ae #e6ffe3a8 #e6a9f0d8" positions="0 0.5 1" />')   # halka renginin açık tonu
    SEG_MID = f"({seg_a0} + {(270 / 42 - math.degrees(4 / R)) / 2:.3f})"
    # nefes efekti: parça alfası 255→40 (1 sn) ve geri — sonsuz döngü, ekran açıkken
    # (Animation öğesi ileri-geri gidemiyor: söner sonra başa atlar) → kosinüsle gerçek nefes, 2 sn periyot
    BREATH = '<Transform target="alpha" value="147 + 108 * cos(3.14159265 * [SECOND_MILLISECOND])" />'
    ring_body = (
        # segmentli parlak yay
        f'<PartDraw x="0" y="0" width="450" height="450">{amb(110)}'
        f'<Arc {arc_box} startAngle="225" endAngle="225"><Transform target="endAngle" value="225 + 270 * {prog}" />'
        f'<Stroke color="#ffffffff" thickness="{TH}">{grad}</Stroke></Arc></PartDraw>'
        # segment boşlukları — halenin altında kalsın (parlama alanında siyah çizik görünmesin)
        f'<PartImage x="0" y="0" width="450" height="450">{amb(0)}<Image resource="ring_gaps" /></PartImage>'
        # ATEŞ TOPU — hepsi halkanın o anki renginde: yumuşak hale (5 kademe) → segment → yuvarlak gövde → iki kademeli sıcak çekirdek
        f'<PartDraw x="0" y="0" width="450" height="450">{amb(0)}{BREATH}'
        f'<Arc {arc_box} startAngle="225" endAngle="225">'
        f'<Transform target="startAngle" value="{seg_a0} + -0.8" /><Transform target="endAngle" value="{seg_a0} + {SEG - GAPD - -0.8:.3f}" />'
        f'<Stroke color="#ffffffff" thickness="{TH + 26}" cap="ROUND">{glow_0}</Stroke></Arc></PartDraw>'
        f'<PartDraw x="0" y="0" width="450" height="450">{amb(0)}{BREATH}'
        f'<Arc {arc_box} startAngle="225" endAngle="225">'
        f'<Transform target="startAngle" value="{seg_a0} + -0.2" /><Transform target="endAngle" value="{seg_a0} + {SEG - GAPD - -0.2:.3f}" />'
        f'<Stroke color="#ffffffff" thickness="{TH + 20}" cap="ROUND">{glow_1}</Stroke></Arc></PartDraw>'
        f'<PartDraw x="0" y="0" width="450" height="450">{amb(0)}{BREATH}'
        f'<Arc {arc_box} startAngle="225" endAngle="225">'
        f'<Transform target="startAngle" value="{seg_a0} + 0.3" /><Transform target="endAngle" value="{seg_a0} + {SEG - GAPD - 0.3:.3f}" />'
        f'<Stroke color="#ffffffff" thickness="{TH + 14}" cap="ROUND">{glow_2}</Stroke></Arc></PartDraw>'
        f'<PartDraw x="0" y="0" width="450" height="450">{amb(0)}{BREATH}'
        f'<Arc {arc_box} startAngle="225" endAngle="225">'
        f'<Transform target="startAngle" value="{seg_a0} + 0.7" /><Transform target="endAngle" value="{seg_a0} + {SEG - GAPD - 0.7:.3f}" />'
        f'<Stroke color="#ffffffff" thickness="{TH + 9}" cap="ROUND">{glow_3}</Stroke></Arc></PartDraw>'
        f'<PartDraw x="0" y="0" width="450" height="450">{amb(0)}{BREATH}'
        f'<Arc {arc_box} startAngle="225" endAngle="225">'
        f'<Transform target="startAngle" value="{seg_a0} + 1.0" /><Transform target="endAngle" value="{seg_a0} + {SEG - GAPD - 1.0:.3f}" />'
        f'<Stroke color="#ffffffff" thickness="{TH + 4}" cap="ROUND">{glow_4}</Stroke></Arc></PartDraw>'
        f'<PartDraw x="0" y="0" width="450" height="450">{amb(110)}'
        f'<Arc {arc_box} startAngle="225" endAngle="225">'
        f'<Transform target="startAngle" value="{seg_a0}" /><Transform target="endAngle" value="{seg_a0} + {SEG - GAPD:.3f}" />'
        f'<Stroke color="#ffffffff" thickness="{TH}">{grad}</Stroke></Arc></PartDraw>'
        f'<PartDraw x="0" y="0" width="450" height="450">{amb(0)}{BREATH}'
        f'<Arc {arc_box} startAngle="225" endAngle="225">'
        f'<Transform target="startAngle" value="{SEG_MID} - 0.05" /><Transform target="endAngle" value="{SEG_MID} + 0.05" />'
        f'<Stroke color="#ffffffff" thickness="{TH + 8}" cap="ROUND">{grad_body}</Stroke></Arc></PartDraw>'
        f'<PartDraw x="0" y="0" width="450" height="450">{amb(0)}{BREATH}'
        f'<Arc {arc_box} startAngle="225" endAngle="225">'
        f'<Transform target="startAngle" value="{SEG_MID} - 0.05" /><Transform target="endAngle" value="{SEG_MID} + 0.05" />'
        f'<Stroke color="#ffffffff" thickness="{TH * 0.75:.1f}" cap="ROUND">{grad_core0}</Stroke></Arc></PartDraw>'
        f'<PartDraw x="0" y="0" width="450" height="450">{amb(110)}{BREATH}'
        f'<Arc {arc_box} startAngle="225" endAngle="225">'
        f'<Transform target="startAngle" value="{SEG_MID} - 0.05" /><Transform target="endAngle" value="{SEG_MID} + 0.05" />'
        f'<Stroke color="#ffffffff" thickness="{TH * 0.45:.1f}" cap="ROUND">{grad_core}</Stroke></Arc></PartDraw>'
    )

    # S/H yuvaları tam ekran + tam ekran BoundingOval: Samsung yuva çizimini sınır alanına kırpıyor.
    # Stop bölge çizgileri (halka iç çeperi): S yuvası halka başı→kurum stopu (kırmızı),
    # H yuvası kurum stopu→izleme stopu (amber). Yuvalar tam ekran → yazılar mutlak (ölçekli) konumda.
    O_ = 225 * (1 - Z)
    SX = lambda x: round(x + O_); SY = lambda y: round(y + O_)
    RI = R - TH / 2 - 5
    _tri = Image.new("RGBA", (450 * 4, 450 * 4), (0, 0, 0, 0))
    _tip, _base, _hw = RI - 2.5, RI - 12, 5.5
    ImageDraw.Draw(_tri).polygon([(4 * 225, 4 * (225 - _tip)), (4 * (225 - _hw), 4 * (225 - _base)),
                                  (4 * (225 + _hw), 4 * (225 - _base))], fill=(255, 80, 80, 140))   # %55 silik
    _tri.resize((450, 450), Image.LANCZOS).save(dr / "stop_tri.png")

    def stop_marker():
        """Kurum stopu konumunda iç çeperde silik kırmızı üçgen (pozisyon yokken gizli)."""
        return ('<Condition><Expressions><Expression name="on"><![CDATA[[COMPLICATION.RANGED_VALUE_VALUE] > 0]]></Expression></Expressions>'
                f'<Compare expression="on"><PartImage x="0" y="0" width="450" height="450" pivotX="0.5" pivotY="0.5">{amb(90)}'
                '<Transform target="angle" value="270 * [COMPLICATION.RANGED_VALUE_VALUE] - 135" />'
                '<Image resource="stop_tri" /></PartImage></Compare></Condition>')

    def live_badge():
        """SN altında veri durumu: yeşil yanıp sönen nokta + ONLINE / gri nokta + OFFLINE.
        Canlılık Stop yuvasının MAX değerinde gelir (1 = canlı, 1.5 = bayat)."""
        blink_d = '<Transform target="alpha" value="160 + 95 * cos(3.14159265 * [SECOND_MILLISECOND])" />'
        blink_g = '<Transform target="alpha" value="70 + 60 * cos(3.14159265 * [SECOND_MILLISECOND])" />'
        def dot(col, glow):
            g = (f'<PartDraw x="324" y="181" width="20" height="20">{amb(0)}{blink_g}'
                 '<Ellipse x="0" y="0" width="20" height="20"><Fill color="#ffffffff">'
                 '<RadialGradient centerX="10" centerY="10" radius="10" colors="#9046e682 #3046e682 #0046e682" positions="0 0.5 1" />'
                 '</Fill></Ellipse></PartDraw>') if glow else ''
            return g + (f'<PartDraw x="330" y="187" width="8" height="8">{amb(0)}{blink_d if glow else ""}'
                        f'<Ellipse x="0" y="0" width="8" height="8"><Fill color="{col}" /></Ellipse></PartDraw>')
        def label(t, col):
            return (f'<PartText x="341" y="184" width="64" height="16">{amb(0)}'
                    f'<Text align="START"><BitmapFont family="sci" size="16" color="{col}">{t}</BitmapFont></Text></PartText>')
        return ('<Condition><Expressions><Expression name="live"><![CDATA[[COMPLICATION.RANGED_VALUE_MAX] < 1.2]]></Expression></Expressions>'
                f'<Compare expression="live">{dot("#ff46e682", True)}{label("ONLINE", "#a5969ba0")}</Compare>'
                f'<Default>{dot("#ff6e7278", False)}{label("OFFLINE", "#7d969ba0")}</Default></Condition>')

    def zone(t0, t1, col):
        return (f'<PartDraw x="0" y="0" width="450" height="450">{amb(90)}'
                f'<Arc centerX="225" centerY="225" width="{round(2 * RI)}" height="{round(2 * RI)}" startAngle="225" endAngle="225">'
                f'<Transform target="startAngle" value="225 + 270 * {t0}" /><Transform target="endAngle" value="225 + 270 * {t1}" />'
                f'<Stroke color="{col}" thickness="2.4" /></Arc></PartDraw>')

    kz_cond = lambda tpl_x, tpl_w, size, ty=0: (
        '<Condition><Expressions>'
        '<Expression name="pos"><![CDATA[[COMPLICATION.RANGED_VALUE_VALUE] > 0]]></Expression>'
        '<Expression name="neg"><![CDATA[[COMPLICATION.RANGED_VALUE_VALUE] < 0]]></Expression>'
        '</Expressions>'
        f'<Compare expression="pos">{text(tpl_x, ty, tpl_w, size + 4, "%s", ["[COMPLICATION.TEXT]"], "bc", size, TEAL, "END", 140)}</Compare>'
        f'<Compare expression="neg">{text(tpl_x, ty, tpl_w, size + 4, "%s", ["[COMPLICATION.TEXT]"], "bc", size, RED, "END", 140)}</Compare>'
        f'<Default>{text(tpl_x, ty, tpl_w, size + 4, "%s", ["[COMPLICATION.TEXT]"], "bc", size, "#ffb4b2a9", "END", 140)}</Default>'
        '</Condition>')

    DX, DY = 250, k(56) + 19   # takvim bloğu: büyük gün sayısının sağ kenarı; sağında ay / gün adı iki satır
    c_, cl = VFD["cell"], VFD["colon"]
    clock_xml = vfd_cells(VFD, [
        (0, c_, "=floor([HOUR_0_23] / 10)", "8"), (c_, c_, "=[HOUR_0_23] % 10", "8"),
        (2 * c_, cl, ":", ":"),
        (2 * c_ + cl, c_, "=floor([MINUTE] / 10)", "8"), (3 * c_ + cl, c_, "=[MINUTE] % 10", "8"),
    ], VFD["dh"] * 100 // 84, 255, 120) + "\n" + vfd_cells(VFDS, [
        (0, VFDS["cell"], "=floor([SECOND] / 10)", "8"), (VFDS["cell"], VFDS["cell"], "=[SECOND] % 10", "8"),
    ], VFDS["cell"] * 2, 0, 0)
    px0, py0, pw, ph = k(96), k(272), k(288), k(92)       # panel
    for nm, col in (("glow_pos", (60, 225, 170)), ("glow_neg", (255, 80, 90)), ("glow_neu", (150, 200, 255))):
        from glow_v2 import glow_png2   # kesik piramit ışık + ortada parlak ışın + beyaz çizik
        glow_png2(pw, ph, k(22), k(22), col).save(dr / f"{nm}.png")
    xml = f'''<?xml version="1.0" encoding="utf-8"?>
<!-- A · ULTRA PRO — gen_faces.py ile üretildi, elle düzenlemeyin. -->
<WatchFace width="450" height="450" clipShape="CIRCLE">
    <Metadata key="CLOCK_TYPE" value="DIGITAL" />
    <Metadata key="PREVIEW_TIME" value="14:32:27" />
    <BitmapFonts>
{fb}
{fs}
{fbi}
{fsi}
    </BitmapFonts>
    <Scene backgroundColor="#ff000000">
        <PartImage x="0" y="0" width="450" height="450">{amb(0)}<Image resource="bg_ultra" /></PartImage>
        <!-- yanmayan halka segmentleri, sönük 88:88 ve VFD ızgarası bg_ultra.png'ye gömülü (performans) -->

        {slot(0, 0, 0, 450, 450, "RANGED_VALUE", APP + "RingComplicationService", "RANGED_VALUE", "slot_alsat", ring_body,
              '<BoundingOval x="0" y="0" width="450" height="450" />')}

        {text(0, DY + k(3) + 2, DX, k(40), "%s", ["[DAY]"], "bci", k(40), "#ffffb296", "END", 140)}
        {text(DX + k(8), DY + k(3), 450 - DX - k(8), k(22), "%s", ["[MONTH_F]"], "sci", k(20), "#ffa0a5aa", "START", 110)}
        {text(DX + k(8), DY + k(23), 450 - DX - k(8), k(22), "%s", ["[DAY_OF_WEEK_F]"], "sci", k(20), "#ffa0a5aa", "START", 110)}

{clock_xml}
          <PartImage x="{WIN[0]}" y="{WIN[1]}" width="{WIN[2] - WIN[0]}" height="{WIN[3] - WIN[1]}"><Image resource="vfd_mesh" /></PartImage>
          <PartImage x="{SWIN[0]}" y="{SWIN[1]}" width="{SWIN[2] - SWIN[0]}" height="{SWIN[3] - SWIN[1]}">{amb(0)}<Image resource="vfd_mesh_s" /></PartImage>
          {text(SWIN[0], SWIN[3] + 1, SWIN[2] - SWIN[0], 16, "SN", [], "sc", 13, "#ff6e737a", "CENTER", 0)}

        <PartDraw x="{k(104)}" y="{k(226)}" width="{k(272)}" height="{k(42)}">{amb(0)}
            <RoundRectangle x="0" y="0" width="{k(272)}" height="{k(42)}" cornerRadiusX="{k(21)}" cornerRadiusY="{k(21)}">
                <Fill color="#ff281c08" /><Stroke color="#ff966419" thickness="2" />
            </RoundRectangle>
            <Rectangle x="{k(184)}" y="{k(9)}" width="2" height="{k(24)}"><Fill color="#ff7a5214" /></Rectangle>
        </PartDraw>
        <PartImage x="{k(116)}" y="{k(237)}" width="{k(20)}" height="{k(20)}">{amb(140)}<Image resource="ic_moon" /></PartImage>
        {slot(1, k(138), k(226), k(148), k(42), "SHORT_TEXT", EZAN + "SonrakiVakitComplicationProviderService", "SHORT_TEXT", "slot_ezan",
              text(0, k(2), k(148), k(38), "%s   %s", ["[COMPLICATION.TITLE]", "[COMPLICATION.TEXT]"], "sc", k(25), AMBER, "CENTER", 150))}
        {slot(5, k(290), k(226), k(84), k(42), "SHORT_TEXT", EZAN + "VaktinCikmasinaComplicationProviderService", "SHORT_TEXT", "slot_kalan",
              text(0, k(2), k(84), k(38), "%s", ["[COMPLICATION.TEXT]"], "sc", k(25), "#ffffdc9a", "CENTER", 150))}

        <PartDraw x="{px0}" y="{py0}" width="{pw}" height="{ph}">{amb(0)}
            <RoundRectangle x="0" y="0" width="{pw}" height="{ph}" cornerRadiusX="{k(22)}" cornerRadiusY="{k(22)}">
                <Fill color="#eb0e1216" /><Stroke color="#ff2d343a" thickness="2" />
            </RoundRectangle>
        </PartDraw>
        {slot(6, k(184), k(286), k(60), k(44), "SMALL_IMAGE", APP + "SparkComplicationService", "SMALL_IMAGE", "slot_grafik",
              f'<PartImage x="0" y="0" width="{k(60)}" height="{k(44)}">{amb(0)}<Image resource="[COMPLICATION.SMALL_IMAGE]" /></PartImage>')}
        {slot(2, px0, py0, pw, ph + k(22), "RANGED_VALUE", APP + "KzComplicationService", "RANGED_VALUE", "slot_alsat",
              '<Condition><Expressions>'
              '<Expression name="pos"><![CDATA[[COMPLICATION.RANGED_VALUE_VALUE] > 0]]></Expression>'
              '<Expression name="neg"><![CDATA[[COMPLICATION.RANGED_VALUE_VALUE] < 0]]></Expression></Expressions>'
              f'<Compare expression="pos"><PartImage x="0" y="0" width="{pw}" height="{ph + k(22)}">{amb(0)}<Image resource="glow_pos" /></PartImage></Compare>'
              f'<Compare expression="neg"><PartImage x="0" y="0" width="{pw}" height="{ph + k(22)}">{amb(0)}<Image resource="glow_neg" /></PartImage></Compare>'
              f'<Default><PartImage x="0" y="0" width="{pw}" height="{ph + k(22)}">{amb(0)}<Image resource="glow_neu" /></PartImage></Default>'
              '</Condition>'
              + text(k(14), k(6), k(100), k(40), "%s", ["[COMPLICATION.TITLE]"], "bc", k(34), WHITE, "START", 150)
              + kz_cond(k(14) + k(100), pw - k(28) - k(100), k(40), k(4)))}
        {slot(7, px0 + k(14), k(330), pw - k(28), k(30), "RANGED_VALUE", APP + "RingComplicationService", "RANGED_VALUE", "slot_alsat",
              text(0, 0, k(190), k(30), "%s", ["[COMPLICATION.TEXT]"], "sc", k(24), "#ff9aa0a6", "START", 0)
              + text(k(190), 0, pw - k(28) - k(190), k(30), "%s", ["[COMPLICATION.TITLE]"], "sc", k(24), "#ffc8cdd2", "END", 0))}

        {slot(3, 0, 0, 450, 450, "RANGED_VALUE", APP + "StopComplicationService", "RANGED_VALUE", "slot_alsat",
              zone("0", "[COMPLICATION.RANGED_VALUE_VALUE]", "#8cff5050") + stop_marker() + live_badge()
              + text(SX(k(96)), SY(k(376)), k(140), k(32), "%s", ["[COMPLICATION.TEXT]"], "sc", k(28), RED, "CENTER", 120),
              '<BoundingOval x="0" y="0" width="450" height="450" />')}
        {slot(4, 0, 0, 450, 450, "RANGED_VALUE", APP + "TargetComplicationService", "RANGED_VALUE", "slot_alsat",
              zone("[COMPLICATION.RANGED_VALUE_MIN]", "[COMPLICATION.RANGED_VALUE_VALUE]", "#8cffc45a")
              + text(SX(k(244)), SY(k(376)), k(140), k(32), "%s", ["[COMPLICATION.TEXT]"], "sc", k(28), GREEN, "CENTER", 120),
              '<BoundingOval x="0" y="0" width="450" height="450" />')}

        <PartImage x="{k(160)}" y="{k(412)}" width="{k(20)}" height="{k(20)}">{amb(0)}<Image resource="ic_heart" /></PartImage>
        {text(k(184), k(408), 60, k(28), "%s", ["[HEART_RATE]"], "sc", k(21), "#ffd2d2d2", "START", 0)}
        <PartDraw x="{k(250)}" y="{k(413)}" width="{k(40)}" height="{k(18)}">{amb(0)}
            <RoundRectangle x="1" y="1" width="{k(38)}" height="{k(16)}" cornerRadiusX="3" cornerRadiusY="3">
                <Stroke color="#ff787d82" thickness="2" />
            </RoundRectangle>
            <Rectangle x="4" y="4" width="1" height="{k(18) - 8}">
                <Transform target="width" value="{k(32)} * [BATTERY_PERCENT] / 100" />
                <Fill color="#ff78dc78" />
            </Rectangle>
        </PartDraw>
        {text(k(296), k(408), 70, k(28), "%s%%", ["[BATTERY_PERCENT]"], "sc", k(21), GRAY, "START", 0)}
    </Scene>
</WatchFace>
'''
    xml = _center_scale(xml, Z)
    (d / "src/main/res/raw/watchface.xml").write_text(xml, encoding="utf-8")
    print("A üretildi:", d)


def _center_scale(xml, Z):
    """Scene'in doğrudan çocuklarının x/y'sine merkez ofseti ekler.
    Tam ekran (450x450) öğelere dokunmaz; genişliği 450 olanlarda yalnız y kayar."""
    import re
    O = 225 * (1 - Z)
    out = []
    for line in xml.splitlines():
        m = re.match(r'^(        <(?:PartDraw|PartImage|PartText|DigitalClock|ComplicationSlot)(?: slotId="\d+")?) x="(-?\d+)" y="(-?\d+)" width="(\d+)" height="(\d+)"(.*)$', line)
        if m:
            head, x, y, w, h, rest = m.groups(); x, y = int(x), int(y)
            if not (w == "450" and h == "450"):
                if w != "450": x = round(x + O)
                y = round(y + O)
            line = f'{head} x="{x}" y="{y}" width="{w}" height="{h}"{rest}'
        out.append(line)
    return "\n".join(out) + "\n"


# ── ortak yardımcılar (B, C) ─────────────────────────────────────────────────
def glyphs_from(drawable, prefix, f, chars=CH):
    asc, desc = f.getmetrics(); h = asc + desc; out = []
    for ch in chars:
        w = max(1, round(f.getlength(ch)))
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(img).text((0, 0), ch, font=f, fill=(255, 255, 255, 255))
        name = f"{prefix}_u{ord(ch):04x}"; img.save(drawable / f"{name}.png")
        out.append(f'            <Character name="{ch}" resource="{name}" width="{w}" height="{h}" />')
    return f'        <BitmapFont name="{prefix}">\n' + "\n".join(out) + "\n        </BitmapFont>"


def canvas2x(c_in, c_out):
    S2 = 2; F = W * S2; C = F / 2
    bg = Image.new("RGBA", (F, F), (0, 0, 0, 255)); px = bg.load()
    for y in range(F):
        for x in range(F):
            t = min(1.0, math.hypot(x - C, y - C) / C) ** 1.4
            px[x, y] = tuple(int(c_in[i] + (c_out[i] - c_in[i]) * t) for i in range(3)) + (255,)
    return bg, F, C


def save_round(bg, F, path):
    m = Image.new("L", (F, F), 0); ImageDraw.Draw(m).ellipse((0, 0, F - 1, F - 1), fill=255)
    out = Image.new("RGBA", (F, F), (0, 0, 0, 0)); out.paste(bg, (0, 0), m)
    out.resize((W, W), Image.LANCZOS).save(path)


def preview_from(src, idx, dr):
    """Konsept görselindeki idx'inci saatin yüzünü önizleme yap."""
    with Image.open(ROOT / "design" / src) as im:
        tw = (im.width - 4 * 60) // 3 if idx is not None else None
        if idx is None:
            box = (95, 63, 610, 578)
        else:
            x = 60 + idx * (tw + 60) + int(tw * 0.09); y = 20 + int(tw * 0.09)
            box = (x, y, x + int(tw * 0.82), y + int(tw * 0.82))
        im.crop(box).resize((450, 450), Image.LANCZOS).save(dr / "preview.png")


def ring_prog(): return "([COMPLICATION.RANGED_VALUE_VALUE] - [COMPLICATION.RANGED_VALUE_MIN]) / ([COMPLICATION.RANGED_VALUE_MAX] - [COMPLICATION.RANGED_VALUE_MIN])"


def kz_condition(x, w, h, font, size, pos, neg, neu, align, aod=140):
    return ('<Condition><Expressions>'
            '<Expression name="pos"><![CDATA[[COMPLICATION.RANGED_VALUE_VALUE] > 0]]></Expression>'
            '<Expression name="neg"><![CDATA[[COMPLICATION.RANGED_VALUE_VALUE] < 0]]></Expression></Expressions>'
            f'<Compare expression="pos">{text(x, 0, w, h, "%s", ["[COMPLICATION.TEXT]"], font, size, pos, align, aod)}</Compare>'
            f'<Compare expression="neg">{text(x, 0, w, h, "%s", ["[COMPLICATION.TEXT]"], font, size, neg, align, aod)}</Compare>'
            f'<Default>{text(x, 0, w, h, "%s", ["[COMPLICATION.TEXT]"], font, size, neu, align, aod)}</Default></Condition>')


# ═════════════════════════ B · LUXURY ═════════════════════════
def face_lux():
    d = module("face_lux", "com.biokpl.gridwatch.face.luxury", "AL/SAT Luxury")
    dr = d / "src/main/res/drawable"
    bg, F, C = canvas2x((22, 30, 52), (3, 4, 10)); S2 = 2
    sun = Image.new("RGBA", (F, F), (0, 0, 0, 0)); sd = ImageDraw.Draw(sun)
    def pt(r, a, cx=C, cy=C):
        t = math.radians(a - 90); return cx + r * math.cos(t), cy + r * math.sin(t)
    for a in range(0, 360, 2):
        sd.line((C, C, *pt(F, a)), fill=(255, 255, 255, 6), width=S2)
    bg.alpha_composite(sun); g = ImageDraw.Draw(bg)
    GOLD, GOLD2 = (222, 184, 110), (150, 118, 62)
    g.ellipse((6 * S2, 6 * S2, F - 6 * S2, F - 6 * S2), outline=GOLD2, width=2 * S2)
    for i in range(60):
        a = i * 6
        if i % 5 == 0: g.line((*pt(226 * K * S2, a), *pt(200 * K * S2, a)), fill=GOLD, width=6 * S2)
        else: g.line((*pt(226 * K * S2, a), *pt(218 * K * S2, a)), fill=(120, 110, 90), width=S2)
    def sub_base(cx, cy, r, track=True):
        cx, cy, r = cx * K * S2, cy * K * S2, r * K * S2
        g.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(8, 10, 20), outline=(70, 66, 56), width=2 * S2)
        if track:
            bb = (cx - r + 8 * S2, cy - r + 8 * S2, cx + r - 8 * S2, cy + r - 8 * S2)
            g.arc(bb, 135, 405, fill=(40, 42, 55), width=6 * S2)
    sub_base(130, 280, 56); sub_base(350, 280, 56)
    cx, cy, r = 240 * K * S2, 368 * K * S2, 70 * K * S2
    g.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(8, 10, 20), outline=GOLD2, width=2 * S2)
    bb = (cx - r + 9 * S2, cy - r + 9 * S2, cx + r - 9 * S2, cy + r - 9 * S2)
    g.arc(bb, 135, 405, fill=(40, 42, 55), width=8 * S2)
    # namaz alt kadranında sabit ince amber halka (süslemedir)
    lx, ly, lr = 130 * K * S2, 280 * K * S2, (56 - 8) * K * S2
    g.arc((lx - lr, ly - lr, lx + lr, ly + lr), 135, 405, fill=(150, 110, 50), width=2 * S2)
    save_round(bg, F, dr / "bg_lux.png")
    fsc = glyph_set(dr, "sc", "SemiBold Condensed", 48)[0]
    fbc = glyph_set(dr, "bc", "Bold Condensed", 96)[0]
    flt = glyphs_from(dr, "lt", ImageFont.truetype(FD + "SegUIVar.ttf", 140), "0123456789:")
    preview_from("kadran_konseptleri_v2.png", 1, dr)

    GOLD_C, GOLD_D, CREAM, MUTE = "#ffdeb86e", "#ff96763e", "#fff8f4ec", "#ff968c78"
    prog = ring_prog()
    sc = lambda c: (int(c[0] * K), int(c[1] * K))
    L_ = sc((130, 280)); R_ = sc((350, 280)); B_ = sc((240, 368)); rr = int(56 * K); rb = int(70 * K)
    # sağ alt kadran pil yayı
    bat_box = f'centerX="{R_[0]}" centerY="{R_[1]}" width="{2 * (rr - 8)}" height="{2 * (rr - 8)}"'
    pos_box = f'centerX="{B_[0]}" centerY="{B_[1]}" width="{2 * (rb - 9)}" height="{2 * (rb - 9)}"'
    xml = f'''<?xml version="1.0" encoding="utf-8"?>
<!-- B · LUXURY — gen_faces.py ile üretildi, elle düzenlemeyin. -->
<WatchFace width="450" height="450" clipShape="CIRCLE">
    <Metadata key="CLOCK_TYPE" value="DIGITAL" />
    <Metadata key="PREVIEW_TIME" value="14:32:27" />
    <BitmapFonts>
{fsc}
{fbc}
{flt}
    </BitmapFonts>
    <Scene backgroundColor="#ff000000">
        <PartImage x="0" y="0" width="450" height="450">{amb(0)}<Image resource="bg_lux" /></PartImage>
        {text(0, k(92), 450, 22, "%s · %s %s", ["[DAY_OF_WEEK_F]", "[DAY]", "[MONTH_F]"], "sc", k(15), GOLD_C, "CENTER", 120)}
        <DigitalClock x="0" y="{k(112)}" width="450" height="{k(104)}">{amb(170)}
            <TimeText format="hh:mm" hourFormat="24" align="CENTER" x="0" y="0" width="450" height="{k(104)}">
                <BitmapFont family="lt" size="{k(104)}" color="{CREAM}" />
            </TimeText>
        </DigitalClock>

        {slot(1, L_[0] - rr, L_[1] + 6, 2 * rr, 18, "SHORT_TEXT", EZAN + "SonrakiVakitComplicationProviderService", "SHORT_TEXT", "slot_ezan",
              text(0, 0, 2 * rr, 18, "%s %s", ["[COMPLICATION.TITLE]", "[COMPLICATION.TEXT]"], "sc", 13, MUTE, "CENTER", 120))}
        {slot(5, L_[0] - rr, L_[1] - 22, 2 * rr, 28, "SHORT_TEXT", EZAN + "VaktinCikmasinaComplicationProviderService", "SHORT_TEXT", "slot_kalan",
              text(0, 0, 2 * rr, 28, "%s", ["[COMPLICATION.TEXT]"], "bc", k(20), CREAM, "CENTER", 150))}

        <PartDraw x="0" y="0" width="450" height="450">{amb(0)}
            <Arc {bat_box} startAngle="225" endAngle="225">
                <Transform target="endAngle" value="225 + 270 * [BATTERY_PERCENT] / 100" />
                <Stroke color="#ff78c88c" thickness="5" cap="ROUND" />
            </Arc>
        </PartDraw>
        {text(R_[0] - rr, R_[1] - 30, 2 * rr, 16, "NABIZ", [], "sc", 11, MUTE, "CENTER", 0)}
        {text(R_[0] - rr, R_[1] - 14, 2 * rr, 28, "%s", ["[HEART_RATE]"], "bc", k(20), CREAM, "CENTER", 0)}
        {text(R_[0] - rr, R_[1] + 14, 2 * rr, 16, "PİL %s%%", ["[BATTERY_PERCENT]"], "sc", 11, MUTE, "CENTER", 0)}

        {slot(0, 0, 0, 450, 450, "RANGED_VALUE", APP + "RingComplicationService", "RANGED_VALUE", "slot_alsat",
              f'<PartDraw x="0" y="0" width="450" height="450">{amb(110)}<Arc {pos_box} startAngle="225" endAngle="225">'
              f'<Transform target="endAngle" value="225 + 270 * {prog}" /><Stroke color="{GOLD_C}" thickness="7" cap="ROUND" /></Arc></PartDraw>',
              f'<BoundingOval x="{B_[0] - rb}" y="{B_[1] - rb}" width="{2 * rb}" height="{2 * rb}" />')}
        {slot(2, B_[0] - rb, B_[1] - 34, 2 * rb, 44, "RANGED_VALUE", APP + "KzComplicationService", "RANGED_VALUE", "slot_alsat",
              text(0, 0, 2 * rb, 18, "%s", ["[COMPLICATION.TITLE]"], "bc", k(16), GOLD_C, "CENTER", 140)
              + kz_condition(0, 2 * rb, 26, "bc", k(26), "#ff78dca0", "#ffff7a6e", CREAM, "CENTER").replace('y="0" width="' + str(2 * rb) + '" height="26"', 'y="18" width="' + str(2 * rb) + '" height="26"'))}
        {slot(3, B_[0] - rb + 10, B_[1] + 14, rb - 10, 18, "SHORT_TEXT", APP + "StopComplicationService", "SHORT_TEXT", "slot_alsat",
              text(0, 0, rb - 10, 18, "%s", ["[COMPLICATION.TEXT]"], "sc", 12, "#ffd28c82", "END", 110))}
        {slot(4, B_[0] + 4, B_[1] + 14, rb - 10, 18, "SHORT_TEXT", APP + "TargetComplicationService", "SHORT_TEXT", "slot_alsat",
              text(0, 0, rb - 10, 18, "%s", ["[COMPLICATION.TEXT]"], "sc", 12, "#ff8cc8a0", "START", 110))}
    </Scene>
</WatchFace>
'''
    (d / "src/main/res/raw/watchface.xml").write_text(xml, encoding="utf-8")
    print("B üretildi:", d)


# ═════════════════════════ C · NEON TRADER ═════════════════════════
def face_neon():
    d = module("face_neon", "com.biokpl.gridwatch.face.neon", "AL/SAT Neon Trader")
    dr = d / "src/main/res/drawable"
    bg, F, C = canvas2x((10, 12, 22), (0, 0, 0)); S2 = 2; g = ImageDraw.Draw(bg)
    x0, x1, y0, y1 = (C - 160 * K * S2), (C + 160 * K * S2), 226 * K * S2, 330 * K * S2
    g.rounded_rectangle((x0 - 10 * S2, y0 - 14 * S2, x1 + 10 * S2, y1 + 10 * S2), radius=16 * S2, fill=(10, 14, 26), outline=(35, 45, 70), width=2 * S2)
    for kk in range(1, 4):
        yy = y0 + (y1 - y0) * kk / 4; g.line((x0, yy, x1, yy), fill=(30, 38, 60), width=S2)
    save_round(bg, F, dr / "bg_neon.png")
    fsc = glyph_set(dr, "sc", "SemiBold Condensed", 48)[0]
    fbc = glyph_set(dr, "bc", "Bold Condensed", 96)[0]
    fag = glyphs_from(dr, "ag", ImageFont.truetype(FD + "AGENCYB.TTF", 150), "0123456789:")
    preview_from("kadran_konseptleri_v2.png", 2, dr)

    CY, MG, ICE, MUTE = "#ff00e6ff", "#ffff3cc8", "#ffebfaff", "#ff6e7896"
    prog = ring_prog()
    R = 222 * K
    box = f'centerX="225" centerY="225" width="{round(2 * R)}" height="{round(2 * R)}"'
    ring = (f'<PartDraw x="0" y="0" width="450" height="450">{amb(0)}<Arc {box} startAngle="225" endAngle="225">'
            f'<Transform target="endAngle" value="225 + 270 * {prog}" /><Stroke color="#5000e6ff" thickness="16" cap="ROUND" /></Arc></PartDraw>'
            f'<PartDraw x="0" y="0" width="450" height="450">{amb(110)}<Arc {box} startAngle="225" endAngle="225">'
            f'<Transform target="endAngle" value="225 + 270 * {prog}" /><Stroke color="{CY}" thickness="6" cap="ROUND" /></Arc></PartDraw>')
    cx0, cy0, cw, chh = k(80), k(222), k(320), k(104)
    xml = f'''<?xml version="1.0" encoding="utf-8"?>
<!-- C · NEON TRADER — gen_faces.py ile üretildi, elle düzenlemeyin. -->
<WatchFace width="450" height="450" clipShape="CIRCLE">
    <Metadata key="CLOCK_TYPE" value="DIGITAL" />
    <Metadata key="PREVIEW_TIME" value="14:32:27" />
    <BitmapFonts>
{fsc}
{fbc}
{fag}
    </BitmapFonts>
    <Scene backgroundColor="#ff000000">
        <PartImage x="0" y="0" width="450" height="450">{amb(0)}<Image resource="bg_neon" /></PartImage>
        <PartDraw x="0" y="0" width="450" height="450">{amb(60)}
            <Arc {box} startAngle="225" endAngle="495"><Stroke color="#ff191e2d" thickness="6" cap="ROUND" /></Arc>
        </PartDraw>
        {slot(0, 0, 0, 450, 450, "RANGED_VALUE", APP + "RingComplicationService", "RANGED_VALUE", "slot_alsat", ring,
              '<BoundingOval x="0" y="0" width="450" height="450" />')}

        {text(k(60), k(70), k(178), 22, "%s %s %s ·", ["[DAY_OF_WEEK]", "[DAY]", "[MONTH_S]"], "sc", k(15), MUTE, "END", 120)}
        {slot(1, k(244), k(70), k(150), 22, "SHORT_TEXT", EZAN + "SonrakiVakitComplicationProviderService", "SHORT_TEXT", "slot_ezan",
              text(0, 0, k(150), 22, "%s %s", ["[COMPLICATION.TITLE]", "[COMPLICATION.TEXT]"], "sc", k(15), "#fffac775", "START", 130))}
        <DigitalClock x="0" y="{k(92)}" width="450" height="{k(120)}">{amb(170)}
            <TimeText format="hh:mm" hourFormat="24" align="CENTER" x="0" y="0" width="450" height="{k(120)}">
                <BitmapFont family="ag" size="{k(120)}" color="{ICE}" />
            </TimeText>
        </DigitalClock>

        {slot(6, cx0, cy0, cw, chh, "SMALL_IMAGE", APP + "CandleComplicationService", "SMALL_IMAGE", "slot_grafik",
              f'<PartImage x="0" y="0" width="{cw}" height="{chh}">{amb(0)}<Image resource="[COMPLICATION.SMALL_IMAGE]" /></PartImage>')}

        {slot(2, k(90), k(338), k(300), 34, "RANGED_VALUE", APP + "KzComplicationService", "RANGED_VALUE", "slot_alsat",
              text(0, 0, k(140), 34, "%s", ["[COMPLICATION.TITLE]"], "bc", k(26), ICE, "START", 150)
              + kz_condition(k(140), k(300) - k(140), 34, "bc", k(24), CY, MG, "#ffb4b2a9", "END"))}
        {slot(3, k(110), k(374), k(120), 20, "SHORT_TEXT", APP + "StopComplicationService", "SHORT_TEXT", "slot_alsat",
              text(0, 0, k(120), 20, "%s", ["[COMPLICATION.TEXT]"], "sc", k(14), "#ffff505a", "CENTER", 120))}
        {slot(4, k(250), k(374), k(120), 20, "SHORT_TEXT", APP + "TargetComplicationService", "SHORT_TEXT", "slot_alsat",
              text(0, 0, k(120), 20, "%s", ["[COMPLICATION.TEXT]"], "sc", k(14), "#ff5af0a0", "CENTER", 120))}
        {slot(7, k(100), k(398), k(280), 20, "RANGED_VALUE", APP + "RingComplicationService", "RANGED_VALUE", "slot_alsat",
              text(0, 0, k(280), 20, "%s · %s", ["[COMPLICATION.TEXT]", "[COMPLICATION.TITLE]"], "sc", k(13), MUTE, "CENTER", 0))}
    </Scene>
</WatchFace>
'''
    (d / "src/main/res/raw/watchface.xml").write_text(xml, encoding="utf-8")
    print("C üretildi:", d)


if __name__ == "__main__":
    import sys
    which = sys.argv[1:] or ["a", "b", "c"]
    if "a" in which: face_ultra()
    if "b" in which: face_lux()
    if "c" in which: face_neon()
