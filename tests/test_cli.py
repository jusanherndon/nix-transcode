"""Tests for the command line interface."""

# ruff: noqa: S101

from pathlib import Path

from click.testing import CliRunner
from ffmpeg.errors import FFmpegError

import transcode.cli as cli
import transcode.directory_run as directory_run
import transcode.transcode as transcode_module
from transcode.cli import main
from transcode.transcode import (
    TranscodeOptions,
    build_ffmpeg_command,
    probe_audio_codecs,
    probe_subtitle_codecs,
    probe_video_codec,
    probe_video_codecs,
)


def test_build_ffmpeg_command_defaults(tmp_path: Path) -> None:
    """The default command transcodes video and copies non-video streams."""
    input_file = tmp_path / "movie.mkv"
    input_file.write_text("not really video")

    command = build_ffmpeg_command(TranscodeOptions(input_file=input_file))

    assert "av1_qsv" in command
    assert command[command.index("-vf") + 1] == "vpp_qsv=format=p010le"
    assert command[command.index("-c:a") + 1] == "copy"
    assert command[command.index("-c:s") + 1] == "copy"
    assert command[command.index("-global_quality") + 1] == "20"
    assert command[command.index("-extbrc") + 1] == "1"
    assert command[command.index("-look_ahead_depth") + 1] == "40"
    assert command[command.index("-extra_hw_frames") + 1] == "40"
    assert "-b:v" not in command
    assert "-max_muxing_queue_size" not in command
    assert str(tmp_path / "transcoded_movie.mkv") in command


def test_build_ffmpeg_command_disables_look_ahead(tmp_path: Path) -> None:
    """Look-ahead ExtBRC options can be turned off."""
    input_file = tmp_path / "movie.mkv"
    input_file.write_text("not really video")

    command = build_ffmpeg_command(
        TranscodeOptions(input_file=input_file, look_ahead=False)
    )

    assert "-extbrc" not in command
    assert "-look_ahead_depth" not in command
    assert "-extra_hw_frames" not in command


def test_build_ffmpeg_command_bitrate_mode(tmp_path: Path) -> None:
    """Bitrate mode uses VBR options instead of global_quality."""
    input_file = tmp_path / "movie.mkv"
    input_file.write_text("not really video")

    command = build_ffmpeg_command(
        TranscodeOptions(input_file=input_file, bitrate=6_000_000)
    )

    assert command[command.index("-b:v") + 1] == "6000000"
    assert command[command.index("-maxrate") + 1] == "12000000"
    assert command[command.index("-bufsize") + 1] == "24000000"
    assert command[command.index("-extbrc") + 1] == "1"
    assert "-global_quality" not in command


def test_build_ffmpeg_command_bitrate_with_maxrate(tmp_path: Path) -> None:
    """An explicit maxrate overrides the default 2x peak."""
    input_file = tmp_path / "movie.mkv"
    input_file.write_text("not really video")

    command = build_ffmpeg_command(
        TranscodeOptions(input_file=input_file, bitrate=6_000_000, maxrate=8_000_000)
    )

    assert command[command.index("-b:v") + 1] == "6000000"
    assert command[command.index("-maxrate") + 1] == "8000000"
    assert command[command.index("-bufsize") + 1] == "24000000"
    assert "-global_quality" not in command


def test_parse_bitrate() -> None:
    """Bitrate strings with k/M suffixes parse to bits per second."""
    from transcode.transcode import parse_bitrate

    assert parse_bitrate("6M") == 6_000_000
    assert parse_bitrate("6000k") == 6_000_000
    assert parse_bitrate("6000000") == 6_000_000


def test_cli_bitrate_dry_run(tmp_path: Path) -> None:
    """--bitrate switches the dry-run command into VBR mode."""
    input_file = tmp_path / "movie.mkv"
    input_file.write_text("not really video")

    runner = CliRunner()
    result = runner.invoke(
        main,
        [str(input_file), "--bitrate", "6M", "--dry-run", "--no-hwaccel"],
    )

    assert result.exit_code == 0
    assert "-b:v 6000000" in result.output
    assert "-maxrate 12000000" in result.output
    assert "-global_quality" not in result.output


