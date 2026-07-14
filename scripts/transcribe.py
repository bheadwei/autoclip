"""Transcribe a video/audio file with faster-whisper (CPU, int8), word-level timestamps.

Usage:
    uv run scripts/transcribe.py <media> [out.json] [--model medium] [--lang zh]

--lang auto  lets whisper detect the language.
Output JSON: {language, duration, segments: [{start, end, text, words: [{start, end, word}]}]}
"""
import argparse
import json
import sys

from faster_whisper import WhisperModel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("media")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--model", default="medium", help="tiny/base/small/medium/large-v3")
    ap.add_argument("--lang", default="zh")
    args = ap.parse_args()
    out_path = args.out or args.media + ".transcript.json"

    lang = None if args.lang == "auto" else args.lang
    model = WhisperModel(args.model, device="cpu", compute_type="int8")
    segments, info = model.transcribe(
        args.media,
        language=lang,
        word_timestamps=True,
        vad_filter=True,
        initial_prompt="以下是繁體中文的內容。" if lang == "zh" else None,
    )

    segs = []
    for s in segments:
        segs.append({
            "start": round(s.start, 3),
            "end": round(s.end, 3),
            "text": s.text.strip(),
            "words": [
                {"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word}
                for w in (s.words or [])
            ],
        })
        print(f"\r  transcribed up to {s.end:7.1f}s", end="", file=sys.stderr, flush=True)
    print(file=sys.stderr)

    data = {"language": info.language, "duration": round(info.duration, 3), "segments": segs}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"wrote {out_path} ({len(segs)} segments, {info.duration:.0f}s, lang={info.language})")


if __name__ == "__main__":
    main()
