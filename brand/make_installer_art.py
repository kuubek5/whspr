# make_installer_art.py — key the coral wordmark off white, then compose the
# Inno Setup wizard bitmaps from the icon + wordmark. No new generations.
from PIL import Image

CHARCOAL = (17, 19, 24)   # #111318, the icon tile background
CORAL = (255, 107, 94)    # #FF6B5E

# ---- wordmark: white backdrop -> transparent ----
wm = Image.open("kuubwave_wordmark-coral_20260916-1640.png").convert("RGBA")
px = wm.load()
w, h = wm.size
for y in range(h):
    for x in range(w):
        r, g, b, a = px[x, y]
        if r > 235 and g > 235 and b > 235:      # white paper -> clear
            px[x, y] = (r, g, b, 0)
# autocrop to the inked pixels
bbox = wm.getbbox()
wm = wm.crop(bbox)
wm.save("kuubwave_wordmark_transparent.png")
print("wordmark transparent:", wm.size)

# white version of the same wordmark (for dark backgrounds)
alpha = wm.split()[3]
white_wm = Image.new("RGBA", wm.size, (255, 255, 255, 0))
white_wm.paste((245, 246, 248, 255), (0, 0), alpha)
white_wm.save("kuubwave_wordmark_white.png")

icon = Image.open("kuubwave_master_1024.png").convert("RGBA")

def fit(img, target_w):
    ratio = target_w / img.width
    return img.resize((target_w, max(1, round(img.height * ratio))), Image.LANCZOS)

# ---- large wizard banner: 164 x 314, charcoal, icon over white wordmark ----
LW, LH = 164, 314
big = Image.new("RGBA", (LW, LH), CHARCOAL + (255,))
ic = fit(icon, 104)
big.alpha_composite(ic, ((LW - ic.width) // 2, 60))
wm_w = fit(white_wm, 132)
big.alpha_composite(wm_w, ((LW - wm_w.width) // 2, 60 + ic.height + 26))
big.convert("RGB").save("kuubwave_wizard_large.bmp")
big.convert("RGB").save("_preview_wizard_large.png")
print("wizard large:", big.size)

# ---- small wizard image: 55 x 55, icon on white header ----
SS = 55
small = Image.new("RGBA", (SS, SS), (255, 255, 255, 255))
ics = fit(icon, 55)
small.alpha_composite(ics, (0, (SS - ics.height) // 2))
small.convert("RGB").save("kuubwave_wizard_small.bmp")
small.convert("RGB").resize((165, 165), Image.NEAREST).save("_preview_wizard_small.png")
print("wizard small:", small.size)
