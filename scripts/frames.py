"""Extract keyframes and tile them into timestamp-labeled contact sheets,
so an LLM can scan the whole video's visuals with a few image reads.

Usage:
    uv run scripts/frames.py <video> <outdir> [--interval 4] [--cols 4] [--rows 4]

Frame N (1-based) is sampled at ~(N-1)*interval seconds. Each cell is labeled
with its timestamp. Sheets are written as <outdir>/sheet_001.jpg, ...
"""
import argparse
import glob
import os
import subprocess

from PIL import Image, ImageDraw, ImageFont

import ffutil

CELL_W = 320


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("outdir")
    ap.add_argument("--interval", type=float, default=4.0, help="seconds between frames")
    ap.add_argument("--cols", type=int, default=4)
    ap.add_argument("--rows", type=int, default=4)
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    raw_dir = os.path.join(args.outdir, "_raw")
    os.makedirs(raw_dir, exist_ok=True)
    for old in glob.glob(os.path.join(raw_dir, "f_*.jpg")):
        os.remove(old)

    subprocess.run(
        [
            ffutil.ffmpeg(), "-hide_banner", "-loglevel", "error",
            "-i", args.video,
            "-vf", f"fps=1/{args.interval},scale={CELL_W}:-2",
            "-q:v", "4",
            os.path.join(raw_dir, "f_%05d.jpg"),
        ],
        check=True,
    )

    frames = sorted(glob.glob(os.path.join(raw_dir, "f_*.jpg")))
    if not frames:
        raise SystemExit("no frames extracted")

    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 22)
    except OSError:
        font = ImageFont.load_default()

    cell_h = Image.open(frames[0]).height
    per_sheet = args.cols * args.rows
    n_sheets = (len(frames) + per_sheet - 1) // per_sheet

    for s in range(n_sheets):
        sheet = Image.new("RGB", (CELL_W * args.cols, cell_h * args.rows), "black")
        draw = ImageDraw.Draw(sheet)
        for i, path in enumerate(frames[s * per_sheet:(s + 1) * per_sheet]):
            idx = s * per_sheet + i
            t = idx * args.interval
            label = f"{int(t // 60):02d}:{int(t % 60):02d}"
            x, y = (i % args.cols) * CELL_W, (i // args.cols) * cell_h
            sheet.paste(Image.open(path), (x, y))
            draw.rectangle([x, y, x + 78, y + 30], fill="black")
            draw.text((x + 6, y + 4), label, fill="yellow", font=font)
        out = os.path.join(args.outdir, f"sheet_{s + 1:03d}.jpg")
        sheet.save(out, quality=85)
        print(out)

    print(f"{len(frames)} frames -> {n_sheets} sheets, interval={args.interval}s")


if __name__ == "__main__":
    main()
