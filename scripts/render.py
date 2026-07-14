"""Cut highlight clips from a video and burn subtitles built from word-level
whisper timestamps, plus animated onomatopoeia (SFX) captions.

Usage:
    uv run scripts/render.py <video> <transcript.json> <clips.json> <outdir> [--vertical]

clips.json is a list of clips; each clip is either a single range or multiple parts:
    [
      {"slug": "hook", "title": "...", "start": 12.5, "end": 42.0},
      {"slug": "multi", "title": "...", "parts": [[60.0, 75.5], [120.0, 141.0]],
       "sfx": [{"start": 62.0, "end": 64.5, "text": "哇啊啊！", "x": 0.5, "y": 0.28,
                "angle": -8, "scale": 1.3}]}
    ]

sfx times are in SOURCE seconds; x/y are fractions of frame size (anchor center);
they pop in with a scale-overshoot animation.
--vertical crops to 9:16 (center) and outputs 1080x1920.
Multi-part clips are rendered per part then concatenated (captions stay in sync).
"""
import argparse
import json
import os
import subprocess

import ffutil

MAX_LINE_CHARS = 10   # zh chars per subtitle line (short-video style)
MAX_GAP = 0.8         # start a new line after a pause this long (seconds)

FONTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts")

# Per-job overrides live in jobs/<name>/job.json under "style".
DEFAULT_STYLE = {
    "dialog_font": "GenSenRounded2 TW B",
    "sfx_font": "GenSenRounded2 TW H",
    "outline": 0,      # px at 1080p; 0 = shadow-only look
    "shadow": 4,
    "fontsize": 88,    # dialog size at PlayResY=1920 (vertical)
    "sfx_size": 130,
}


def hex2ass(h: str) -> str:
    h = h.lstrip("#")
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}&".upper()


