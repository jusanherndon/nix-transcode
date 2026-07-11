"""Tests for post-transcode quality metrics."""

# ruff: noqa: S101

from pathlib import Path

from ffmpeg_quality_metrics import FfmpegQualityMetricsError

import transcode.quality as quality_module
import transcode.transcode as transcode_module
from transcode.quality import check_quality, format_quality_summary, quality_metrics
from transcode.transcode import TranscodeOptions, transcode_with_quality_check


def test_quality_metrics_default_excludes_vmaf() -> None:
    """Default quality checks only run PSNR and SSIM."""
    assert quality_metrics() == ("psnr", "ssim")
    assert quality_metrics(include_vmaf=True) == ("psnr", "ssim", "vmaf")


def test_format_quality_summary_includes_psnr_ssim_and_vmaf() -> None:
    """Global stats are rendered into a short summary."""
    summary = format_quality_summary(
        {
            "psnr": {"psnr_avg": {"average": 42.5}},
            "ssim": {"ssim_avg": {"average": 0.987654}},
            "vmaf": {"vmaf": {"average": 91.234}},
        }
    )

    assert "PSNR avg: 42.500 dB" in summary
    assert "SSIM avg: 0.987654" in summary
    assert "VMAF avg: 91.234" in summary


def test_check_quality_returns_summary(tmp_path: Path, monkeypatch) -> None:
    """Successful metric runs return exit code 0 and a summary string."""
    reference = tmp_path / "source.mkv"
    distorted = tmp_path / "transcoded_source.mkv"
    reference.write_text("ref")
    distorted.write_text("dist")

    class FakeMetrics:
        def __init__(
            self, ref: str, dist: str, *, threads: int, ffmpeg_path: str
        ) -> None:
            assert ref == str(reference)
            assert dist == str(distorted)
            assert threads == 8
            assert ffmpeg_path == "ffmpeg"

        def calculate(
            self, metrics: list[str], vmaf_options: dict | None = None
        ) -> dict:
            assert metrics == ["psnr", "ssim"]
            assert vmaf_options is None
            return {}

        def get_global_stats(self) -> dict:
            return {
                "psnr": {"psnr_avg": {"average": 40.0}},
                "ssim": {"ssim_avg": {"average": 0.95}},
            }

    monkeypatch.setattr(quality_module, "FfmpegQualityMetrics", FakeMetrics)

    exit_code, summary = check_quality(reference, distorted, threads=8)

    assert exit_code == 0
    assert "PSNR avg: 40.000 dB" in summary
    assert "SSIM avg: 0.950000" in summary
    assert "VMAF" not in summary


def test_check_quality_includes_vmaf_when_requested(
    tmp_path: Path, monkeypatch
) -> None:
    """Passing include_vmaf adds VMAF and libvmaf thread options."""
    reference = tmp_path / "source.mkv"
    distorted = tmp_path / "transcoded_source.mkv"
    reference.write_text("ref")
    distorted.write_text("dist")

    class FakeMetrics:
        def __init__(
            self, _ref: str, _dist: str, *, threads: int, ffmpeg_path: str
        ) -> None:
            assert threads == 8
            assert ffmpeg_path == "ffmpeg"

        def calculate(
            self, metrics: list[str], vmaf_options: dict | None = None
        ) -> dict:
            assert metrics == ["psnr", "ssim", "vmaf"]
            assert vmaf_options == {"n_threads": 8}
            return {}

        def get_global_stats(self) -> dict:
            return {
                "psnr": {"psnr_avg": {"average": 40.0}},
                "ssim": {"ssim_avg": {"average": 0.95}},
                "vmaf": {"vmaf": {"average": 88.5}},
            }

    monkeypatch.setattr(quality_module, "FfmpegQualityMetrics", FakeMetrics)

    exit_code, summary = check_quality(
        reference, distorted, include_vmaf=True, threads=8
    )

    assert exit_code == 0
    assert "VMAF avg: 88.500" in summary


