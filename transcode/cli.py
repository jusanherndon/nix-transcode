"""Command line interface for AV1 transcoding."""

from __future__ import annotations

import time
from pathlib import Path

import click

from transcode import __version__
from transcode.directory_run import DirectoryTranscodeSettings, run_directory_transcode
from transcode.transcode import (
    TranscodeOptions,
    display_transcode_command,
    transcode_with_quality_check,
)

DEFAULT_DIRECTORY_WAIT_SECONDS = 150


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument(
    "input_path",
    required=False,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "-i",
    "--input-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Input Matroska (.mkv) file to transcode. May also be passed positionally.",
)
@click.option(
    "-d",
    "--input-directory",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Directory of files to transcode one at a time.",
)
@click.option(
    "-o",
    "--output",
    "output_file",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Output .mkv path. Defaults to transcoded_INPUT_STEM.mkv next to the input.",
)
@click.option(
    "-q",
    "--quality",
    default=20,
    show_default=True,
    type=click.IntRange(1, 51),
    help="Intel QSV global quality. Lower is higher quality/larger file.",
)
@click.option(
    "--preset",
    default="slow",
    show_default=True,
    help="av1_qsv encoder preset, for example medium, slow, or veryslow.",
)
@click.option(
    "--hwaccel/--no-hwaccel",
    default=True,
    show_default=True,
    help="Use Intel QSV hardware-accelerated decoding when possible.",
)
@click.option("-y", "--overwrite", is_flag=True, help="Overwrite the output file.")
@click.option(
    "--check-quality/--no-check-quality",
    default=True,
    show_default=True,
    help="After a successful transcode, score the output against the input with "
    "ffmpeg-quality-metrics (PSNR, SSIM, and VMAF).",
)
@click.option(
    "--wait-seconds",
    default=DEFAULT_DIRECTORY_WAIT_SECONDS,
    show_default=True,
    type=click.IntRange(DEFAULT_DIRECTORY_WAIT_SECONDS),
    help="Seconds to wait between files when transcoding a directory; minimum is 150 seconds.",
)
@click.option(
    "--dry-run", is_flag=True, help="Print the ffmpeg command without running it."
)
@click.version_option(__version__, prog_name="transcode")
def main(
    input_path: Path | None,
    input_file: Path | None,
    input_directory: Path | None,
    output_file: Path | None,
    quality: int,
    preset: str,
    hwaccel: bool,
    overwrite: bool,
    check_quality: bool,
    wait_seconds: int,
    dry_run: bool,
) -> None:
    """Transcode a Matroska input file to AV1 in a Matroska container using Intel QSV.

    Video is encoded with ffmpeg's av1_qsv encoder. AAC/Opus audio streams are
    copied, other audio streams are converted to Opus, supported text subtitles
    are converted to ASS, and attachment streams are copied.
    """
    input_sources = [
        source
        for source in (input_path, input_file, input_directory)
        if source is not None
    ]
    if len(input_sources) > 1:
        raise click.UsageError(
            "pass input either positionally, with --input-file, or with --input-directory; not more than one"
        )

    if input_directory is not None:
        if output_file is not None:
            raise click.UsageError("--output cannot be used with --input-directory")

        result = run_directory_transcode(
            input_directory,
            DirectoryTranscodeSettings(
                quality=quality,
                preset=preset,
                hwaccel=hwaccel,
                overwrite=overwrite,
                check_quality=check_quality,
            ),
            wait_seconds=wait_seconds,
            dry_run=dry_run,
            output=click.echo,
            wait=time.sleep,
        )
        if result.status == "no_eligible_input_files":
            raise click.UsageError(f"no files found in {result.input_directory}")
        if result.status == "failed":
            raise click.exceptions.Exit(result.exit_code)
        return

    source_file = input_file or input_path
    if source_file is None:
        raise click.UsageError(
            "missing input file; pass INPUT_PATH, --input-file, or --input-directory"
        )

    options = TranscodeOptions(
        input_file=source_file,
        output_file=output_file,
        quality=quality,
        preset=preset,
        hwaccel=hwaccel,
        overwrite=overwrite,
        check_quality=check_quality,
    )
    click.echo(display_transcode_command(options))

    if dry_run:
        return

    raise click.exceptions.Exit(
        transcode_with_quality_check(options, output=click.echo)
    )