def test_cli_maxrate_requires_bitrate(tmp_path: Path) -> None:
    """--maxrate alone is rejected."""
    input_file = tmp_path / "movie.mkv"
    input_file.write_text("not really video")

    runner = CliRunner()
    result = runner.invoke(main, [str(input_file), "--maxrate", "8M", "--dry-run"])

    assert result.exit_code != 0
    assert "--maxrate requires --bitrate" in result.output


def test_build_ffmpeg_command_copies_av1_video(tmp_path: Path) -> None:
    """AV1 inputs copy the video stream instead of re-encoding it."""
    input_file = tmp_path / "movie.mkv"
    input_file.write_text("not really video")

    command = build_ffmpeg_command(
        TranscodeOptions(input_file=input_file, video_codec="av1")
    )

    assert command[command.index("-c:v") + 1] == "copy"
    assert "av1_qsv" not in command
    assert "-vf" not in command
    assert "-pix_fmt" not in command


def test_build_ffmpeg_command_copies_aac_and_opus_audio(tmp_path: Path) -> None:
    """AAC and Opus audio streams are copied without re-encoding."""
    input_file = tmp_path / "movie.mkv"
    input_file.write_text("not really video")

    command = build_ffmpeg_command(
        TranscodeOptions(input_file=input_file, audio_codecs=("ac3", "opus"))
    )

    assert command[command.index("-c:a:0") + 1] == "copy"
    assert command[command.index("-c:a:1") + 1] == "copy"


def test_build_ffmpeg_command_converts_other_audio_to_opus(tmp_path: Path) -> None:
    """Non-AAC/Opus audio streams are converted to Opus."""
    input_file = tmp_path / "movie.mkv"
    input_file.write_text("not really video")

    command = build_ffmpeg_command(
        TranscodeOptions(input_file=input_file, audio_codecs=("dts", "ac3"))
    )

    assert command[command.index("-c:a:0") + 1] == "aac"
    assert command[command.index("-c:a:1") + 1] == "copy"


def test_build_ffmpeg_command_converts_non_ass_subtitles(tmp_path: Path) -> None:
    """Non-SSA/ASS subtitle streams are converted to ASS."""
    input_file = tmp_path / "movie.mkv"
    input_file.write_text("not really video")

    command = build_ffmpeg_command(
        TranscodeOptions(input_file=input_file, subtitle_codecs=("subrip",))
    )

    assert command[command.index("-c:s:0") + 1] == "ass"


def test_build_ffmpeg_command_copies_ass_subtitles(tmp_path: Path) -> None:
    """SSA/ASS subtitle streams are copied."""
    input_file = tmp_path / "movie.mkv"
    input_file.write_text("not really video")

    command = build_ffmpeg_command(
        TranscodeOptions(input_file=input_file, subtitle_codecs=("ssa", "ass"))
    )

    assert command[command.index("-c:s:0") + 1] == "copy"
    assert command[command.index("-c:s:1") + 1] == "copy"


def test_build_ffmpeg_command_copies_bitmap_subtitles(tmp_path: Path) -> None:
    """Bitmap subtitle streams are copied because ffmpeg cannot encode them as ASS."""
    input_file = tmp_path / "movie.mkv"
    input_file.write_text("not really video")

    command = build_ffmpeg_command(
        TranscodeOptions(
            input_file=input_file,
            subtitle_codecs=("hdmv_pgs_subtitle", "dvd_subtitle"),
        )
    )

    assert command[command.index("-c:s:0") + 1] == "copy"
    assert command[command.index("-c:s:1") + 1] == "copy"


def test_build_ffmpeg_command_preserves_multiple_mixed_subtitles(
    tmp_path: Path,
) -> None:
    """Every subtitle stream gets an explicit copy-or-convert codec option."""
    input_file = tmp_path / "movie.mkv"
    input_file.write_text("not really video")

    command = build_ffmpeg_command(
        TranscodeOptions(input_file=input_file, subtitle_codecs=("ass", "subrip"))
    )

    assert command[command.index("-map") + 1] == "0"
    assert command[command.index("-c:s:0") + 1] == "copy"
    assert command[command.index("-c:s:1") + 1] == "ass"


