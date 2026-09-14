"""Генератор иконки интеграции Smart Osmos.

Капля воды с тремя горизонтальными полосами — ступенями очистки.
Рисуется с четырёхкратным суперсэмплингом, поэтому края выходят гладкими.
"""

import math

from PIL import Image, ImageDraw, ImageFont

SS = 4  # коэффициент суперсэмплинга
TOP = (0x0D, 0x47, 0xA1)  # глубокий синий — вершина капли
BOTTOM = (0x4F, 0xC3, 0xF7)  # светлый голубой — низ капли


def _quad(p0, p1, p2, n=48):
    """Точки квадратичной кривой Безье."""
    return [
        (
            (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
            (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1],
        )
        for t in (i / n for i in range(n + 1))
    ]


def droplet(cx, cy, r, h, steps=360):
    """Контур капли: скруглённая вершина, выгнутые бока и нижняя дуга.

    Прямые касательные дали бы силуэт географической булавки, поэтому бока
    слегка выгнуты наружу, а самый кончик скруглён.
    """
    beta = math.degrees(math.acos(r / h))
    a1, a2 = -90 + beta, 270 - beta
    tip_r = r * 0.14  # радиус скругления кончика
    apex_y = cy - h + tip_r
    bow = r * 0.10  # насколько бока выгнуты наружу

    right = (cx + r * math.cos(math.radians(a1)), cy + r * math.sin(math.radians(a1)))
    left = (cx + r * math.cos(math.radians(a2)), cy + r * math.sin(math.radians(a2)))

    pts = []
    # скруглённая вершина
    for i in range(25):
        a = math.radians(180 + 180 * i / 24)
        pts.append((cx + tip_r * math.cos(a), apex_y + tip_r * math.sin(a)))
    # правый бок вниз
    mid = ((pts[-1][0] + right[0]) / 2 + bow, (pts[-1][1] + right[1]) / 2)
    pts += _quad(pts[-1], mid, right)
    # нижняя дуга
    n = int(steps * (a2 - a1) / 360)
    for i in range(n + 1):
        a = math.radians(a1 + (a2 - a1) * i / n)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    # левый бок вверх
    mid = ((left[0] + pts[0][0]) / 2 - bow, (left[1] + pts[0][1]) / 2)
    pts += _quad(left, mid, pts[0])
    return pts


def render(size):
    """Нарисовать квадратную иконку заданного размера."""
    s = size * SS
    cx, r = s / 2, s * 0.325
    cy = s * 0.660
    h = r * 1.95

    # Маска капли и вертикальный градиент под ней.
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).polygon(droplet(cx, cy, r, h), fill=255)

    grad = Image.new("RGB", (1, s))
    top_y, bottom_y = cy - h, cy + r
    for y in range(s):
        t = min(1.0, max(0.0, (y - top_y) / (bottom_y - top_y)))
        grad.putpixel(
            (0, y),
            tuple(round(a + (b - a) * t) for a, b in zip(TOP, BOTTOM, strict=True)),
        )
    grad = grad.resize((s, s))

    icon = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    icon.paste(grad, (0, 0), mask)

    # Три ступени очистки — светлые полосы поперёк широкой части капли.
    bands = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bands)
    band_h = r * 0.185
    for i, offset in enumerate((-0.52, -0.02, 0.48)):
        y = cy + r * offset
        half = math.sqrt(max(r * r - (y - cy) ** 2, 0)) * 0.82 if y > cy else r * 0.80
        alpha = 245 - i * 18
        bd.rounded_rectangle(
            [cx - half, y - band_h / 2, cx + half, y + band_h / 2],
            radius=band_h / 2,
            fill=(255, 255, 255, alpha),
        )
    bands.putalpha(
        Image.composite(bands.getchannel("A"), Image.new("L", (s, s), 0), mask)
    )
    icon = Image.alpha_composite(icon, bands)

    return icon.resize((size, size), Image.LANCZOS)


def logo(short_side, font_path, dark=False):
    """Горизонтальный логотип: иконка плюс название, обрезанный по содержимому.

    brands требует минимум пустого места по краям, поэтому холст берётся с
    запасом, а затем обрезается по непрозрачным пикселям и масштабируется так,
    чтобы короткая сторона была ровно short_side.
    """
    h = short_side * 2
    img = Image.new("RGBA", (h * 4, h), (0, 0, 0, 0))
    icon = render(h)
    img.paste(icon, (0, 0), icon)
    font = ImageFont.truetype(font_path, int(h * 0.31))
    d = ImageDraw.Draw(img)
    x = int(h * 1.02)
    top = (0xE3, 0xF2, 0xFD, 255) if dark else (0x0D, 0x47, 0xA1, 255)
    d.text((x, h * 0.31), "SMART", font=font, fill=top, anchor="lm")
    d.text((x, h * 0.69), "OSMOS", font=font, fill=(0x29, 0xB6, 0xF6, 255), anchor="lm")

    img = img.crop(img.getbbox())
    scale = short_side / min(img.size)
    return img.resize(
        (round(img.width * scale), round(img.height * scale)), Image.LANCZOS
    )


def main():
    """Собрать все четыре файла в каталоге brands/."""
    import argparse
    import pathlib

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--font",
        default="Roboto-Bold.ttf",
        help="TTF для надписи на логотипе (по умолчанию Roboto-Bold.ttf рядом)",
    )
    parser.add_argument(
        "--out",
        default=str(pathlib.Path(__file__).resolve().parent.parent / "brands"),
        help="куда положить файлы",
    )
    args = parser.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    render(256).save(out / "icon.png")
    render(512).save(out / "icon@2x.png")
    logo(256, args.font).save(out / "logo.png")
    logo(512, args.font).save(out / "logo@2x.png")
    # Надпись тёмно-синим теряется на тёмной теме — для неё отдельный вариант.
    logo(256, args.font, dark=True).save(out / "dark_logo.png")
    logo(512, args.font, dark=True).save(out / "dark_logo@2x.png")
    print(f"Файлы записаны в {out}")


if __name__ == "__main__":
    main()
