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
import math, random, shutil
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

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


def glyph_set(drawable, prefix, var, px):
    """Beyaz glif PNG'leri + <BitmapFont> XML'i döndürür. px = çizim boyu."""
    f = bfont(var, px)
    asc, desc = f.getmetrics()
    h = asc + desc
    chars = []
    for ch in CH:
        w = max(1, round(f.getlength(ch)))
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(img).text((0, 0), ch, font=f, fill=(255, 255, 255, 255))
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
        versionCode = 1
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
    out.resize((W, W), Image.LANCZOS).save(dr / "bg_ultra.png")
    # ikonlar
    ic = Image.new("RGBA", (40, 40), (0, 0, 0, 0)); idr = ImageDraw.Draw(ic)
    idr.ellipse((4, 4, 36, 36), fill=(250, 199, 117, 255)); idr.ellipse((14, 0, 46, 32), fill=(0, 0, 0, 0))
    ic.save(dr / "ic_moon.png")
    hi = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    ImageDraw.Draw(hi).text((20, 21), "\u2665", font=ImageFont.truetype(FD + "seguisym.ttf", 36), fill=(255, 90, 110, 255), anchor="mm")
    hi.save(dr / "ic_heart.png")
    # bitmap fontlar
    fb, hb = glyph_set(dr, "bc", "Bold Condensed", 120)
    fs, hs = glyph_set(dr, "sc", "SemiBold Condensed", 48)
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

    ring_body = (
        # parlama (geniş, soluk)
        f'<PartDraw x="0" y="0" width="450" height="450">{amb(0)}'
        f'<Arc {arc_box} startAngle="225" endAngle="225"><Transform target="endAngle" value="225 + 270 * {prog}" />'
        f'<Stroke color="#22ffffff" thickness="{TH * 1.6:.1f}">{grad}</Stroke></Arc></PartDraw>'
        # segmentli parlak yay
        f'<PartDraw x="0" y="0" width="450" height="450">{amb(110)}'
        f'<Arc {arc_box} startAngle="225" endAngle="225"><Transform target="endAngle" value="225 + 270 * {prog}" />'
        f'<Stroke color="#ffffffff" thickness="{TH}" dashIntervals="{dash}">{grad}</Stroke></Arc></PartDraw>'
        # fiyat noktası (parlama + beyaz)
        f'<PartDraw x="0" y="0" width="450" height="450">{amb(0)}'
        f'<Arc {arc_box} startAngle="225" endAngle="225">'
        f'<Transform target="startAngle" value="224.6 + 270 * {prog}" /><Transform target="endAngle" value="225.4 + 270 * {prog}" />'
        f'<Stroke color="#50ffffff" thickness="36" cap="ROUND" /></Arc></PartDraw>'
        f'<PartDraw x="0" y="0" width="450" height="450">{amb(150)}'
        f'<Arc {arc_box} startAngle="225" endAngle="225">'
        f'<Transform target="startAngle" value="224.6 + 270 * {prog}" /><Transform target="endAngle" value="225.4 + 270 * {prog}" />'
        f'<Stroke color="#ffffffff" thickness="22" cap="ROUND" /></Arc></PartDraw>'
    )

    kz_cond = lambda tpl_x, tpl_w, size: (
        '<Condition><Expressions>'
        '<Expression name="pos"><![CDATA[[COMPLICATION.RANGED_VALUE_VALUE] > 0]]></Expression>'
        '<Expression name="neg"><![CDATA[[COMPLICATION.RANGED_VALUE_VALUE] < 0]]></Expression>'
        '</Expressions>'
        f'<Compare expression="pos">{text(tpl_x, 0, tpl_w, 36, "%s", ["[COMPLICATION.TEXT]"], "bc", size, TEAL, "END", 140)}</Compare>'
        f'<Compare expression="neg">{text(tpl_x, 0, tpl_w, 36, "%s", ["[COMPLICATION.TEXT]"], "bc", size, RED, "END", 140)}</Compare>'
        f'<Default>{text(tpl_x, 0, tpl_w, 36, "%s", ["[COMPLICATION.TEXT]"], "bc", size, "#ffb4b2a9", "END", 140)}</Default>'
        '</Condition>')

    px0, py0, pw, ph = k(96), k(272), k(288), k(92)       # panel
    xml = f'''<?xml version="1.0" encoding="utf-8"?>
<!-- A · ULTRA PRO — gen_faces.py ile üretildi, elle düzenlemeyin. -->
<WatchFace width="450" height="450" clipShape="CIRCLE">
    <Metadata key="CLOCK_TYPE" value="DIGITAL" />
    <Metadata key="PREVIEW_TIME" value="14:32:27" />
    <BitmapFonts>
{fb}
{fs}
    </BitmapFonts>
    <Scene backgroundColor="#ff000000">
        <PartImage x="0" y="0" width="450" height="450">{amb(0)}<Image resource="bg_ultra" /></PartImage>

        <PartDraw x="0" y="0" width="450" height="450">{amb(70)}
            <Arc {arc_box} startAngle="225" endAngle="495">
                <Stroke color="#ff26282c" thickness="{TH}" dashIntervals="{dash}" />
            </Arc>
        </PartDraw>

        {slot(0, 0, 0, 450, 450, "RANGED_VALUE", APP + "RingComplicationService", "RANGED_VALUE", "slot_alsat", ring_body,
              '<BoundingOval x="0" y="0" width="450" height="450" />')}

        {text(0, k(90), 450, k(30), "%s %s %s", ["[DAY_OF_WEEK_F]", "[DAY]", "[MONTH_F]"], "sc", k(21), GRAY, "CENTER", 110)}

        <DigitalClock x="{-k(14)}" y="{k(120)}" width="450" height="{k(112)}">{amb(170)}
            <TimeText format="hh:mm" hourFormat="24" align="CENTER" x="0" y="0" width="450" height="{k(112)}">
                <BitmapFont family="bc" size="{k(112)}" color="{WHITE}" />
            </TimeText>
        </DigitalClock>
        <DigitalClock x="{k(132) + 225 - 40}" y="{k(142)}" width="80" height="{k(30)}">{amb(0)}
            <TimeText format="ss" align="CENTER" x="0" y="0" width="80" height="{k(30)}">
                <BitmapFont family="bc" size="{k(30)}" color="{TEAL}" />
            </TimeText>
        </DigitalClock>
        {text(k(132) + 225 - 40, k(176), 80, 18, "SN", [], "sc", 14, "#ff6e737a", "CENTER", 0)}

        <PartDraw x="{k(104)}" y="{k(226)}" width="{k(272)}" height="{k(42)}">{amb(0)}
            <RoundRectangle x="0" y="0" width="{k(272)}" height="{k(42)}" cornerRadiusX="{k(21)}" cornerRadiusY="{k(21)}">
                <Fill color="#ff281c08" /><Stroke color="#ff966419" thickness="2" />
            </RoundRectangle>
            <Rectangle x="{k(184)}" y="{k(9)}" width="2" height="{k(24)}"><Fill color="#ff7a5214" /></Rectangle>
        </PartDraw>
        <PartImage x="{k(116)}" y="{k(237)}" width="{k(20)}" height="{k(20)}">{amb(140)}<Image resource="ic_moon" /></PartImage>
        {slot(1, k(138), k(226), k(148), k(42), "SHORT_TEXT", EZAN + "SonrakiVakitComplicationProviderService", "SHORT_TEXT", "slot_ezan",
              text(0, k(4), k(148), k(34), "%s %s", ["[COMPLICATION.TITLE]", "[COMPLICATION.TEXT]"], "sc", k(22), AMBER, "CENTER", 150))}
        {slot(5, k(290), k(226), k(84), k(42), "SHORT_TEXT", EZAN + "VaktinCikmasinaComplicationProviderService", "SHORT_TEXT", "slot_kalan",
              text(0, k(4), k(84), k(34), "%s", ["[COMPLICATION.TEXT]"], "sc", k(22), "#ffffdc9a", "CENTER", 150))}

        <PartDraw x="{px0}" y="{py0}" width="{pw}" height="{ph}">{amb(0)}
            <RoundRectangle x="0" y="0" width="{pw}" height="{ph}" cornerRadiusX="{k(22)}" cornerRadiusY="{k(22)}">
                <Fill color="#eb0e1216" /><Stroke color="#ff2d343a" thickness="2" />
            </RoundRectangle>
        </PartDraw>
        {slot(6, k(184), k(286), k(60), k(44), "SMALL_IMAGE", APP + "SparkComplicationService", "SMALL_IMAGE", "slot_grafik",
              f'<PartImage x="0" y="0" width="{k(60)}" height="{k(44)}">{amb(0)}<Image resource="[COMPLICATION.SMALL_IMAGE]" /></PartImage>')}
        {slot(2, px0 + k(14), k(278), pw - k(28), k(40), "RANGED_VALUE", APP + "KzComplicationService", "RANGED_VALUE", "slot_alsat",
              text(0, 0, k(100), k(40), "%s", ["[COMPLICATION.TITLE]"], "bc", k(34), WHITE, "START", 150) + kz_cond(k(100), pw - k(28) - k(100), k(34)))}
        {slot(7, px0 + k(14), k(330), pw - k(28), k(30), "RANGED_VALUE", APP + "RingComplicationService", "RANGED_VALUE", "slot_alsat",
              text(0, 0, k(180), k(30), "%s", ["[COMPLICATION.TEXT]"], "sc", k(20), "#ff9aa0a6", "START", 0)
              + text(k(180), 0, pw - k(28) - k(180), k(30), "%s", ["[COMPLICATION.TITLE]"], "sc", k(20), "#ffc8cdd2", "END", 0))}

        {slot(3, k(96), k(376), k(140), k(32), "SHORT_TEXT", APP + "StopComplicationService", "SHORT_TEXT", "slot_alsat",
              text(0, 0, k(140), k(32), "%s", ["[COMPLICATION.TEXT]"], "sc", k(24), RED, "CENTER", 120))}
        {slot(4, k(244), k(376), k(140), k(32), "SHORT_TEXT", APP + "TargetComplicationService", "SHORT_TEXT", "slot_alsat",
              text(0, 0, k(140), k(32), "%s", ["[COMPLICATION.TEXT]"], "sc", k(24), GREEN, "CENTER", 120))}

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
