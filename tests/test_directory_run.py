"""Tests for Directory transcode run orchestration."""

# ruff: noqa: S101

from pathlib import Path

import transcode.directory_run as directory_run
from transcode.directory_run import (
    DirectoryTranscodeSettings,
    run_directory_transcode,
)
from transcode.transcode import TranscodeOptions


def test_directory_transcode_run_reports_no_eligible_input_files(tmp_path: Path) -> None:
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

    def fake_transcode(options: TranscodeOptions) -> int:
        attempted_files.append(options.input_file)
        return 7

    monkeypatch.setattr(directory_run, "transcode", fake_transcode)

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

    monkeypatch.setattr(directory_run, "transcode", lambda _options: 0)

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
