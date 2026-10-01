"""Build and run ffmpeg-python-package jobs for Intel QSV AV1 transcoding."""

from __future__ import annotations

import json
import shlex
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from ffmpeg.errors import FFmpegError
from ffmpeg.ffmpeg import FFmpeg

from transcode.quality import check_quality

TRANSCODED_PREFIX = "transcoded_"
DEFAULT_LOG_LEVEL = "verbose"
# Decoder, vpp_qsv, and av1_qsv share one Quick Sync frame pool. veryslow
# keeps several frames in flight, and the default pool runs out after a few
# frames, which stalls the encoder while audio keeps going.
QSV_EXTRA_HW_FRAMES = 64
FFMPEG_LOG_LEVELS = (
    "quiet",
    "panic",
    "fatal",
    "error",
    "warning",
    "info",
    "verbose",
    "debug",
    "trace",
)


def parse_bitrate(value: str) -> int:
    """Parse a bitrate like ``6M``, ``6000k``, or ``6000000`` into bits/sec."""
    text = value.strip().lower().replace(" ", "")
    if not text:
        msg = "bitrate must not be empty"
        raise ValueError(msg)
    try:
        if text.endswith("m"):
            return int(float(text[:-1]) * 1_000_000)
        if text.endswith("k"):
            return int(float(text[:-1]) * 1_000)
        return int(text)
    except ValueError as exc:
        msg = f"invalid bitrate: {value!r}"
        raise ValueError(msg) from exc


@dataclass(frozen=True, slots=True)
class TranscodeOptions:
    """Options used to create an ffmpeg transcode command."""

    input_file: Path
    output_file: Path | None = None
    quality: int = 20
    bitrate: int | None = None
    maxrate: int | None = None
    preset: str = "veryslow"
    hwaccel: bool = True
    overwrite: bool = False
    check_quality: bool = True
    check_vmaf: bool = False
    quality_threads: int | None = None
    log_level: str = DEFAULT_LOG_LEVEL
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
    video_codec: str | None = None
    video_codecs: tuple[str, ...] | None = None
    audio_codecs: tuple[str, ...] | None = None
    subtitle_codecs: tuple[str, ...] | None = None

    def resolved_output(self) -> Path:
        """Return the requested output path, defaulting to a Matroska file."""
        if self.output_file is not None:
            return self.output_file
        return self.input_file.with_name(
            f"{TRANSCODED_PREFIX}{self.input_file.stem}.mkv"
        )


def probe_stream_codecs(
    input_file: Path, stream_selector: str, ffprobe_bin: str = "ffprobe"
) -> tuple[str, ...]:
    """Return stream codec names reported by ffprobe for a stream selector."""
    ffprobe = FFmpeg(executable=ffprobe_bin)
    ffprobe.option("v", "error")
    ffprobe.option("select_streams", stream_selector)
    ffprobe.option("show_entries", "stream=codec_name")
    ffprobe.option("of", "json")
    ffprobe.input(str(input_file))

    streams = json.loads(ffprobe.execute().decode()).get("streams", [])
    return tuple(
        codec.lower()
        for stream in streams
        if isinstance((codec := stream.get("codec_name")), str)
    )


def probe_video_codecs(
    input_file: Path, ffprobe_bin: str = "ffprobe"
) -> tuple[str, ...]:
    """Return all video stream codec names reported by ffprobe."""
    return probe_stream_codecs(input_file, "v", ffprobe_bin)


def probe_video_codec(input_file: Path, ffprobe_bin: str = "ffprobe") -> str | None:
    """Return the first video stream codec name reported by ffprobe."""
    codecs = probe_video_codecs(input_file, ffprobe_bin)
    return codecs[0] if codecs else None


def probe_audio_codecs(
    input_file: Path, ffprobe_bin: str = "ffprobe"
) -> tuple[str, ...]:
    """Return all audio stream codec names reported by ffprobe."""
    return probe_stream_codecs(input_file, "a", ffprobe_bin)


def probe_subtitle_codecs(
    input_file: Path, ffprobe_bin: str = "ffprobe"
) -> tuple[str, ...]:
    """Return all subtitle stream codec names reported by ffprobe."""
    return probe_stream_codecs(input_file, "s", ffprobe_bin)


