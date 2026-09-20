# build_icons.py — turn the three approved 2K logo sources into every icon the
# app and installer need. Run from the brand/ folder:
#   python build_icons.py
#
# Sources (2K squircle renders):
#   dark tile   — the app/tray identity on near-black
#   light tile  — the same mark on off-white (installer wizard, light contexts)
#   tray glyph  — a simplified bold 'k' that stays legible at 16px
#
# Outputs (written next to this script, in brand/):
#   kuubwave_master_1024.png / kuubwave_master_light_1024.png
#   kuubwave.ico (dark, multi-size)  / kuubwave_light.ico
#   kuubwave_tray.png (rounded, for the system tray)
#   kuubwave_wizard_large.bmp (164x314) / kuubwave_wizard_small.bmp (55x55)
# The caller (or make step) copies kuubwave.ico + kuubwave_tray.png to the repo
# root, where flow._icon_path / the spec / the exe icon look for them.
from PIL import Image, ImageDraw
import os

HERE = os.path.dirname(os.path.abspath(__file__))

DARK = "kuubwave_logo-final-c2_2k_20260920-1245.png"
LIGHT = "kuubwave_logo-final-c2-light_2k_20260920-1250.png"
TRAY = "kuubwave_tray-glyph_20260920-1255.png"

ICO_SIZES = [256, 128, 64, 48, 32, 16]
RADIUS_FRAC = 0.2237          # iOS-style squircle corner
LIGHT_BG = (251, 247, 245)    # #FBF7F5 — the app's light theme surface


def _load(name):
    return Image.open(os.path.join(HERE, name)).convert("RGBA")


def rounded(im, size):
    """Square-fit to `size` and round the corners to transparency (supersampled
    mask for clean edges). The sources are already centred squircles, so a plain
    square resize keeps the mark centred."""
    im = im.resize((size, size), Image.LANCZOS)
    S = 4
    mask = Image.new("L", (size * S, size * S), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size * S - 1, size * S - 1],
        radius=int(size * S * RADIUS_FRAC), fill=255)
    im.putalpha(mask.resize((size, size), Image.LANCZOS))
    return im


def save_ico(master1024, out):
    imgs = [master1024.resize((s, s), Image.LANCZOS) for s in ICO_SIZES]
    imgs[0].save(os.path.join(HERE, out), format="ICO",
                 sizes=[(s, s) for s in ICO_SIZES], append_images=imgs[1:])
    print("ico:", out)


def save_png(im, out):
    im.save(os.path.join(HERE, out))
    print("png:", out)


def wizard_bmp(logo, w, h, out):
    """Inno modern-wizard image: RGB BMP (no alpha), logo centred on the light
    surface so it blends with the wizard's pane."""
    canvas = Image.new("RGB", (w, h), LIGHT_BG)
    side = int(min(w, h) * 0.72)
    mark = logo.resize((side, side), Image.LANCZOS)
    canvas.paste(mark, ((w - side) // 2, (h - side) // 2), mark)
    canvas.save(os.path.join(HERE, out), format="BMP")
    print("bmp:", out)


def main():
    dark = _load(DARK)
    light = _load(LIGHT)
    tray = _load(TRAY)

    dark_master = rounded(dark, 1024)
    light_master = rounded(light, 1024)
    tray_master = rounded(tray, 1024)

    save_png(dark_master, "kuubwave_master_1024.png")
    save_png(light_master, "kuubwave_master_light_1024.png")
    save_png(tray_master, "kuubwave_tray.png")

    save_ico(dark_master, "kuubwave.ico")
    save_ico(light_master, "kuubwave_light.ico")

    # rounded light mark on the light surface for the wizard art (BMP = no alpha,
    # so it must sit on a real background, not transparency)
    wizard_bmp(light_master, 164, 314, "kuubwave_wizard_large.bmp")
    wizard_bmp(light_master, 55, 55, "kuubwave_wizard_small.bmp")


if __name__ == "__main__":
    main()
