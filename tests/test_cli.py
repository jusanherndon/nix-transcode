"""Tests for the command line interface."""

# ruff: noqa: S101

from pathlib import Path

from click.testing import CliRunner

import transcode.cli as cli
import transcode.transcode as transcode_module
from transcode.cli import main
from transcode.transcode import (
    TranscodeOptions,
    build_ffmpeg_command,
    probe_video_codec,
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
    assert str(tmp_path / "movie.mkv") in command


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
                "v:0",
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
    assert str(tmp_path / "movie.mkv") in result.output


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
    """Directory waits must be at least five minutes."""
    input_file = tmp_path / "movie.mkv"
    input_file.write_text("not really video")

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--input-directory", str(tmp_path), "--wait-seconds", "299", "--dry-run"],
    )

    assert result.exit_code != 0
    assert "299 is not in the range" in result.output


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

    def fake_transcode(options: TranscodeOptions) -> int:
        transcoded_files.append(options.input_file)
        return 0

    monkeypatch.setattr(cli, "transcode", fake_transcode)
    monkeypatch.setattr(cli.time, "sleep", slept_seconds.append)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--input-directory", str(tmp_path), "--wait-seconds", "300", "--no-hwaccel"],
    )

    assert result.exit_code == 0
    assert transcoded_files == [first_file, second_file]
    assert slept_seconds == [300]
