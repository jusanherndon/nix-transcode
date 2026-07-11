"""Tests for Directory transcode run orchestration."""

# ruff: noqa: S101

from dataclasses import replace
from pathlib import Path

import transcode.directory_run as directory_run
from transcode.directory_run import (
    DirectoryTranscodeSettings,
    TranscodeJob,
    run_directory_transcode,
)
from transcode.transcode import TranscodeOptions, build_ffmpeg_command


def test_directory_and_single_file_jobs_build_same_ffmpeg_command(
    tmp_path: Path,
) -> None:
    """Directory and single-file jobs share the same ffmpeg option builder."""
    input_file = tmp_path / "movie.mkv"
    input_file.write_text("not really video")
    output_file = tmp_path / "transcoded_movie.mkv"
    settings = DirectoryTranscodeSettings(
        quality=16,
        preset="medium",
        hwaccel=False,
        overwrite=True,
    )
    single_file_options = TranscodeOptions(
        input_file=input_file,
        output_file=output_file,
        quality=settings.quality,
        preset=settings.preset,
        hwaccel=settings.hwaccel,
        overwrite=settings.overwrite,
        video_codec="h264",
        audio_codecs=("dts", "aac"),
        subtitle_codecs=("subrip", "ass"),
    )
    directory_options = TranscodeJob(
        input_file=input_file,
        output_file=output_file,
        settings=settings,
    ).to_options()
    directory_options = replace(
        directory_options,
        video_codec=single_file_options.video_codec,
        audio_codecs=single_file_options.audio_codecs,
        subtitle_codecs=single_file_options.subtitle_codecs,
    )

    assert build_ffmpeg_command(single_file_options) == build_ffmpeg_command(
        directory_options
    )


def test_directory_transcode_run_reports_no_eligible_input_files(
    tmp_path: Path,
) -> None:
    """Dry-run and real runs share the same no-files result."""
    (tmp_path / "transcoded_old.mkv").write_text("not really video")
    (tmp_path / "nested").mkdir()

    result = run_directory_transcode(
        tmp_path,
        DirectoryTranscodeSettings(),
        wait_seconds=300,
        dry_run=True,
        output=lambda _line: None,
        wait=lambda _seconds: None,
    )

    assert result.status == "no_eligible_input_files"
    assert result.input_directory == tmp_path


def test_directory_transcode_run_dry_run_displays_jobs_without_waiting(
    tmp_path: Path,
) -> None:
    """Dry-run displays every Transcode job and never uses the wait adapter."""
    first_file = tmp_path / "a.mkv"
    second_file = tmp_path / "b.mkv"
    for input_file in (first_file, second_file):
        input_file.write_text("not really video")
    output_lines: list[str] = []
    waited_seconds: list[int] = []

    result = run_directory_transcode(
        tmp_path,
        DirectoryTranscodeSettings(hwaccel=False),
        wait_seconds=300,
        dry_run=True,
        output=output_lines.append,
        wait=waited_seconds.append,
    )

    assert result.status == "completed"
    assert result.jobs_attempted == 2
    assert len(output_lines) == 2
    assert f"-i {first_file}" in output_lines[0]
    assert f"-i {second_file}" in output_lines[1]
    assert waited_seconds == []


def test_directory_transcode_run_returns_failed_result(
    tmp_path: Path, monkeypatch
) -> None:
    """A failed Transcode job stops the run and returns the failing job."""
    first_file = tmp_path / "a.mkv"
    second_file = tmp_path / "b.mkv"
    for input_file in (first_file, second_file):
        input_file.write_text("not really video")
    attempted_files: list[Path] = []

    def fake_transcode(options: TranscodeOptions, output=None) -> int:
        attempted_files.append(options.input_file)
        return 7

    monkeypatch.setattr(directory_run, "transcode_with_quality_check", fake_transcode)

    result = run_directory_transcode(
        tmp_path,
        DirectoryTranscodeSettings(hwaccel=False),
        wait_seconds=300,
        dry_run=False,
        output=lambda _line: None,
        wait=lambda _seconds: None,
    )

    assert result.status == "failed"
    assert result.job.input_file == first_file
    assert result.job_index == 0
    assert result.exit_code == 7
    assert attempted_files == [first_file]


def test_directory_transcode_run_waits_between_successful_jobs(
    tmp_path: Path, monkeypatch
) -> None:
    """The wait adapter is used only between successful Transcode job values."""
    first_file = tmp_path / "a.mkv"
    second_file = tmp_path / "b.mkv"
    for input_file in (first_file, second_file):
        input_file.write_text("not really video")
    waited_seconds: list[int] = []

    monkeypatch.setattr(
        directory_run, "transcode_with_quality_check", lambda _options, output=None: 0
    )

    result = run_directory_transcode(
        tmp_path,
        DirectoryTranscodeSettings(hwaccel=False),
        wait_seconds=300,
        dry_run=False,
        output=lambda _line: None,
        wait=waited_seconds.append,
    )

    assert result.status == "completed"
    assert result.jobs_attempted == 2
    assert waited_seconds == [300]


def test_directory_transcode_run_skips_wait_after_copy_only_job(
    tmp_path: Path, monkeypatch
) -> None:
    """Copy-only jobs do not need the cooldown wait before the next job."""
    first_file = tmp_path / "a.mkv"
    second_file = tmp_path / "b.mkv"
    for input_file in (first_file, second_file):
        input_file.write_text("not really video")
    waited_seconds: list[int] = []

    def fake_options_with_probed_codec(
        options: TranscodeOptions, *, strict: bool = True
    ) -> TranscodeOptions:
        return replace(
            options,
            video_codec="av1",
            audio_codecs=("aac", "opus"),
            subtitle_codecs=("ass", "hdmv_pgs_subtitle"),
        )

    monkeypatch.setattr(
        directory_run, "transcode_with_quality_check", lambda _options, output=None: 0
    )
    monkeypatch.setattr(
        directory_run, "options_with_probed_codec", fake_options_with_probed_codec
    )

    result = run_directory_transcode(
        tmp_path,
        DirectoryTranscodeSettings(hwaccel=False),
        wait_seconds=300,
        dry_run=False,
        output=lambda _line: None,
        wait=waited_seconds.append,
    )

    assert result.status == "completed"
    assert result.jobs_attempted == 2
    assert waited_seconds == []