def test_probe_video_codec(tmp_path: Path, monkeypatch) -> None:
    """Ffprobe JSON is parsed into a lowercase codec name."""
    input_file = tmp_path / "movie.mkv"
    input_file.write_text("not really video")

    class FakeFFmpeg:
        def __init__(self, executable: str) -> None:
            assert executable == "ffprobe"
            self.arguments = [executable]

        def option(self, key: str, value: str) -> None:
            self.arguments.extend([f"-{key}", value])

        def input(self, path: str) -> None:
            assert path == str(input_file)
            self.arguments.extend(["-i", path])

        def execute(self) -> bytes:
            assert self.arguments == [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v",
                "-show_entries",
                "stream=codec_name",
                "-of",
                "json",
                "-i",
                str(input_file),
            ]
            return b'{"streams":[{"codec_name":"AV1"}]}'

    monkeypatch.setattr(transcode_module, "FFmpeg", FakeFFmpeg)

    assert probe_video_codec(input_file) == "av1"


def test_probe_video_codecs(tmp_path: Path, monkeypatch) -> None:
    """Ffprobe video JSON is parsed into all lowercase codec names."""
    input_file = tmp_path / "movie.mkv"
    input_file.write_text("not really video")

    class FakeFFmpeg:
        def __init__(self, executable: str) -> None:
            assert executable == "ffprobe"
            self.arguments = [executable]

        def option(self, key: str, value: str) -> None:
            self.arguments.extend([f"-{key}", value])

        def input(self, path: str) -> None:
            assert path == str(input_file)
            self.arguments.extend(["-i", path])

        def execute(self) -> bytes:
            assert "-select_streams" in self.arguments
            assert self.arguments[self.arguments.index("-select_streams") + 1] == "v"
            return b'{"streams":[{"codec_name":"H264"},{"codec_name":"MJPEG"}]}'

    monkeypatch.setattr(transcode_module, "FFmpeg", FakeFFmpeg)

    assert probe_video_codecs(input_file) == ("h264", "mjpeg")


def test_build_ffmpeg_command_drops_mjpeg_when_two_video_streams(
    tmp_path: Path,
) -> None:
    """An MJPEG sidecar video stream is omitted when another video stream exists."""
    input_file = tmp_path / "movie.mkv"
    input_file.write_text("not really video")

    command = build_ffmpeg_command(
        TranscodeOptions(input_file=input_file, video_codecs=("h264", "mjpeg"))
    )

    map_positions = [index for index, value in enumerate(command) if value == "-map"]
    assert command[map_positions[0] + 1] == "0"
    assert command[map_positions[1] + 1] == "-0:v:1"
    assert command[command.index("-c:v") + 1] == "av1_qsv"


def test_build_ffmpeg_command_copies_av1_and_drops_mjpeg(
    tmp_path: Path,
) -> None:
    """Dropping MJPEG still lets an AV1 primary stream be copied."""
    input_file = tmp_path / "movie.mkv"
    input_file.write_text("not really video")

    command = build_ffmpeg_command(
        TranscodeOptions(input_file=input_file, video_codecs=("mjpeg", "av1"))
    )

    map_positions = [index for index, value in enumerate(command) if value == "-map"]
    assert command[map_positions[1] + 1] == "-0:v:0"
    assert command[command.index("-c:v") + 1] == "copy"
    assert "av1_qsv" not in command


def test_probe_audio_codecs(tmp_path: Path, monkeypatch) -> None:
    """Ffprobe audio JSON is parsed into lowercase codec names."""
    input_file = tmp_path / "movie.mkv"
    input_file.write_text("not really video")

    class FakeFFmpeg:
        def __init__(self, executable: str) -> None:
            assert executable == "ffprobe"
            self.arguments = [executable]

        def option(self, key: str, value: str) -> None:
            self.arguments.extend([f"-{key}", value])

        def input(self, path: str) -> None:
            assert path == str(input_file)
            self.arguments.extend(["-i", path])

        def execute(self) -> bytes:
            assert "-select_streams" in self.arguments
            assert self.arguments[self.arguments.index("-select_streams") + 1] == "a"
            return b'{"streams":[{"codec_name":"AAC"},{"codec_name":"DTS"}]}'

    monkeypatch.setattr(transcode_module, "FFmpeg", FakeFFmpeg)

    assert probe_audio_codecs(input_file) == ("aac", "dts")


