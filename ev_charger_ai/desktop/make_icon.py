"""Draw desktop/icon.ico for the shortcut. Run once; needs Pillow."""
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "icon.ico")

BG = (16, 23, 28, 255)        # slate, the dashboard's dark ground
EDGE = (42, 52, 58, 255)
BOLT = (57, 135, 229, 255)    # accent blue
DOT = (250, 178, 25, 255)     # status amber - "something needs a look"
S = 512                       # draw big, downsample for each size


def draw():
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    r = int(S * 0.22)
    d.rounded_rectangle([0, 0, S - 1, S - 1], radius=r, fill=BG, outline=EDGE,
                        width=max(2, S // 96))
    # a charging bolt, drawn as one polygon so it stays crisp when shrunk
    w, h = S, S
    bolt = [(0.56, 0.10), (0.27, 0.55), (0.45, 0.55), (0.39, 0.90),
            (0.71, 0.43), (0.52, 0.43), (0.62, 0.10)]
    d.polygon([(x * w, y * h) for x, y in bolt], fill=BOLT)
    # alert badge: the reason this is a monitoring app and not a charger logo
    cx, cy, rad = 0.785 * w, 0.215 * h, 0.115 * w
    d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=BG)
    d.ellipse([cx - rad * 0.68, cy - rad * 0.68, cx + rad * 0.68, cy + rad * 0.68],
              fill=DOT)
    return im


def main():
    im = draw()
    sizes = [16, 24, 32, 48, 64, 128, 256]
    im.save(OUT, format="ICO",
            sizes=[(s, s) for s in sizes])
    im.resize((256, 256), Image.LANCZOS).save(
        os.path.join(HERE, "icon.png"), format="PNG")
    print("wrote", OUT, os.path.getsize(OUT), "bytes;", len(sizes), "sizes")


if __name__ == "__main__":
    main()
