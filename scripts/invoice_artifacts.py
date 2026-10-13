#!/usr/bin/env python3
"""Prepare local CAPTCHA views and export an official page capture; no OCR/network."""
import argparse
import json
import os
import shutil
from pathlib import Path


def emit(value):
    print(json.dumps(value, ensure_ascii=False))


class JsonParser(argparse.ArgumentParser):
    def error(self, message):
        emit({"error": message, "usage": self.format_usage().strip()})
        raise SystemExit(2)

    def print_help(self, file=None):
        emit({"help": self.format_help()})


def load_screenshot(path):
    from PIL import Image

    with Image.open(path) as image:
        if image.format not in {"PNG", "JPEG"}:
            raise ValueError("Input must be a PNG or JPEG screenshot (detected from its bytes).")
        source_format = image.format
        image.load()
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, "white")
        return Image.alpha_composite(background, rgba).convert("RGB"), source_format


def reserve_paths(directory, names):
    """Reserve coordinated names exclusively, advancing the suffix on collisions."""
    directory.mkdir(parents=True, exist_ok=True)
    index = 1
    while True:
        suffix = "" if index == 1 else f"-{index}"
        paths = [directory / f"{Path(name).stem}{suffix}{Path(name).suffix}" for name in names]
        created = []
        try:
            for path in paths:
                os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
                created.append(path)
            return paths
        except FileExistsError:
            for path in created:
                path.unlink()
            index += 1
        except Exception:
            for path in created:
                path.unlink()
            raise


def captcha(args):
    from PIL import Image

    if not 1 <= args.scale <= 32:
        raise ValueError("Scale must be an integer from 1 to 32.")
    source = args.input.expanduser().resolve()
    image, source_format = load_screenshot(source)
    if image.width * image.height * args.scale ** 2 > 100_000_000:
        raise ValueError("Enlarged image exceeds 100 million pixels; use a smaller scale or crop.")
    pixels = []
    retained = 0
    source_pixels = image.get_flattened_data() if hasattr(image, "get_flattened_data") else image.getdata()
    for r, g, b in source_pixels:
        if args.color == "red":
            keep = r >= 80 and r - max(g, b) >= 25 and r >= 1.2 * max(g, b)
        elif args.color == "blue":
            keep = b >= 80 and b - max(r, g) >= 25 and b >= 1.2 * max(r, g)
        elif args.color == "black":
            keep = max(r, g, b) <= 180 and max(r, g, b) - min(r, g, b) <= 60
        else:
            keep = True
        retained += int(keep)
        pixels.append((r, g, b) if keep else (255, 255, 255))
    filtered = Image.new("RGB", image.size)
    filtered.putdata(pixels)
    usable = sum(min(pixel) < 245 for pixel in pixels) if args.color == "all" else retained
    size = (image.width * args.scale, image.height * args.scale)
    source_name = "source.png" if source_format == "PNG" else "source.jpg"
    paths = reserve_paths(args.output_dir.expanduser().resolve(), [source_name, "enlarged.png", "filtered.png"])
    try:
        shutil.copyfile(source, paths[0])
        image.resize(size, Image.Resampling.NEAREST).save(paths[1])
        filtered.resize(size, Image.Resampling.NEAREST).save(paths[2])
    except Exception:
        for path in paths:
            path.unlink(missing_ok=True)
        raise
    return {
        "source": str(paths[0]), "enlarged": str(paths[1]), "filtered": str(paths[2]),
        "source_format": source_format, "source_size": list(image.size), "output_size": list(size), "scale": args.scale,
        "color": args.color, "retained_pixels": retained,
        "retained_fraction": retained / (image.width * image.height),
        "no_usable_pixels": usable == 0,
        "warning": "No usable pixels after filtering; inspect the preserved source/enlarged view." if usable == 0 else None,
    }


def crop_image(image, value):
    try:
        x, y, width, height = map(int, value.split(","))
    except (ValueError, TypeError):
        raise ValueError("Crop must be x,y,width,height using four integers.") from None
    if min(x, y) < 0 or min(width, height) <= 0 or x + width > image.width or y + height > image.height:
        raise ValueError("Crop must have positive dimensions and stay within the input image.")
    return image.crop((x, y, x + width, y + height))


def result(args):
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas

    source = args.input.expanduser().resolve()
    image, source_format = load_screenshot(source)
    if args.crop:
        image = crop_image(image, args.crop)
    requested = args.pdf.expanduser().resolve()
    if requested.suffix.lower() != ".pdf":
        raise ValueError("Output --pdf path must end in .pdf.")
    paths = reserve_paths(requested.parent, [requested.name, requested.with_suffix(".png").name])
    page_size = landscape(A4) if image.width > image.height else A4
    try:
        image.save(paths[1])
        pdf = canvas.Canvas(str(paths[0]), pagesize=page_size)
        title = args.title or "Official invoice verification result"
        pdf.setTitle(f"{title} (页面截图版)")
        pdf.setSubject("Official website rendered page screenshot / 页面截图版")
        pdf.setAuthor("chinatax-invoice-verify")
        pdf.setCreator("Local official page screenshot exporter")
        if args.verified_at:
            pdf.setKeywords(f"verified-at: {args.verified_at}")
        font = "Helvetica"
        if any(ord(char) > 127 for char in title + (args.verified_at or "")):
            pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
            font = "STSong-Light"
        width, height = page_size
        margin = 28
        pdf.setFont(font, 12)
        pdf.drawString(margin, height - margin, title)
        pdf.setFont(font, 8)
        pdf.drawString(margin, height - margin - 15, args.verified_at or "Official website page screenshot")
        scale = min((width - 2 * margin) / image.width, (height - 2 * margin - 43) / image.height)
        drawn_width, drawn_height = image.width * scale, image.height * scale
        pdf.drawImage(ImageReader(image), (width - drawn_width) / 2, margin + 10 + (height - 2 * margin - 43 - drawn_height) / 2, width=drawn_width, height=drawn_height)
        pdf.setFont("Helvetica", 7)
        pdf.drawString(margin, 15, "Official verification page screenshot")
        pdf.showPage()
        pdf.save()
    except Exception:
        for path in paths:
            path.unlink(missing_ok=True)
        raise
    return {"pdf": str(paths[0]), "png": str(paths[1]), "source": str(source), "source_format": source_format, "image_size": list(image.size), "page": "A4 landscape" if image.width > image.height else "A4 portrait", "pages": 1, "format": "页面截图版"}


def main():
    parser = JsonParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    captcha_parser = commands.add_parser("captcha", help="Preserve, enlarge and color-filter a CAPTCHA capture.")
    captcha_parser.add_argument("--input", type=Path, required=True, help="PNG/JPEG screenshot; actual format is detected from bytes.")
    captcha_parser.add_argument("--color", choices=["red", "blue", "black", "all"], required=True)
    captcha_parser.add_argument("--output-dir", type=Path, required=True)
    captcha_parser.add_argument("--scale", type=int, default=6)
    captcha_parser.set_defaults(run=captcha)
    result_parser = commands.add_parser("result", help="Export an official page PNG as a single A4 PDF.")
    result_parser.add_argument("--input", type=Path, required=True, help="Official page PNG/JPEG screenshot; actual format is detected from bytes.")
    result_parser.add_argument("--pdf", type=Path, required=True)
    result_parser.add_argument("--crop")
    result_parser.add_argument("--title")
    result_parser.add_argument("--verified-at")
    result_parser.set_defaults(run=result)
    args = parser.parse_args()
    try:
        emit(args.run(args))
        return 0
    except Exception as error:
        emit({"error": str(error) or type(error).__name__})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
