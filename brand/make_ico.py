# make_ico.py — turn the coral KuubWave master PNG into a production app icon:
# tight-crop the squircle off its white backdrop, round the corners to
# transparency, and emit a clean 1024 master plus a multi-resolution .ico.
from PIL import Image, ImageDraw
import os

SRC = "kuubwave_appicon-coral_20260916-1632.png"
OUT_MASTER = "kuubwave_master_1024.png"
OUT_ICO = "kuubwave.ico"
ICO_SIZES = [256, 128, 64, 48, 32, 16]

im = Image.open(SRC).convert("RGBA")
w, h = im.size
px = im.load()

# --- find the dark squircle's bounding box (everything that isn't near-white) ---
def is_bg(r, g, b):
    return r > 235 and g > 235 and b > 235

minx, miny, maxx, maxy = w, h, 0, 0
step = 2  # sample every 2px — plenty at this resolution, ~4x faster
for y in range(0, h, step):
    for x in range(0, w, step):
        r, g, b, a = px[x, y]
        if not is_bg(r, g, b):
            if x < minx: minx = x
            if y < miny: miny = y
            if x > maxx: maxx = x
            if y > maxy: maxy = y

# square the box around its centre so the mark stays centred
bw, bh = maxx - minx, maxy - miny
side = max(bw, bh)
cx, cy = (minx + maxx) // 2, (miny + maxy) // 2
half = side // 2
# pull the box ~1.2% inward so the pale anti-alias ring left by the white
# backdrop gets trimmed off the straight edges (the rounded mask handles corners)
inset = int(side * 0.012)
left, top = cx - half + inset, cy - half + inset
side -= inset * 2
crop = im.crop((left, top, left + side, top + side)).convert("RGBA")

# supersample the rounded-corner mask for smooth edges, then downscale
S = 4
n = crop.size[0]
mask = Image.new("L", (n * S, n * S), 0)
d = ImageDraw.Draw(mask)
radius = int(n * S * 0.2237)  # iOS-style squircle corner
d.rounded_rectangle([0, 0, n * S - 1, n * S - 1], radius=radius, fill=255)
mask = mask.resize((n, n), Image.LANCZOS)
crop.putalpha(mask)

master = crop.resize((1024, 1024), Image.LANCZOS)
master.save(OUT_MASTER)
print("master:", OUT_MASTER, master.size)

# .ico with each size rendered from the 1024 master (crisper than one embedded bitmap)
imgs = [master.resize((s, s), Image.LANCZOS) for s in ICO_SIZES]
imgs[0].save(OUT_ICO, format="ICO", sizes=[(s, s) for s in ICO_SIZES],
             append_images=imgs[1:])
print("ico:", OUT_ICO, os.path.getsize(OUT_ICO), "bytes", ICO_SIZES)
