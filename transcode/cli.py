"""Command line interface for AV1 transcoding."""

from __future__ import annotations

from pathlib import Path

import click

from transcode import __version__
from transcode.transcode import (
    TranscodeOptions,
    build_ffmpeg_command,
    format_command,
    transcode,
)


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
    "-o",
    "--output",
    "output_file",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Output .mkv path. Defaults to INPUT_STEM.av1.mkv next to the input.",
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
@click.option("--dry-run", is_flag=True, help="Print the ffmpeg command without running it.")
@click.version_option(__version__, prog_name="transcode")
def main(
    input_path: Path | None,
    input_file: Path | None,
    output_file: Path | None,
    quality: int,
    preset: str,
    hwaccel: bool,
    overwrite: bool,
    dry_run: bool,
) -> None:
    """Transcode a Matroska input file to AV1 in a Matroska container using Intel QSV.

    Video is encoded with ffmpeg's av1_qsv encoder. Audio, subtitle, and
    attachment streams are copied from the source without re-encoding.
    """
    if input_path is not None and input_file is not None:
        raise click.UsageError("pass the input file either positionally or with --input-file, not both")

    source_file = input_file or input_path
    if source_file is None:
        raise click.UsageError("missing input file; pass INPUT_PATH or --input-file")

    options = TranscodeOptions(
        input_file=source_file,
        output_file=output_file,
        quality=quality,
        preset=preset,
        hwaccel=hwaccel,
        overwrite=overwrite,
    )
    command = format_command(build_ffmpeg_command(options))

    if dry_run:
        click.echo(command)
        return

    click.echo(command)
    raise click.exceptions.Exit(transcode(options))
