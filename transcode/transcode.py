"""Build and run ffmpeg-python-package jobs for Intel QSV AV1 transcoding."""

from __future__ import annotations

import json
import shlex
from collections.abc import Sequence
from dataclasses import dataclass, replace
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
    ffprobe_bin: str = "ffprobe"
    video_codec: str | None = None

    def resolved_output(self) -> Path:
        """Return the requested output path, defaulting to a Matroska file."""
        if self.output_file is not None:
            return self.output_file
        return self.input_file.with_name(f"{self.input_file.stem}.mkv")


def probe_video_codec(input_file: Path, ffprobe_bin: str = "ffprobe") -> str | None:
    """Return the first video stream codec name reported by ffprobe."""
    ffprobe = FFmpeg(executable=ffprobe_bin)
    ffprobe.option("v", "error")
    ffprobe.option("select_streams", "v:0")
    ffprobe.option("show_entries", "stream=codec_name")
    ffprobe.option("of", "json")
    ffprobe.input(str(input_file))

    streams = json.loads(ffprobe.execute().decode()).get("streams", [])
    if not streams:
        return None
    codec = streams[0].get("codec_name")
    return codec.lower() if isinstance(codec, str) else None


def options_with_probed_codec(
    options: TranscodeOptions, *, strict: bool = True
) -> TranscodeOptions:
    """Return options populated with the input video codec from ffprobe."""
    if options.video_codec is not None:
        return options
    try:
        video_codec = probe_video_codec(options.input_file, options.ffprobe_bin)
    except (OSError, FFmpegError, json.JSONDecodeError):
        if strict:
            raise
        return options
    return replace(options, video_codec=video_codec)


def build_ffmpeg(options: TranscodeOptions) -> FFmpeg:
    """Build a python-ffmpeg ``FFmpeg`` job for Matroska-to-AV1/QSV transcoding.

    The job uses Intel Quick Sync Video's AV1 encoder (``av1_qsv``) with the
    10-bit ``p010le`` pixel format unless the input video stream is already AV1,
    in which case video is copied. It keeps all streams from the source file
    (``-map 0``), copies audio, subtitle, and attachment streams without
    re-encoding, preserves metadata and chapters, and writes a Matroska
    container.
    """
    ffmpeg = FFmpeg(executable=options.ffmpeg_bin)
    ffmpeg.option("hide_banner")
    ffmpeg.option("y" if options.overwrite else "n")

    copy_video = options.video_codec == "av1"
    input_options = {}
    if options.hwaccel and not copy_video:
        input_options = {"hwaccel": "qsv", "hwaccel_output_format": "qsv"}

    ffmpeg.input(str(options.input_file), input_options)
    output_options = {
        "map": "0",
        "map_metadata": "0",
        "map_chapters": "0",
        "c:v": "copy" if copy_video else "av1_qsv",
        "c:a": "copy",
        "c:s": "copy",
        "c:t": "copy",
        "f": "matroska",
        "max_muxing_queue_size": "4096",
    }
    if not copy_video:
        output_options.update(
            {
                "preset": options.preset,
                "global_quality": options.quality,
                "b:v": "0",
            }
        )
        if options.hwaccel:
            output_options["vf"] = "vpp_qsv=format=p010le"
        else:
            output_options["pix_fmt"] = "p010le"

    ffmpeg.output(str(options.resolved_output()), output_options)
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

    output_existed = output_file.exists()
    try:
        build_ffmpeg(options_with_probed_codec(options)).execute()
    except FFmpegError:
        if output_file.exists() and (options.overwrite or not output_existed):
            output_file.unlink()
        return 1
    return 0