def test_probe_subtitle_codecs(tmp_path: Path, monkeypatch) -> None:
    """Ffprobe subtitle JSON is parsed into lowercase codec names."""
    input_file = tmp_path / "movie.mkv"
    input_file.write_text("not really video")

    class FakeFFmpeg:
        def __init__(self, executable: str) -> None:
            assert executable == "ffprobe"
            self.arguments = [executable]

        def option(self, key: str, value: str) -> None:
            self.arguments.extend([f"-{key}", value])

        def input(self, path: str) -> None:
            assert path == str(input_file)
            self.arguments.extend(["-i", path])

        def execute(self) -> bytes:
            assert "-select_streams" in self.arguments
            assert self.arguments[self.arguments.index("-select_streams") + 1] == "s"
            return b'{"streams":[{"codec_name":"SubRip"},{"codec_name":"ASS"}]}'

    monkeypatch.setattr(transcode_module, "FFmpeg", FakeFFmpeg)

    assert probe_subtitle_codecs(input_file) == ("subrip", "ass")


def test_cli_dry_run(tmp_path: Path) -> None:
    """Dry-run prints the ffmpeg command without running it."""
    input_file = tmp_path / "movie.mkv"
    input_file.write_text("not really video")

    runner = CliRunner()
    result = runner.invoke(main, [str(input_file), "--dry-run", "--no-hwaccel"])

    assert result.exit_code == 0
    assert "ffmpeg" in result.output
    assert "av1_qsv" in result.output
    assert "-pix_fmt p010le" in result.output
    assert "-c:a copy" in result.output
    assert "-c:s copy" in result.output


def test_cli_input_file_option_dry_run(tmp_path: Path) -> None:
    """The input can be passed with --input-file instead of positionally."""
    input_file = tmp_path / "movie.mkv"
    input_file.write_text("not really video")

    runner = CliRunner()
    result = runner.invoke(
        main, ["--input-file", str(input_file), "--dry-run", "--no-hwaccel"]
    )

    assert result.exit_code == 0
    assert f"-i {input_file}" in result.output
    assert str(tmp_path / "transcoded_movie.mkv") in result.output


def test_cli_input_directory_dry_run(tmp_path: Path) -> None:
    """A directory input builds one command per regular, non-transcoded file."""
    first_file = tmp_path / "a.mkv"
    second_file = tmp_path / "b.mkv"
    previous_output = tmp_path / "transcoded_old.mkv"
    nested_dir = tmp_path / "nested"
    for input_file in (first_file, second_file, previous_output):
        input_file.write_text("not really video")
    nested_dir.mkdir()

    runner = CliRunner()
    result = runner.invoke(
        main, ["--input-directory", str(tmp_path), "--dry-run", "--no-hwaccel"]
    )

    assert result.exit_code == 0
    assert f"-i {first_file}" in result.output
    assert f"-i {second_file}" in result.output
    assert str(tmp_path / "transcoded_a.mkv") in result.output
    assert str(tmp_path / "transcoded_b.mkv") in result.output
    assert "transcoded_old" not in result.output


def test_cli_input_directory_wait_seconds_minimum(tmp_path: Path) -> None:
    """Directory waits must be at least the default cooldown."""
    input_file = tmp_path / "movie.mkv"
    input_file.write_text("not really video")

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--input-directory", str(tmp_path), "--wait-seconds", "149", "--dry-run"],
    )

    assert result.exit_code != 0
    assert "149 is not in the range" in result.output


def test_cli_input_directory_waits_between_transcodes(
    tmp_path: Path, monkeypatch
) -> None:
    """Directory transcodes sleep between successful jobs."""
    first_file = tmp_path / "a.mkv"
    second_file = tmp_path / "b.mkv"
    for input_file in (first_file, second_file):
        input_file.write_text("not really video")
    slept_seconds: list[int] = []
    transcoded_files: list[Path] = []

    def fake_transcode(options: TranscodeOptions, output=None) -> int:
        transcoded_files.append(options.input_file)
        return 0

    monkeypatch.setattr(directory_run, "transcode_with_quality_check", fake_transcode)
    monkeypatch.setattr(cli.time, "sleep", slept_seconds.append)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--input-directory", str(tmp_path), "--wait-seconds", "300", "--no-hwaccel"],
    )

    assert result.exit_code == 0
    assert transcoded_files == [first_file, second_file]
    assert slept_seconds == [300]
