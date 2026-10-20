"""The glyph artwork as PNGs, for the overlay.

The page gets SVG, but the overlay is Tk, which displays PNG and GIF only - and neither the app's environment
nor this plugin's vendored runtime has an SVG rasteriser (cairosvg, svglib, skia, aggdraw are all absent).
Pillow is there, so the same paths are drawn here: every cubic segment is flattened to a polyline (Pillow has
no bezier primitive), and the glyph is drawn at SUPERSAMPLE times the wanted size and downsampled, which is
what makes the strokes smooth without an anti-aliasing library.
"""
from __future__ import annotations

from PIL import Image, ImageDraw

from .glyph_art import GLYPH_ART_VERSION, GLYPHS, STROKE_WIDTH, _checked

BOX = 100.0              # the artwork's coordinate box
SUPERSAMPLE = 4          # drawn this many times larger, then downsampled with LANCZOS
CURVE_STEPS = 16         # segments per cubic; at 20 px on screen the corners are already invisible
MIN_SIZE, MAX_SIZE = 8, 512

Point = tuple[float, float]


def flatten_cubic(p0: Point, p1: Point, p2: Point, p3: Point, steps: int = CURVE_STEPS) -> list[Point]:
    """A cubic bezier as `steps` + 1 points, the endpoints kept exactly so neighbouring segments still meet."""
    out: list[Point] = []
    for i in range(steps + 1):
        t = i / steps
        u = 1.0 - t
        x = u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0]
        y = u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1]
        out.append((x, y))
    out[0], out[-1] = (float(p0[0]), float(p0[1])), (float(p3[0]), float(p3[1]))
    return out


def parse_path(d: str) -> list[Point]:
    """One subpath string as the points of its polyline. Only M, L, C and Z occur in our own artwork; anything
    else raises, because a silently mis-drawn glyph is worse than a failing test."""
    tokens = d.replace(",", " ").split()
    points: list[Point] = []
    start: Point | None = None
    i = 0
    while i < len(tokens):
        command = tokens[i]
        i += 1
        if command == "Z":
            if start is not None:
                points.append(start)
            continue
        if command not in ("M", "L", "C"):
            raise ValueError(f"unsupported path command {command!r} in {d!r}")
        count = 6 if command == "C" else 2
        numbers = [float(n) for n in tokens[i:i + count]]
        if len(numbers) != count:
            raise ValueError(f"{command} needs {count} numbers in {d!r}")
        i += count
        if command == "C":
            here = points[-1] if points else (0.0, 0.0)
            points.extend(flatten_cubic(here, (numbers[0], numbers[1]), (numbers[2], numbers[3]),
                                        (numbers[4], numbers[5]))[1:])
        else:
            points.append((numbers[0], numbers[1]))
            if command == "M":
                start = (numbers[0], numbers[1])
    return points


def glyph_png(index: int, size: int) -> Image.Image:
    """One glyph as a transparent RGBA image of `size` x `size`, strokes in white (the overlay tints nothing,
    so white is what its dark background wants)."""
    if not isinstance(size, int) or isinstance(size, bool) or not MIN_SIZE <= size <= MAX_SIZE:
        raise ValueError(f"glyph size {size!r} is not {MIN_SIZE}..{MAX_SIZE}")
    big = size * SUPERSAMPLE
    scale = big / BOX
    image = Image.new("RGBA", (big, big), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    width = max(1, round(STROKE_WIDTH * scale))
    for subpath in GLYPHS[_checked(index)]:
        points = [(x * scale, y * scale) for x, y in parse_path(subpath)]
        if len(points) > 1:
            draw.line(points, fill=(255, 255, 255, 255), width=width, joint="curve")
        elif points:                       # a single M is a dot (the Face's eyes, the Voxel's mark)
            x, y = points[0]
            draw.ellipse((x - width / 2, y - width / 2, x + width / 2, y + width / 2),
                         fill=(255, 255, 255, 255))
    return image.resize((size, size), Image.LANCZOS)
