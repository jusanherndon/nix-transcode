"""Build and run ffmpeg-python-package jobs for Intel QSV AV1 transcoding."""

from __future__ import annotations

import shlex
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ffmpeg.errors import FFmpegError
from ffmpeg.ffmpeg import FFmpeg


@dataclass(frozen=True, slots=True)
class TranscodeOptions:
    """Options used to create an ffmpeg transcode command."""

    input_file: Path
    output_file: Path | None = None
    quality: int = 18
    preset: str = "slow"
    hwaccel: bool = True
    overwrite: bool = False
    ffmpeg_bin: str = "ffmpeg"

    def resolved_output(self) -> Path:
        """Return the requested output path, defaulting to a Matroska file."""
        if self.output_file is not None:
            return self.output_file
        return self.input_file.with_name(f"{self.input_file.stem}.mkv")


def build_ffmpeg(options: TranscodeOptions) -> FFmpeg:
    """Build a python-ffmpeg ``FFmpeg`` job for Matroska-to-AV1/QSV transcoding.

    The job uses Intel Quick Sync Video's AV1 encoder (``av1_qsv``) with the
    10-bit ``p010le`` pixel format, keeps all streams from the source file
    (``-map 0``), copies audio, subtitle, and attachment streams without
    re-encoding, preserves metadata and chapters, and writes a Matroska
    container.
    """
    ffmpeg = FFmpeg(executable=options.ffmpeg_bin)
    ffmpeg.option("hide_banner")
    ffmpeg.option("y" if options.overwrite else "n")

    input_options = {}
    if options.hwaccel:
        input_options = {"hwaccel": "qsv", "hwaccel_output_format": "qsv"}

    ffmpeg.input(str(options.input_file), input_options)
    ffmpeg.output(
        str(options.resolved_output()),
        {
            "map": "0",
            "map_metadata": "0",
            "map_chapters": "0",
            "c:v": "av1_qsv",
            "pix_fmt": "p010le",
            "preset": options.preset,
            "global_quality": options.quality,
            "b:v": "0",
            "c:a": "copy",
            "c:s": "copy",
            "c:t": "copy",
            "f": "matroska",
            "max_muxing_queue_size": "4096",
        },
    )
    return ffmpeg


def build_ffmpeg_command(options: TranscodeOptions) -> Sequence[str]:
    """Build an ffmpeg argv list from the python-ffmpeg job for display."""
    return build_ffmpeg(options).arguments


def format_command(command: Sequence[str]) -> str:
    """Return a shell-escaped command string for display."""
    return shlex.join(command)


def transcode(options: TranscodeOptions) -> int:
    """Run the python-ffmpeg job and return a process-like exit code."""
    output_file = options.resolved_output()
    if options.input_file.resolve() == output_file.resolve():
        msg = "input and output paths must be different"
        raise ValueError(msg)

    try:
        build_ffmpeg(options).execute()
    except FFmpegError:
        return 1
    return 0
