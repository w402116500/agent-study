"""Compress interview diagrams: PNG -> WebP, then rewrite markdown refs.

Keeps the same basename so Docsify / study.html only need a suffix change.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
IMAGE_ROOT = ROOT / "大模型面试题"
MAX_WIDTH = 1280
WEBP_QUALITY = 78
WEBP_METHOD = 4


def iter_pngs(root: Path):
    for dirpath, _, files in os.walk(root):
        for name in files:
            if name.lower().endswith(".png"):
                yield Path(dirpath) / name


def compress_one(src: Path) -> tuple[int, int]:
    orig_size = src.stat().st_size
    dest = src.with_suffix(".webp")
    with Image.open(src) as im:
        im.load()
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGBA" if "A" in im.mode else "RGB")
        width, height = im.size
        if width > MAX_WIDTH:
            ratio = MAX_WIDTH / float(width)
            im = im.resize((MAX_WIDTH, max(1, int(height * ratio))), Image.Resampling.LANCZOS)
        save_kwargs = {
            "format": "WEBP",
            "quality": WEBP_QUALITY,
            "method": WEBP_METHOD,
        }
        if im.mode == "RGBA":
            save_kwargs["lossless"] = False
        im.save(dest, **save_kwargs)
    new_size = dest.stat().st_size
    if new_size >= orig_size * 0.95:
        # Rare: keep original if WebP is not actually smaller.
        dest.unlink(missing_ok=True)
        return orig_size, orig_size
    src.unlink()
    return orig_size, new_size


def rewrite_markdown_refs(root: Path) -> int:
    changed = 0
    for dirpath, _, files in os.walk(root):
        for name in files:
            if not name.lower().endswith(".md"):
                continue
            path = Path(dirpath) / name
            text = path.read_text(encoding="utf-8")
            updated = text.replace(".png)", ".webp)").replace('.png "', '.webp "')
            if updated != text:
                path.write_text(updated, encoding="utf-8")
                changed += 1
    return changed


def rewrite_study_html(path: Path) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    updated = text.replace("images/", "images/").replace("_img.png", "_img.webp")
    # also catch generic .png image markdown
    updated = updated.replace("](images/", "](images/")
    updated = updated.replace("_img.png", "_img.webp")
    if updated != text:
        path.write_text(updated, encoding="utf-8")
        return True
    return False


def main() -> int:
    pngs = list(iter_pngs(IMAGE_ROOT))
    print(f"Found {len(pngs)} PNG files under {IMAGE_ROOT}")
    before = after = 0
    converted = skipped = 0
    for i, src in enumerate(pngs, 1):
        orig, new = compress_one(src)
        before += orig
        after += new
        if orig == new:
            skipped += 1
        else:
            converted += 1
        if i % 40 == 0 or i == len(pngs):
            print(
                f"  [{i}/{len(pngs)}] converted={converted} skipped={skipped} "
                f"now {after / 1024 / 1024:.1f} MB (was {before / 1024 / 1024:.1f} MB)"
            )
    md_changed = rewrite_markdown_refs(IMAGE_ROOT)
    study_changed = rewrite_study_html(ROOT / "study.html")
    print(
        f"Done. converted={converted} skipped={skipped} "
        f"{before / 1024 / 1024:.1f} MB -> {after / 1024 / 1024:.1f} MB "
        f"({(after / before * 100) if before else 0:.1f}%)"
    )
    print(f"Markdown files rewritten: {md_changed}; study.html rewritten: {study_changed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