def ass_header(vertical: bool, style: dict) -> str:
    w, h = (1080, 1920) if vertical else (1920, 1080)
    k = h / 1920 if vertical else h / 1080
    fontsize = int(style["fontsize"] * k)
    sfx_size = int(style["sfx_size"] * k)
    margin_v = 420 if vertical else 110
    common = (f"&H00FFFFFF,&H00FFFFFF,&H00000000,&H50000000,-1,0,0,0,100,100,0,0,1,"
              f"{style['outline']},{style['shadow']}")
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{style['dialog_font']},{fontsize},{common},2,60,60,{margin_v},1
Style: Sfx,{style['sfx_font']},{sfx_size},{common},5,20,20,20,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def ts(sec: float) -> str:
    sec = max(sec, 0.0)
    h = int(sec // 3600)
    m = int(sec % 3600 // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def words_in_range(transcript: dict, start: float, end: float) -> list:
    out = []
    for seg in transcript["segments"]:
        if seg["end"] < start or seg["start"] > end:
            continue
        for w in seg["words"]:
            mid = (w["start"] + w["end"]) / 2
            if start <= mid <= end:
                out.append(w)
    return out


def chunk_lines(words: list) -> list:
    """Group words into short subtitle lines: break on pauses or length."""
    lines, cur, chars = [], [], 0
    for w in words:
        text = w["word"].strip()
        if not text:
            continue
        if cur and (chars + len(text) > MAX_LINE_CHARS or w["start"] - cur[-1]["end"] > MAX_GAP):
            lines.append(cur)
            cur, chars = [], 0
        cur.append(w)
        chars += len(text)
    if cur:
        lines.append(cur)
    return lines


def dialog_events(words: list, offset: float) -> list:
    events = []
    for line in chunk_lines(words):
        start, end = line[0]["start"] - offset, line[-1]["end"] - offset + 0.15
        text = "".join(w["word"].strip() for w in line)
        events.append(f"Dialogue: 0,{ts(start)},{ts(end)},Cap,,0,0,0,,{text}")
    return events


def sfx_events(sfx_list: list, part_start: float, part_end: float, vertical: bool, style: dict) -> list:
    w, h = (1080, 1920) if vertical else (1920, 1080)
    events = []
    for s in sfx_list or []:
        mid = (s["start"] + s["end"]) / 2
        if not (part_start <= mid <= part_end):
            continue
        st = max(s["start"], part_start) - part_start
        en = min(s["end"], part_end) - part_start
        x, y = int(s.get("x", 0.5) * w), int(s.get("y", 0.28) * h)
        angle = s.get("angle", 0)
        scale = s.get("scale", 1.0)
        fs = int(style["sfx_size"] * (h / 1920 if vertical else h / 1080) * scale)
        color = f"\\c{hex2ass(s['color'])}" if s.get("color") else ""
        font = f"\\fn{s['font']}" if s.get("font") else ""
        # pop-in: small -> overshoot -> settle
        tags = (f"{{\\an5\\pos({x},{y})\\frz{angle}\\fs{fs}{font}{color}\\fad(60,120)"
                f"\\fscx40\\fscy40\\t(0,110,\\fscx135\\fscy135)\\t(110,200,\\fscx100\\fscy100)}}")
        events.append(f"Dialogue: 1,{ts(st)},{ts(en)},Sfx,,0,0,0,,{tags}{s['text']}")
    return events


def render_part(video, transcript, sfx, start, end, ass_path, out_path, vertical, style):
    words = words_in_range(transcript, start, end)
    events = dialog_events(words, offset=start) + sfx_events(sfx, start, end, vertical, style)
    with open(ass_path, "w", encoding="utf-8-sig") as f:
        f.write(ass_header(vertical, style))
        f.write("\n".join(events) + "\n")
    outdir = os.path.dirname(os.path.abspath(out_path))
    fontsdir = os.path.relpath(FONTS_DIR, outdir).replace("\\", "/")
    vf = f"ass={os.path.basename(ass_path)}:fontsdir={fontsdir}"
    if vertical:
        vf = f"crop=ih*9/16:ih,scale=1080:1920,{vf}"
    subprocess.run(
        [
            ffutil.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
            "-ss", str(start), "-to", str(end), "-i", os.path.abspath(video),
            "-vf", vf,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "160k",
            os.path.basename(out_path),
        ],
        check=True,
        cwd=outdir,  # relative ass=/fontsdir= paths avoid Windows drive-colon filter escaping
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("transcript")
    ap.add_argument("clips")
    ap.add_argument("outdir")
    ap.add_argument("--vertical", action="store_true")
    args = ap.parse_args()

    with open(args.transcript, encoding="utf-8") as f:
        transcript = json.load(f)
    with open(args.clips, encoding="utf-8") as f:
        clips = json.load(f)
    os.makedirs(args.outdir, exist_ok=True)

    style = dict(DEFAULT_STYLE)
    job_path = os.path.join(os.path.dirname(os.path.abspath(args.clips)), "job.json")
    if os.path.isfile(job_path):
        with open(job_path, encoding="utf-8") as f:
            style.update(json.load(f).get("style") or {})

    for clip in clips:
        slug = clip["slug"]
        parts = clip.get("parts") or [[clip["start"], clip["end"]]]
        part_files = []
        for i, (s, e) in enumerate(parts):
            suffix = f"_p{i + 1}" if len(parts) > 1 else ""
            out = os.path.join(args.outdir, f"{slug}{suffix}.mp4")
            render_part(args.video, transcript, clip.get("sfx"), s, e,
                        os.path.join(args.outdir, f"{slug}{suffix}.ass"), out, args.vertical, style)
            part_files.append(out)

        final = os.path.join(args.outdir, f"{slug}.mp4")
        if len(part_files) > 1:
            list_path = os.path.join(args.outdir, f"{slug}_concat.txt")
            with open(list_path, "w", encoding="utf-8") as f:
                for p in part_files:
                    f.write(f"file '{os.path.basename(p)}'\n")
            subprocess.run(
                [ffutil.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
                 "-f", "concat", "-safe", "0", "-i", os.path.basename(list_path),
                 "-c", "copy", os.path.basename(final)],
                check=True, cwd=os.path.abspath(args.outdir),
            )
        dur = sum(e - s for s, e in parts)
        print(f"{final}  ({dur:.1f}s, {len(parts)} part(s))")


if __name__ == "__main__":
    main()