def options_with_probed_codec(
    options: TranscodeOptions, *, strict: bool = True
) -> TranscodeOptions:
    """Return options populated with the input video codec from ffprobe."""
    if (
        options.video_codec is not None
        and options.video_codecs is not None
        and options.audio_codecs is not None
        and options.subtitle_codecs is not None
    ):
        return options
    try:
        video_codecs = options.video_codecs
        if video_codecs is None:
            if options.video_codec is None:
                video_codecs = probe_video_codecs(
                    options.input_file, options.ffprobe_bin
                )
            else:
                video_codecs = (options.video_codec,)
        video_codec = options.video_codec
        if video_codec is None:
            video_codec = primary_video_codec(video_codecs)
        audio_codecs = options.audio_codecs
        if audio_codecs is None:
            audio_codecs = probe_audio_codecs(options.input_file, options.ffprobe_bin)
        subtitle_codecs = options.subtitle_codecs
        if subtitle_codecs is None:
            subtitle_codecs = probe_subtitle_codecs(
                options.input_file, options.ffprobe_bin
            )
    except (OSError, FFmpegError, json.JSONDecodeError):
        if strict:
            raise
        return options
    return replace(
        options,
        video_codec=video_codec,
        video_codecs=video_codecs,
        audio_codecs=audio_codecs,
        subtitle_codecs=subtitle_codecs,
    )


def video_streams_to_drop(video_codecs: tuple[str, ...] | None) -> tuple[int, ...]:
    """Return video stream indexes that should be dropped from the output."""
    if video_codecs is None or video_codecs.count("mjpeg") != 1:
        return ()
    return tuple(index for index, codec in enumerate(video_codecs) if codec == "mjpeg")


def primary_video_codec(video_codecs: tuple[str, ...] | None) -> str | None:
    """Return the codec of the first video stream that will be kept."""
    if not video_codecs:
        return None
    dropped_indexes = set(video_streams_to_drop(video_codecs))
    return next(
        (
            codec
            for index, codec in enumerate(video_codecs)
            if index not in dropped_indexes
        ),
        video_codecs[0],
    )


def output_map_options(video_codecs: tuple[str, ...] | None) -> str | list[str]:
    """Return ffmpeg map options, excluding droppable video streams."""
    dropped_video_streams = video_streams_to_drop(video_codecs)
    if not dropped_video_streams:
        return "0"
    return ["0", *(f"-0:v:{index}" for index in dropped_video_streams)]


def audio_codec_options(audio_codecs: tuple[str, ...] | None) -> dict[str, str]:
    """Return ffmpeg codec options for all audio streams."""
    if not audio_codecs:
        return {"c:a": "copy"}
    return {
        f"c:a:{index}": "copy" if codec in {"ac3", "aac", "opus"} else "aac"
        for index, codec in enumerate(audio_codecs)
    }


BITMAP_SUBTITLE_CODECS = {
    "dvb_subtitle",
    "dvd_subtitle",
    "hdmv_pgs_subtitle",
    "xsub",
}


def subtitle_codec_options(subtitle_codecs: tuple[str, ...] | None) -> dict[str, str]:
    """Return ffmpeg codec options for all subtitle streams."""
    if not subtitle_codecs:
        return {"c:s": "copy"}
    return {
        f"c:s:{index}": "copy"
        if codec in {"ass", "ssa"} or codec in BITMAP_SUBTITLE_CODECS
        else "ass"
        for index, codec in enumerate(subtitle_codecs)
    }


def media_stream_codec_options_all_copy(options: TranscodeOptions) -> bool:
    """Return whether video, audio, and subtitle codec options all copy streams."""
    return (
        primary_video_codec(
            options.video_codecs
            or ((options.video_codec,) if options.video_codec else None)
        )
        == "av1"
        and all(
            value == "copy"
            for value in audio_codec_options(options.audio_codecs).values()
        )
        and all(
            value == "copy"
            for value in subtitle_codec_options(options.subtitle_codecs).values()
        )
    )


def video_rate_control_options(options: TranscodeOptions) -> dict[str, str | int]:
    """Return av1_qsv rate-control options for quality or bitrate mode."""
    if options.bitrate is not None:
        maxrate = (
            options.maxrate if options.maxrate is not None else options.bitrate * 2
        )
        return {
            "preset": options.preset,
            "b:v": options.bitrate,
            "maxrate": maxrate,
            "bufsize": options.bitrate * 4,
        }
    return {
        "preset": options.preset,
        "global_quality": options.quality,
    }


