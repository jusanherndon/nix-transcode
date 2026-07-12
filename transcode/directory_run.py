"""Directory transcode run orchestration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from transcode.transcode import (
    TRANSCODED_PREFIX,
    TranscodeOptions,
    display_transcode_command,
    media_stream_codec_options_all_copy,
    options_with_probed_codec,
    transcode_with_quality_check,
)

OutputAdapter = Callable[[str], None]
WaitAdapter = Callable[[int], None]


@dataclass(frozen=True, slots=True)
class DirectoryTranscodeSettings:
    """Shared settings for every Transcode job in a Directory transcode run."""

    quality: int = 20
    bitrate: int | None = None
    maxrate: int | None = None
    preset: str = "slow"
    hwaccel: bool = True
    overwrite: bool = False
    check_quality: bool = True
    check_vmaf: bool = False
    quality_threads: int | None = None


@dataclass(frozen=True, slots=True)
class TranscodeJob:
    """One planned input-to-output media transcode."""

    input_file: Path
    output_file: Path
    settings: DirectoryTranscodeSettings

    def to_options(self) -> TranscodeOptions:
        """Return TranscodeOptions for this job."""
        return TranscodeOptions(
            input_file=self.input_file,
            output_file=self.output_file,
            quality=self.settings.quality,
            bitrate=self.settings.bitrate,
            maxrate=self.settings.maxrate,
            preset=self.settings.preset,
            hwaccel=self.settings.hwaccel,
            overwrite=self.settings.overwrite,
            check_quality=self.settings.check_quality,
            check_vmaf=self.settings.check_vmaf,
            quality_threads=self.settings.quality_threads,
        )


@dataclass(frozen=True, slots=True)
class DirectoryTranscodeCompleted:
    """Directory transcode result for a completed run."""

    status: Literal["completed"]
    jobs_attempted: int


@dataclass(frozen=True, slots=True)
class DirectoryTranscodeNoEligibleInputFiles:
    """Directory transcode result when no Eligible input file values exist."""

    status: Literal["no_eligible_input_files"]
    input_directory: Path


@dataclass(frozen=True, slots=True)
class DirectoryTranscodeFailed:
    """Directory transcode result when a Transcode job fails."""

    status: Literal["failed"]
    job: TranscodeJob
    job_index: int
    exit_code: int


DirectoryTranscodeResult = (
    DirectoryTranscodeCompleted
    | DirectoryTranscodeNoEligibleInputFiles
    | DirectoryTranscodeFailed
)


def directory_output_for(input_file: Path) -> Path:
    """Return the output path used for directory transcodes."""
    return input_file.with_name(f"{TRANSCODED_PREFIX}{input_file.stem}.mkv")


def eligible_input_files(input_directory: Path) -> list[Path]:
    """Return regular files, excluding Previous transcode output values."""
    return [
        path
        for path in sorted(input_directory.iterdir())
        if path.is_file() and not path.name.startswith(TRANSCODED_PREFIX)
    ]


def plan_transcode_jobs(
    input_directory: Path, settings: DirectoryTranscodeSettings
) -> list[TranscodeJob]:
    """Return the Transcode job values for a Directory transcode run."""
    return [
        TranscodeJob(
            input_file=input_file,
            output_file=directory_output_for(input_file),
            settings=settings,
        )
        for input_file in eligible_input_files(input_directory)
    ]


def run_directory_transcode(
    input_directory: Path,
    settings: DirectoryTranscodeSettings,
    *,
    wait_seconds: int,
    dry_run: bool,
    output: OutputAdapter,
    wait: WaitAdapter,
) -> DirectoryTranscodeResult:
    """Run a Directory transcode run and return its Directory transcode result."""
    jobs = plan_transcode_jobs(input_directory, settings)
    if not jobs:
        return DirectoryTranscodeNoEligibleInputFiles(
            status="no_eligible_input_files", input_directory=input_directory
        )

    for index, job in enumerate(jobs):
        options = job.to_options()
        display_options = options_with_probed_codec(options, strict=False)
        output(display_transcode_command(options, display_options=display_options))
        if dry_run:
            continue

        exit_code = transcode_with_quality_check(options, output=output)
        if exit_code != 0:
            return DirectoryTranscodeFailed(
                status="failed",
                job=job,
                job_index=index,
                exit_code=exit_code,
            )

        if index < len(jobs) - 1 and not media_stream_codec_options_all_copy(
            display_options
        ):
            output(f"Waiting {wait_seconds} seconds before the next transcode...")
            wait(wait_seconds)

    return DirectoryTranscodeCompleted(status="completed", jobs_attempted=len(jobs))
