"""Per-edition icons for the iMPS Fault Detection desktop builds.

Every edition is the same product, so the icons share one shape (a rounded
plate with a charging bolt) and differ in the one thing that survives being
shrunk to 16 px: the plate colour.

  current   deep blue                      the line carrying the newest benchmark
  snapshot  warm amber + dark footer band  the archived 2026-09-12 snapshot
  iso       green + light inset frame       detectors with the ISO 15118 rule layers

For each edition this writes, under desktop/icons/<edition>/:

  icon.ico     7 sizes, 16-256 px   exe, installer and uninstaller (win.icon, nsis.*Icon)
  icon.png     512 px               the BrowserWindow icon = taskbar and alt-tab
                                    (main.cjs loads process.resourcesPath/icon.png)
  favicon.png  64 px                the browser-tab icon (app/public/img/favicon.png)

The artwork follows C:\\ev_fleet\\icons\\tools\\make_app_icons.py (first drawn for
the post-build patcher); this copy lives in the repository so every build can
reproduce it. Run with any Python that has Pillow:

    python desktop/icons/make_edition_icons.py
"""
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
S = 512                                   # draw large, downsample per size
EDGE = (255, 255, 255, 40)
GLYPH = (255, 255, 255, 255)
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]

THEMES = {
    # name        plate top        plate bottom    footer band      inset frame
    "current":  ((36, 106, 191), (25, 74, 138), None,           None),
    "snapshot": ((176, 118, 6),  (124, 83, 4),  (32, 24, 8),    None),
    "iso":      ((22, 150, 108), (11, 102, 72), None,           (235, 250, 244)),
}


def plate(top, bottom):
    """Rounded square with a soft vertical gradient."""
    r = int(S * 0.22)
    grad = Image.new("RGBA", (1, S))
    for y in range(S):
        f = y / (S - 1)
        grad.putpixel((0, y), tuple(
            int(top[i] + (bottom[i] - top[i]) * f) for i in range(3)) + (255,))
    grad = grad.resize((S, S))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=r, fill=255)
    return grad, mask, r


def band(im, mask, y0, y1, colour, alpha):
    strip = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(strip).rectangle([0, y0, S, y1], fill=colour + (alpha,))
    im.paste(strip, (0, 0), Image.composite(strip.split()[3], Image.new("L", (S, S), 0), mask))


def draw(theme):
    top, bottom, footer, frame = THEMES[theme]
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    grad, mask, r = plate(top, bottom)
    im.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([1, 1, S - 2, S - 2], radius=r, outline=EDGE, width=max(2, S // 128))

    # the charging bolt, one polygon so it stays crisp when shrunk
    bolt = [(0.545, 0.115), (0.265, 0.560), (0.455, 0.560), (0.395, 0.900),
            (0.700, 0.440), (0.515, 0.440), (0.615, 0.115)]
    d.polygon([(x * S, y * S) for x, y in bolt], fill=GLYPH)

    if footer:                            # archived edition: a dark footer
        h = int(S * 0.155)
        band(im, mask, S - h, S, footer, 235)
        d2 = ImageDraw.Draw(im)
        y0, y1 = S - h * 0.62, S - h * 0.38
        for i, x in enumerate((0.30, 0.47, 0.64)):   # three ticks: "an older record"
            d2.rounded_rectangle([x * S, y0, (x + 0.09) * S, y1], radius=int(h * 0.12),
                                 fill=(255, 255, 255, 190 - i * 35))
    if frame:                             # rule-layer edition: a light inset frame
        inset = int(S * 0.06)
        ImageDraw.Draw(im).rounded_rectangle(
            [inset, inset, S - 1 - inset, S - 1 - inset], radius=int(r * 0.72),
            outline=frame + (235,), width=max(3, int(S * 0.035)))
    return im


def main():
    for name in THEMES:
        out = os.path.join(HERE, name)
        os.makedirs(out, exist_ok=True)
        im = draw(name)
        im.save(os.path.join(out, "icon.ico"), format="ICO", sizes=[(s, s) for s in ICO_SIZES])
        im.save(os.path.join(out, "icon.png"))
        im.resize((64, 64), Image.LANCZOS).save(os.path.join(out, "favicon.png"))
        sizes = {f: os.path.getsize(os.path.join(out, f)) for f in ("icon.ico", "icon.png", "favicon.png")}
        print(name, sizes)


if __name__ == "__main__":
    main()