def build_ffmpeg(options: TranscodeOptions) -> FFmpeg:
    """Build a python-ffmpeg ``FFmpeg`` job for Matroska-to-AV1/QSV transcoding.

    The job uses Intel Quick Sync Video's AV1 encoder (``av1_qsv``) with the
    10-bit ``p010le`` pixel format unless the kept input video stream is already
    AV1, in which case video is copied. Hardware decoding reserves extra Quick
    Sync frames so the decoder, ``vpp_qsv``, and ``av1_qsv`` can all hold frames
    at once. AAC and Opus audio streams are copied;
    other
    audio streams are converted to Opus while preserving their channel layout
    when supported by ffmpeg/aac. Subtitle streams are copied if they are
    already SSA/ASS or bitmap-based, otherwise text subtitles are converted to
    ASS. Each audio and subtitle stream gets an explicit codec option so every
    mapped stream is preserved. It keeps all streams from the source file
    (``-map 0``), except for an MJPEG video stream when it is paired with one
    other video stream. It copies attachment streams without re-encoding,
    preserves metadata and chapters, and writes a Matroska
    container.
    """
    ffmpeg = FFmpeg(executable=options.ffmpeg_bin)
    ffmpeg.option("hide_banner")
    ffmpeg.option("loglevel", options.log_level)
    ffmpeg.option("y" if options.overwrite else "n")

    video_codecs = options.video_codecs or (
        (options.video_codec,) if options.video_codec else None
    )
    copy_video = primary_video_codec(video_codecs) == "av1"
    input_options = {}
    if options.hwaccel and not copy_video:
        input_options = {
            "hwaccel": "qsv",
            "hwaccel_output_format": "qsv",
            "extra_hw_frames": QSV_EXTRA_HW_FRAMES,
        }

    ffmpeg.input(str(options.input_file), input_options)
    output_options = {
        "map": output_map_options(video_codecs),
        "map_metadata": "0",
        "map_chapters": "0",
        "c:v": "copy" if copy_video else "av1_qsv",
        **audio_codec_options(options.audio_codecs),
        **subtitle_codec_options(options.subtitle_codecs),
        "c:t": "copy",
        "f": "matroska",
    }
    if not copy_video:
        output_options.update(video_rate_control_options(options))
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


def display_transcode_command(
    options: TranscodeOptions,
    *,
    display_options: TranscodeOptions | None = None,
) -> str:
    """Return the shell-escaped ffmpeg command for a transcode job."""
    resolved = display_options or options_with_probed_codec(options, strict=False)
    return format_command(build_ffmpeg_command(resolved))


def _emit(output: Callable[[str], None] | None, message: str) -> None:
    """Send a log line to the caller, or to stderr when no callback is set."""
    if output is not None:
        output(message)
        return
    print(message, file=sys.stderr)


def _ffmpeg_returncode(ffmpeg: FFmpeg | None) -> int | None:
    """Return the ffmpeg process exit status, when the process was started."""
    if ffmpeg is None:
        return None
    process = getattr(ffmpeg, "_process", None)
    returncode = getattr(process, "returncode", None)
    if isinstance(returncode, int):
        return returncode
    return None


def _failure_message(exc: FFmpegError, returncode: int | None) -> str:
    """Return a failure line that includes the process status when known."""
    detail = exc.message or "ffmpeg exited with an error"
    if returncode is None:
        return f"ffmpeg failed: {detail}"
    if returncode < 0:
        return f"ffmpeg failed (signal {-returncode}): {detail}"
    return f"ffmpeg failed (exit {returncode}): {detail}"


def transcode(
    options: TranscodeOptions,
    *,
    output: Callable[[str], None] | None = None,
) -> int:
    """Run the python-ffmpeg job and return a process-like exit code.

    ffmpeg stderr is forwarded as it arrives. Failures include the ffmpeg
    error text.
    """
    output_file = options.resolved_output()
    if options.input_file.resolve() == output_file.resolve():
        msg = "input and output paths must be different"
        raise ValueError(msg)

    output_existed = output_file.exists()
    ffmpeg: FFmpeg | None = None
    try:
        ffmpeg = build_ffmpeg(options_with_probed_codec(options))
        ffmpeg.on("stderr", lambda line: _emit(output, line))
        ffmpeg.execute()
    except FFmpegError as exc:
        _emit(output, _failure_message(exc, _ffmpeg_returncode(ffmpeg)))
        if output_file.exists() and (options.overwrite or not output_existed):
            output_file.unlink()
        return 1
    return 0


def transcode_with_quality_check(
    options: TranscodeOptions,
    *,
    output: Callable[[str], None] | None = None,
) -> int:
    """Run a Transcode job, then optionally score the output against the input."""
    exit_code = transcode(options, output=output)
    if exit_code != 0:
        return exit_code

    if output is not None:
        output("Transcode done.")

    if not options.check_quality:
        return exit_code

    if output is not None:
        output("Calculating quality metrics...")

    quality_exit_code, summary = check_quality(
        options.input_file,
        options.resolved_output(),
        include_vmaf=options.check_vmaf,
        threads=options.quality_threads,
        ffmpeg_bin=options.ffmpeg_bin,
    )
    if output is not None:
        output(summary)
    return quality_exit_code
