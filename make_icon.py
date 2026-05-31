from PIL import Image, ImageDraw, ImageFilter
import numpy as np

DIR  = r'C:\Users\BioCSI\CLAUDE\GridTracker'
SIZE = 512

# 1. Logo arka plan - beyaz kenarı kırp, kareye doldur
logo = Image.open(f'{DIR}/logo.png').convert('RGBA')
arr  = np.array(logo)
mask = ~((arr[:,:,0]>220) & (arr[:,:,1]>220) & (arr[:,:,2]>220))
r0,r1 = np.where(np.any(mask,axis=1))[0][[0,-1]]
c0,c1 = np.where(np.any(mask,axis=0))[0][[0,-1]]
bg = logo.crop((c0,r0,c1+1,r1+1)).resize((SIZE,SIZE), Image.LANCZOS)

# 2. Cüzdan - gri arka planı kaldır
icon = Image.open(f'{DIR}/icon-192.png').convert('RGBA')
ia   = np.array(icon)
H, W = ia.shape[:2]

# Köşeden bg rengini örnekle
bg_col = ia[0,0,:3].astype(float)

# Flood-fill: sadece bg rengine yakın pikselleri kaldır (düşük tolerans = cüzdan korunur)
TOL = 32
vis  = np.zeros((H,W), bool)
is_b = np.zeros((H,W), bool)
stk  = [(r,c) for r in [0,H-1] for c in range(W)] + [(r,c) for c in [0,W-1] for r in range(H)]
for r,c in stk: vis[r,c] = True

while stk:
    r,c = stk.pop()
    if np.sqrt(((ia[r,c,:3].astype(float)-bg_col)**2).sum()) < TOL*1.73:
        is_b[r,c] = True
        for dr,dc in [(-1,0),(1,0),(0,-1),(0,1)]:
            nr,nc = r+dr, c+dc
            if 0<=nr<H and 0<=nc<W and not vis[nr,nc]:
                vis[nr,nc]=True; stk.append((nr,nc))

alpha = Image.fromarray((~is_b*255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1))
ia2 = ia.copy(); ia2[:,:,3] = np.array(alpha)
icon_clean = Image.fromarray(ia2)

# 3. Boyutlandır ve ortala
IW = int(SIZE * 0.88)
IH = int(IW * (icon.height / icon.width))
icon_big = icon_clean.resize((IW,IH), Image.LANCZOS)
ox = (SIZE-IW)//2
oy = (SIZE-IH)//2

# 4. Logo üzerine yapıştır
result = bg.copy()
result.paste(icon_big, (ox,oy), icon_big)

# 5. Yuvarlatılmış köşe
cm = Image.new('L',(SIZE,SIZE),0)
ImageDraw.Draw(cm).rounded_rectangle([0,0,SIZE-1,SIZE-1], radius=72, fill=255)
result.putalpha(cm)

out = f'{DIR}/icon-new.png'
result.save(out, 'PNG')
print(f'Kaydedildi: {out}')
