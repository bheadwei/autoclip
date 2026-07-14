"""Locate ffmpeg/ffprobe even when the current shell's PATH hasn't been refreshed
after a winget install."""
import glob
import os
import shutil


def find(name: str) -> str:
    p = shutil.which(name)
    if p:
        return p
    patterns = [
        os.path.expandvars(rf"%LOCALAPPDATA%\Microsoft\WinGet\Links\{name}.exe"),
        os.path.expandvars(rf"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*\**\bin\{name}.exe"),
        os.path.expandvars(rf"%PROGRAMFILES%\ffmpeg*\bin\{name}.exe"),
        rf"C:\ffmpeg\bin\{name}.exe",
    ]
    for pat in patterns:
        hits = glob.glob(pat, recursive=True)
        if hits:
            return hits[0]
    raise FileNotFoundError(
        f"{name} not found. Install it first: winget install --id Gyan.FFmpeg -e"
    )


def ffmpeg() -> str:
    return find("ffmpeg")


def ffprobe() -> str:
    return find("ffprobe")
