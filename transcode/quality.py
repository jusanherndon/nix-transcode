"""Compare a transcoded file against its source with ffmpeg-quality-metrics."""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from ffmpeg_quality_metrics import FfmpegQualityMetrics, FfmpegQualityMetricsError

DEFAULT_QUALITY_METRICS: tuple[str, ...] = ("psnr", "ssim")


def default_quality_threads() -> int:
    """Return the default thread count for quality metric calculation.

    Leaves two cores free so other programs can keep responding.
    """
    return max(1, (os.cpu_count() or 1) - 2)


def quality_metrics(*, include_vmaf: bool = False) -> tuple[str, ...]:
    """Return the metric names to calculate for a quality check."""
    if include_vmaf:
        return (*DEFAULT_QUALITY_METRICS, "vmaf")
    return DEFAULT_QUALITY_METRICS


def format_quality_summary(global_stats: dict) -> str:
    """Return a short human-readable summary of global metric stats."""
    lines = ["Quality metrics (output vs input):"]
    psnr = global_stats.get("psnr", {}).get("psnr_avg", {})
    if "average" in psnr:
        lines.append(f"  PSNR avg: {psnr['average']:.3f} dB")
    ssim = global_stats.get("ssim", {}).get("ssim_avg", {})
    if "average" in ssim:
        lines.append(f"  SSIM avg: {ssim['average']:.6f}")
    vmaf = global_stats.get("vmaf", {}).get("vmaf", {})
    if "average" in vmaf:
        lines.append(f"  VMAF avg: {vmaf['average']:.3f}")
    if len(lines) == 1:
        lines.append("  (no summary stats available)")
    return "\n".join(lines)


def check_quality(
    reference: Path,
    distorted: Path,
    *,
    metrics: Sequence[str] | None = None,
    include_vmaf: bool = False,
    threads: int | None = None,
    ffmpeg_bin: str = "ffmpeg",
) -> tuple[int, str]:
    """Compare distorted against reference and return exit code plus summary text.

    ``threads`` sets ffmpeg filter threads and, when VMAF is enabled, libvmaf
    ``n_threads``. When omitted, uses CPU count minus two (at least one thread).
    """
    selected_metrics = (
        tuple(metrics)
        if metrics is not None
        else quality_metrics(include_vmaf=include_vmaf)
    )
    thread_count = default_quality_threads() if threads is None else threads
    try:
        ffqm = FfmpegQualityMetrics(
            str(reference),
            str(distorted),
            threads=thread_count,
            ffmpeg_path=ffmpeg_bin,
        )
        vmaf_options = (
            {"n_threads": thread_count} if "vmaf" in selected_metrics else None
        )
        ffqm.calculate(list(selected_metrics), vmaf_options=vmaf_options)
        summary = format_quality_summary(ffqm.get_global_stats())
    except (OSError, FfmpegQualityMetricsError, ValueError, KeyError) as exc:
        return 1, f"Quality metrics failed: {exc}"
    return 0, summary
