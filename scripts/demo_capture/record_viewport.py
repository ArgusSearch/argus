"""Record the selected, local Argus tab through Chrome DevTools AXI."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit


def check_browser() -> None:
    if not os.environ.get("CHROME_DEVTOOLS_AXI_SESSION"):
        raise ValueError("select an isolated CHROME_DEVTOOLS_AXI_SESSION")
    completed = subprocess.run(
        ["chrome-devtools-axi", "run"],
        input="console.log(JSON.stringify(await page.eval(() => [location.href, document.title])));",
        text=True,
        capture_output=True,
        check=True,
        timeout=20,
    )
    url, title = json.loads(completed.stdout)
    parsed = urlsplit(url)
    host = parsed.hostname
    local = host == "localhost" or bool(host and ipaddress.ip_address(host).is_loopback)
    if not local or not title.startswith("Argus"):
        raise ValueError("open the local Mission Control tab before recording")


def record(output: Path, seconds: float, fps: float) -> int:
    if output.exists() or output.suffix not in {".mp4", ".mov"}:
        raise ValueError("choose a new MP4 or MOV filepath")
    check_browser()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".argus-capture-", dir=output.parent) as scratch:
        work = Path(scratch)
        opening = time.monotonic()
        frames: list[tuple[Path, float]] = []
        while (elapsed := time.monotonic() - opening) < seconds:
            frame = work / f"frame-{len(frames):05d}.jpeg"
            subprocess.run(
                ["chrome-devtools-axi", "screenshot", str(frame), "--format", "jpeg"],
                stdout=subprocess.DEVNULL,
                check=True,
                timeout=15,
            )
            if not frame.is_file():
                raise ValueError("DevTools did not write its viewport frame")
            frames.append((frame, elapsed))
            remaining = min(seconds, elapsed + 1 / fps) - (time.monotonic() - opening)
            time.sleep(max(remaining, 0))
        if len(frames) < 2:
            raise ValueError("browser did not supply enough frames")
        sequence = work / "frames.txt"
        pts = [0.0, *(instant for _, instant in frames[1:]), seconds]
        sequence.write_text(
            "".join(
                f"file '{frame.name}'\nduration {end - start:.6f}\n"
                for (frame, _), start, end in zip(frames, pts[:-1], pts[1:], strict=True)
            )
            + f"file '{frames[-1][0].name}'\n"
        )
        movie = work / output.name
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-f",
                "concat",
                "-safe",
                "1",
                "-i",
                str(sequence),
                "-vf",
                "fps=30,scale=trunc(iw/2)*2:trunc(ih/2)*2",
                "-t",
                str(seconds),
                "-an",
                "-c:v",
                "libx264",
                "-crf",
                "17",
                "-pix_fmt",
                "yuv420p",
                str(movie),
            ],
            check=True,
        )
        movie.rename(output)
        return len(frames)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--seconds", type=float, required=True)
    parser.add_argument("--fps", type=float, default=10.0, help="maximum screenshot sampling rate")
    args = parser.parse_args()
    if not 2 <= args.seconds <= 180 or not 1 <= args.fps <= 30:
        parser.error("use 2 to 180 seconds at 1 to 30 screenshots per second")
    try:
        frames = record(args.output, args.seconds, args.fps)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"Viewport capture failed. {exc}\n")
    print(f"Saved {args.output} from {frames} real viewport frames")


if __name__ == "__main__":
    main()
