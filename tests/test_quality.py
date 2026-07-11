"""Tests for post-transcode quality metrics."""

# ruff: noqa: S101

from pathlib import Path

from ffmpeg_quality_metrics import FfmpegQualityMetricsError

import transcode.quality as quality_module
import transcode.transcode as transcode_module
from transcode.quality import check_quality, format_quality_summary
from transcode.transcode import TranscodeOptions, transcode_with_quality_check


def test_format_quality_summary_includes_psnr_and_ssim() -> None:
    """Global stats are rendered into a short summary."""
    summary = format_quality_summary(
        {
            "psnr": {"psnr_avg": {"average": 42.5}},
            "ssim": {"ssim_avg": {"average": 0.987654}},
        }
    )

    assert "PSNR avg: 42.500 dB" in summary
    assert "SSIM avg: 0.987654" in summary


def test_check_quality_returns_summary(tmp_path: Path, monkeypatch) -> None:
    """Successful metric runs return exit code 0 and a summary string."""
    reference = tmp_path / "source.mkv"
    distorted = tmp_path / "transcoded_source.mkv"
    reference.write_text("ref")
    distorted.write_text("dist")

    class FakeMetrics:
        def __init__(self, ref: str, dist: str, *, ffmpeg_path: str) -> None:
            assert ref == str(reference)
            assert dist == str(distorted)
            assert ffmpeg_path == "ffmpeg"

        def calculate(self, metrics: list[str]) -> dict:
            assert metrics == ["psnr", "ssim"]
            return {}

        def get_global_stats(self) -> dict:
            return {
                "psnr": {"psnr_avg": {"average": 40.0}},
                "ssim": {"ssim_avg": {"average": 0.95}},
            }

    monkeypatch.setattr(quality_module, "FfmpegQualityMetrics", FakeMetrics)

    exit_code, summary = check_quality(reference, distorted)

    assert exit_code == 0
    assert "PSNR avg: 40.000 dB" in summary
    assert "SSIM avg: 0.950000" in summary


def test_check_quality_reports_failure(tmp_path: Path, monkeypatch) -> None:
    """Metric failures return a non-zero exit code and an error message."""
    reference = tmp_path / "source.mkv"
    distorted = tmp_path / "transcoded_source.mkv"
    reference.write_text("ref")
    distorted.write_text("dist")

    class FakeMetrics:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def calculate(self, _metrics: list[str]) -> dict:
            raise FfmpegQualityMetricsError("boom")

    monkeypatch.setattr(quality_module, "FfmpegQualityMetrics", FakeMetrics)

    exit_code, summary = check_quality(reference, distorted)

    assert exit_code == 1
    assert summary.startswith("Quality metrics failed:")


def test_transcode_with_quality_check_runs_after_success(
    tmp_path: Path, monkeypatch
) -> None:
    """A successful transcode is followed by a quality comparison."""
    input_file = tmp_path / "movie.mkv"
    output_file = tmp_path / "transcoded_movie.mkv"
    input_file.write_text("not really video")
    printed: list[str] = []

    monkeypatch.setattr(transcode_module, "transcode", lambda _options: 0)
    monkeypatch.setattr(
        transcode_module,
        "check_quality",
        lambda reference, distorted, *, ffmpeg_bin="ffmpeg": (
            0,
            f"ok:{reference.name}:{distorted.name}:{ffmpeg_bin}",
        ),
    )

    exit_code = transcode_with_quality_check(
        TranscodeOptions(input_file=input_file, output_file=output_file),
        output=printed.append,
    )

    assert exit_code == 0
    assert printed == ["ok:movie.mkv:transcoded_movie.mkv:ffmpeg"]


def test_transcode_with_quality_check_can_be_skipped(
    tmp_path: Path, monkeypatch
) -> None:
    """Quality checking can be disabled without calling the metrics helper."""
    input_file = tmp_path / "movie.mkv"
    input_file.write_text("not really video")
    called = False

    monkeypatch.setattr(transcode_module, "transcode", lambda _options: 0)

    def unexpected_check(*_args, **_kwargs):
        nonlocal called
        called = True
        return 0, "should not run"

    monkeypatch.setattr(transcode_module, "check_quality", unexpected_check)

    exit_code = transcode_with_quality_check(
        TranscodeOptions(input_file=input_file, check_quality=False),
        output=lambda _line: None,
    )

    assert exit_code == 0
    assert called is False


def test_transcode_with_quality_check_skips_on_transcode_failure(
    tmp_path: Path, monkeypatch
) -> None:
    """Failed transcodes do not run quality metrics."""
    input_file = tmp_path / "movie.mkv"
    input_file.write_text("not really video")
    called = False

    monkeypatch.setattr(transcode_module, "transcode", lambda _options: 3)

    def unexpected_check(*_args, **_kwargs):
        nonlocal called
        called = True
        return 0, "should not run"

    monkeypatch.setattr(transcode_module, "check_quality", unexpected_check)

    exit_code = transcode_with_quality_check(
        TranscodeOptions(input_file=input_file),
        output=lambda _line: None,
    )

    assert exit_code == 3
    assert called is False
