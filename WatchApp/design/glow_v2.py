"""Hisse kartı ışığı v2: daha yayvan, alt kenara yakın daha parlak, alt çizginin ortasında parlak ışın."""
import numpy as np
from PIL import Image, ImageDraw, ImageFilter


def glow_png2(w, h, below, rad, col, strength=0.35, below_k=0.30, spread=0.50, edge=1.0, beam=1.0, reach=0.85, center=1.0, plume=1.0, intensity=0.8, slit=1.0):
    q = 2; W_, H_ = w * q, (h + below) * q
    yy = np.arange(H_)[:, None].astype(np.float32); xx = np.arange(W_)[None, :].astype(np.float32)
    m = Image.new("L", (W_, H_), 0); ImageDraw.Draw(m).rounded_rectangle((0, 0, W_ - 1, h * q - 1), radius=rad * q, fill=255)
    inside = np.array(m).astype(np.float32) / 255
    hfall = np.exp(-(np.abs(xx - W_ / 2) / (W_ / 2 * spread)) ** 2.6)    # ortada geniş, kenarlara doğru hızla silikleşir
    t = np.clip((h * q - yy) / (h * q * reach), 0, 1)            # yukarı uzanma
    up = (1 - t) ** 2.2 * inside * hfall
    hot = (1 - t) ** 5 * inside * hfall                                   # alt kenara yakın parlak bant
    tb = np.clip((yy - h * q) / (below * q), 0, 1)
    down = np.where(yy > h * q, (1 - tb) ** 2, 0) * hfall
    # ortada dar ışık sütunu: yayvan ışıktan daha yukarı uzanır
    narrow = np.exp(-(np.abs(xx - W_ / 2) / (W_ / 2 * 0.30)) ** 2)
    t2 = np.clip((h * q - yy) / (h * q * 1.15), 0, 1)
    col_up = (1 - t2) ** 1.8 * inside * narrow
    # piramit: tabanda geniş, yukarı doğru simetrik daralır, tepe ortada (yayvan ışık + dar sütun yerine)
    tp = np.clip((h * q - yy) / (h * q * 1.25), 0, 1)                  # 0 alt kenar → 1 tepe
    half = (W_ / 2) * (0.68 * (1 - tp) + 0.22 * tp)              # kesik piramit: tepe düz, sivri değil
    pyr = np.exp(-(np.abs(xx - W_ / 2) / half) ** 3) * (1 - tp) ** 1.6 * inside      # net piramit hatları; yukarı doğru hızla hafifler
    a = pyr * 150 * strength * 1.25 + hot * 120 * edge + down * 150 * below_k
    lay = np.zeros((H_, W_, 4), np.float32); lay[..., :3] = col; lay[..., 3] = a
    lay[..., 3] *= intensity                                                # genel şiddet: yalnız ışık gövdesi
    img = Image.fromarray(lay.clip(0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(2 * q))
    # alt çizginin ortasında parlak ışın: dar, ince, merkezde beyaza yakın
    bw = np.exp(-((xx[0] - W_ / 2) / (W_ / 2 * 0.58)) ** 2)     # daha uzun ışın
    y0 = int(h * q - 2)
    beam_l = np.zeros((H_, W_, 4), np.float32)
    lite = np.array(col, np.float32) * 0.62 + 255 * 0.38          # parlak açık ton (kırmızı/yeşil)
    beam_l[..., :3] = lite          # renk tüm alanda: bulanıklık şeffaf siyahı karıştırıp ışını karartmasın
    for dy, k in ((-1, .55), (0, 1.0), (1, 1.0), (2, .55)):
        beam_l[y0 + dy, :, 3] = 255 * bw * k * beam
    halo = Image.fromarray(beam_l.clip(0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(3 * q))
    core = Image.fromarray(beam_l.clip(0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.6 * q))
    img.alpha_composite(halo); img.alpha_composite(halo); img.alpha_composite(core)
    # tam ortada çok parlak çekirdek: dar, beyaza yakın + küçük parlama
    cw = np.exp(-((xx[0] - W_ / 2) / (W_ / 2 * 0.26)) ** 2)
    hot_l = np.zeros((H_, W_, 4), np.float32)
    white = np.array(col, np.float32) * 0.5 + 255 * 0.5           # çekirdek: rengin parlak açık tonu, beyaz değil
    hot_l[..., :3] = white
    for dy, k in ((-1, .8), (0, 1.0), (1, 1.0), (2, .8)):
        hot_l[y0 + dy, :, 3] = 255 * cw * k * center
    hot_img = Image.fromarray(hot_l.clip(0, 255).astype(np.uint8))
    img.alpha_composite(hot_img.filter(ImageFilter.GaussianBlur(5 * q)))
    img.alpha_composite(hot_img.filter(ImageFilter.GaussianBlur(2 * q)))
    img.alpha_composite(hot_img.filter(ImageFilter.GaussianBlur(0.5 * q)))
    # tam ortada ince beyaz çizik (en üst katman)
    sw = np.exp(-((xx[0] - W_ / 2) / (W_ / 2 * 0.16)) ** 4)
    wl = np.zeros((H_, W_, 4), np.float32); wl[..., :3] = 255
    wl[y0, :, 3] = 255 * sw * slit; wl[y0 + 1, :, 3] = 200 * sw * slit
    img.alpha_composite(Image.fromarray(wl.clip(0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.35 * q)))
    return img.resize((w, h + below), Image.LANCZOS)
