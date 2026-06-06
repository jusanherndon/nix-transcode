"""Tests for the command line interface."""

# ruff: noqa: S101

from pathlib import Path

from click.testing import CliRunner

from transcode.cli import main
from transcode.transcode import TranscodeOptions, build_ffmpeg_command


def test_build_ffmpeg_command_defaults(tmp_path: Path) -> None:
    """The default command transcodes video and copies non-video streams."""
    input_file = tmp_path / "movie.mkv"
    input_file.write_text("not really video")

    command = build_ffmpeg_command(TranscodeOptions(input_file=input_file))

    assert "av1_qsv" in command
    assert command[command.index("-c:a") + 1] == "copy"
    assert command[command.index("-c:s") + 1] == "copy"
    assert str(tmp_path / "movie.av1.mkv") in command


def test_cli_dry_run(tmp_path: Path) -> None:
    """Dry-run prints the ffmpeg command without running it."""
    input_file = tmp_path / "movie.mkv"
    input_file.write_text("not really video")

    runner = CliRunner()
    result = runner.invoke(main, [str(input_file), "--dry-run", "--no-hwaccel"])

    assert result.exit_code == 0
    assert "ffmpeg" in result.output
    assert "av1_qsv" in result.output
    assert "-c:a copy" in result.output
    assert "-c:s copy" in result.output


def test_cli_input_file_option_dry_run(tmp_path: Path) -> None:
    """The input can be passed with --input-file instead of positionally."""
    input_file = tmp_path / "movie.mkv"
    input_file.write_text("not really video")

    runner = CliRunner()
    result = runner.invoke(main, ["--input-file", str(input_file), "--dry-run", "--no-hwaccel"])

    assert result.exit_code == 0
    assert f"-i {input_file}" in result.output
    assert str(tmp_path / "movie.av1.mkv") in result.output