def test_default_quality_threads_leaves_two_cores(monkeypatch) -> None:
    """The default thread count is CPU count minus two, with a floor of one."""
    monkeypatch.setattr(quality_module.os, "cpu_count", lambda: 8)
    assert quality_module.default_quality_threads() == 6

    monkeypatch.setattr(quality_module.os, "cpu_count", lambda: 2)
    assert quality_module.default_quality_threads() == 1

    monkeypatch.setattr(quality_module.os, "cpu_count", lambda: 1)
    assert quality_module.default_quality_threads() == 1

    monkeypatch.setattr(quality_module.os, "cpu_count", lambda: None)
    assert quality_module.default_quality_threads() == 1


def test_check_quality_defaults_to_cpu_count_minus_two(
    tmp_path: Path, monkeypatch
) -> None:
    """Omitting threads uses CPU count minus two."""
    reference = tmp_path / "source.mkv"
    distorted = tmp_path / "transcoded_source.mkv"
    reference.write_text("ref")
    distorted.write_text("dist")
    seen: dict[str, object] = {}

    class FakeMetrics:
        def __init__(
            self, _ref: str, _dist: str, *, threads: int, ffmpeg_path: str
        ) -> None:
            seen["threads"] = threads
            assert ffmpeg_path == "ffmpeg"

        def calculate(
            self, metrics: list[str], vmaf_options: dict | None = None
        ) -> dict:
            seen["metrics"] = metrics
            seen["vmaf_options"] = vmaf_options
            return {}

        def get_global_stats(self) -> dict:
            return {}

    monkeypatch.setattr(quality_module, "FfmpegQualityMetrics", FakeMetrics)
    monkeypatch.setattr(quality_module, "default_quality_threads", lambda: 10)

    check_quality(reference, distorted)

    assert seen == {
        "threads": 10,
        "metrics": ["psnr", "ssim"],
        "vmaf_options": None,
    }


def test_check_quality_reports_failure(tmp_path: Path, monkeypatch) -> None:
    """Metric failures return a non-zero exit code and an error message."""
    reference = tmp_path / "source.mkv"
    distorted = tmp_path / "transcoded_source.mkv"
    reference.write_text("ref")
    distorted.write_text("dist")

    class FakeMetrics:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def calculate(
            self, _metrics: list[str], vmaf_options: dict | None = None
        ) -> dict:
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
        lambda reference, distorted, *, include_vmaf=False, threads=None, ffmpeg_bin="ffmpeg": (
            0,
            f"ok:{reference.name}:{distorted.name}:{include_vmaf}:{threads}:{ffmpeg_bin}",
        ),
    )

    exit_code = transcode_with_quality_check(
        TranscodeOptions(
            input_file=input_file,
            output_file=output_file,
            quality_threads=16,
            check_vmaf=True,
        ),
        output=printed.append,
    )

    assert exit_code == 0
    assert printed == [
        "Transcode done.",
        "Calculating quality metrics...",
        "ok:movie.mkv:transcoded_movie.mkv:True:16:ffmpeg",
    ]


def test_transcode_with_quality_check_can_be_skipped(
    tmp_path: Path, monkeypatch
) -> None:
    """Quality checking can be disabled without calling the metrics helper."""
    input_file = tmp_path / "movie.mkv"
    input_file.write_text("not really video")
    called = False
    printed: list[str] = []

    monkeypatch.setattr(transcode_module, "transcode", lambda _options: 0)

    def unexpected_check(*_args, **_kwargs):
        nonlocal called
        called = True
        return 0, "should not run"

    monkeypatch.setattr(transcode_module, "check_quality", unexpected_check)

    exit_code = transcode_with_quality_check(
        TranscodeOptions(input_file=input_file, check_quality=False),
        output=printed.append,
    )

    assert exit_code == 0
    assert called is False
    assert printed == ["Transcode done."]


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
