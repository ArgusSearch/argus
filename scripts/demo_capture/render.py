"""Cut actual Mission Control recordings into the captioned 90-second agent scene."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
LENGTH = 90
SAMPLE_RATE = 48_000
FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"


def run(*command: str, capture: bool = False) -> bytes:
    return subprocess.run(command, check=True, stdout=subprocess.PIPE if capture else None).stdout or b""


def ffmpeg(*args: str, capture: bool = False) -> bytes:
    return run("ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *args, capture=capture)


def probe(media: Path) -> dict[str, Any]:
    return json.loads(
        run("ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(media), capture=True)
    )


def text_image(path: Path, text: str, size: str, points: int) -> None:
    run(
        "magick",
        "-background",
        "#071321",
        "-fill",
        "#edf6ff",
        "-font",
        FONT,
        "-pointsize",
        str(points),
        "-gravity",
        "center",
        "-size",
        size,
        f"caption:{text}",
        str(path),
    )


def srt_time(seconds: int) -> str:
    minute, second = divmod(seconds, 60)
    return f"00:{minute:02}:{second:02},000"


def voice_over(path: Path, captions: list[tuple[int, int, str]], work: Path, voice: str) -> None:
    """Place offline spoken captions exactly on the film timebase."""
    with wave.open(str(path), "wb") as output:
        output.setparams((1, 2, SAMPLE_RATE, 0, "NONE", "not compressed"))
        for index, (start, end, text) in enumerate(captions):
            speech = work / f"speech-{index}.aiff"
            run("say", "-v", voice, "-r", "165", "-o", str(speech), text)
            pcm = ffmpeg(
                "-i",
                str(speech),
                "-ar",
                str(SAMPLE_RATE),
                "-ac",
                "1",
                "-f",
                "s16le",
                "pipe:1",
                capture=True,
            )
            lead_bytes = SAMPLE_RATE // 2  # 250 ms at two bytes per sample
            span_bytes = (end - start) * SAMPLE_RATE * 2
            if len(pcm) + lead_bytes > span_bytes:
                raise ValueError(f"narration at {start}s exceeds its caption slot")
            output.writeframes(bytes(lead_bytes) + pcm + bytes(span_bytes - lead_bytes - len(pcm)))


def render(cuts_file: Path, output: Path, source: str, voice: str) -> None:
    cue_sheet = json.loads((ROOT / "docs" / "pitch" / "agent-scene.json").read_bytes())
    cuts = json.loads(cuts_file.read_bytes())
    if set(cuts) != {cue["shot"] for cue in cue_sheet}:
        raise ValueError("cuts must identify each shot in the cue sheet")
    sidecar = output.with_suffix(".srt")
    if output.suffix.lower() != ".mp4" or output.exists() or sidecar.exists():
        raise ValueError("choose a new MP4 output path")
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=".agent-scene-", dir=output.parent) as temporary:
        work = Path(temporary)
        badge = work / "source.png"
        text_image(badge, "Recorded model run" if source == "recorded" else "Live model", "320x40", 24)
        takes = []
        narration = []
        for index, cue in enumerate(cue_sheet):
            shot = cue["shot"]
            start = cue["start"]
            end = cue_sheet[index + 1]["start"] if index + 1 < len(cue_sheet) else LENGTH
            duration = end - start
            take = cuts[shot]
            media = cuts_file.parent / take["file"]
            offset = float(take["start"])
            if offset < 0 or float(probe(media)["format"]["duration"]) + 0.01 < offset + duration:
                raise ValueError(f"{shot} must contain {duration} seconds starting at {offset:g}s")
            inputs = ["-ss", str(offset), "-i", str(media), "-i", str(badge)]
            filters = [
                "[0:v]setpts=PTS-STARTPTS,fps=30,scale=1840:944:force_original_aspect_ratio=decrease:"
                "force_divisible_by=2,pad=1920:1080:(ow-iw)/2:44:color=0x071321,setsar=1[scene]",
                "[scene][1:v]overlay=40:2[badge]",
            ]
            previous = "badge"
            captions = cue["captions"]
            for caption_index, (in_point, text) in enumerate(captions):
                out_point = captions[caption_index + 1][0] if caption_index + 1 < len(captions) else duration
                narration.append((start + in_point, start + out_point, text))
                image = work / f"caption-{index}-{caption_index}.png"
                text_image(image, text, "1840x80", 32)
                inputs.extend(("-i", str(image)))
                label = f"caption{caption_index}"
                filters.append(
                    f"[{previous}][{caption_index + 2}:v]overlay=40:994:"
                    f"enable='gte(t,{in_point})*lt(t,{out_point})'[{label}]"
                )
                previous = label
            cut = work / f"{index:02}.mp4"
            ffmpeg(
                *inputs,
                "-filter_complex",
                ";".join(filters),
                "-map",
                f"[{previous}]",
                "-t",
                str(duration),
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                str(cut),
            )
            takes.append(f"file '{cut.name}'")

        listing = work / "shots.txt"
        listing.write_text("\n".join(takes) + "\n")
        voice_file = work / "narration.wav"
        voice_over(voice_file, narration, work, voice)
        rendered = work / "rendered.mp4"
        ffmpeg(
            "-f",
            "concat",
            "-safe",
            "1",
            "-i",
            str(listing),
            "-i",
            str(voice_file),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-movflags",
            "+faststart",
            str(rendered),
        )
        result = probe(rendered)
        video, audio = result["streams"]
        if (
            video["codec_name"] != "h264"
            or (video["width"], video["height"]) != (1920, 1080)
            or audio["codec_name"] != "aac"
            or any(abs(float(stream["duration"]) - LENGTH) > 1 / 30 for stream in (video, audio))
        ):
            raise ValueError("export must include 90 seconds of 1080p video and narration")
        srt = work / "captions.srt"
        srt.write_text(
            "\n".join(
                f"{index}\n{srt_time(start)} --> {srt_time(end)}\n{text}\n"
                for index, (start, end, text) in enumerate(narration, 1)
            )
        )
        rendered.rename(output)
        srt.rename(sidecar)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cuts", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source", choices=("recorded", "live"), required=True)
    parser.add_argument("--voice", default="Samantha")
    args = parser.parse_args()
    for tool in ("ffmpeg", "ffprobe", "magick", "say"):
        if not shutil.which(tool):
            parser.error(f"{tool} is required to export the film")
    try:
        render(args.cuts, args.output, args.source, args.voice)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Film export failed. {exc}\n")
    print(f"Exported {args.output} and {args.output.with_suffix('.srt')}")


if __name__ == "__main__":
    main()
