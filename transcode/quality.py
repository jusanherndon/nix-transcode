"""Compare a transcoded file against its source with ffmpeg-quality-metrics."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from ffmpeg_quality_metrics import FfmpegQualityMetrics, FfmpegQualityMetricsError

DEFAULT_QUALITY_METRICS: tuple[str, ...] = ("psnr", "ssim", "vmaf")


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
    metrics: Sequence[str] = DEFAULT_QUALITY_METRICS,
    ffmpeg_bin: str = "ffmpeg",
) -> tuple[int, str]:
    """Compare distorted against reference and return exit code plus summary text."""
    try:
        ffqm = FfmpegQualityMetrics(
            str(reference),
            str(distorted),
            ffmpeg_path=ffmpeg_bin,
        )
        ffqm.calculate(list(metrics))
        summary = format_quality_summary(ffqm.get_global_stats())
    except (OSError, FfmpegQualityMetricsError, ValueError, KeyError) as exc:
        return 1, f"Quality metrics failed: {exc}"
    return 0, summary
