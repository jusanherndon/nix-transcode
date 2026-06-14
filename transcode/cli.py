"""Command line interface for AV1 transcoding."""

from __future__ import annotations

import time
from pathlib import Path

import click

from transcode import __version__
from transcode.transcode import (
    TranscodeOptions,
    build_ffmpeg_command,
    format_command,
    options_with_probed_codec,
    transcode,
)

DEFAULT_DIRECTORY_WAIT_SECONDS = 300
TRANSCODED_PREFIX = "transcoded_"


def directory_output_for(input_file: Path) -> Path:
    """Return the output path used for directory transcodes."""
    return input_file.with_name(f"{TRANSCODED_PREFIX}{input_file.stem}.mkv")


def directory_inputs(input_directory: Path) -> list[Path]:
    """Return regular files in a directory, excluding previous transcode outputs."""
    return [
        path
        for path in sorted(input_directory.iterdir())
        if path.is_file() and not path.name.startswith(TRANSCODED_PREFIX)
    ]


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
    help="Output .mkv path. Defaults to INPUT_STEM.mkv next to the input.",
)
@click.option(
    "-q",
    "--quality",
    default=18,
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
    "--wait-seconds",
    default=DEFAULT_DIRECTORY_WAIT_SECONDS,
    show_default=True,
    type=click.IntRange(DEFAULT_DIRECTORY_WAIT_SECONDS),
    help="Seconds to wait between files when transcoding a directory; minimum is 300 seconds.",
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
    wait_seconds: int,
    dry_run: bool,
) -> None:
    """Transcode a Matroska input file to AV1 in a Matroska container using Intel QSV.

    Video is encoded with ffmpeg's av1_qsv encoder. Audio, subtitle, and
    attachment streams are copied from the source without re-encoding.
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

        source_files = directory_inputs(input_directory)
        if not source_files:
            raise click.UsageError(f"no files found in {input_directory}")

        jobs = [
            TranscodeOptions(
                input_file=source_file,
                output_file=directory_output_for(source_file),
                quality=quality,
                preset=preset,
                hwaccel=hwaccel,
                overwrite=overwrite,
            )
            for source_file in source_files
        ]

        for index, options in enumerate(jobs):
            display_options = options_with_probed_codec(options, strict=False)
            command = format_command(build_ffmpeg_command(display_options))
            click.echo(command)
            if dry_run:
                continue

            exit_code = transcode(options)
            if exit_code != 0:
                raise click.exceptions.Exit(exit_code)

            if index < len(jobs) - 1:
                click.echo(
                    f"Waiting {wait_seconds} seconds before the next transcode..."
                )
                time.sleep(wait_seconds)
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
    )
    display_options = options_with_probed_codec(options, strict=False)
    command = format_command(build_ffmpeg_command(display_options))

    if dry_run:
        click.echo(command)
        return

    click.echo(command)
    raise click.exceptions.Exit(transcode(options))
