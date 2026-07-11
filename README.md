# nix-transcode

A small Python CLI that shells out to `ffmpeg` to transcode video to AV1 with Intel Quick Sync Video (`av1_qsv`).

The default command:

- writes a Matroska (`.mkv`) container
- probes the input video codecs with `ffprobe`
- encodes video with Intel's AV1 QSV encoder using 10-bit `p010le`, unless the kept input video is already AV1
- copies AV1 video streams without re-encoding
- drops an MJPEG video stream when it is one of exactly two video streams in the container
- copies AAC and Opus audio streams without re-encoding
- converts other audio streams to Opus while preserving channel layouts such as 5.1 when supported by ffmpeg/libopus
- copies subtitle streams without re-encoding when they are already SSA/ASS
- converts other subtitle streams to ASS
- preserves metadata and chapters

## Requirements

- `ffmpeg` and `ffprobe` available on `PATH`
- An Intel GPU/driver stack with `av1_qsv` support

Check encoder availability with:

```sh
ffmpeg -hide_banner -encoders | grep av1_qsv
```

## Usage

```sh
transcode input.mkv
# or
transcode --input-file input.mkv
# or transcode every regular file in a directory, one at a time
transcode --input-directory /path/to/videos
```

A single-file transcode creates `input.mkv` next to the source file.

A directory transcode creates outputs next to each source file with a `transcoded_` prefix, such as `transcoded_input.mkv`. Files that already start with `transcoded_` are skipped. Directory transcodes wait at least 150 seconds (2.5 minutes) between files to give the GPU a break.

Useful options:

```sh
transcode input.mkv -o output.mkv
transcode --input-file input.mkv -o output.mkv
transcode --input-directory /path/to/videos --wait-seconds 600
transcode input.mkv --quality 16 --preset slow
transcode input.mkv --dry-run
transcode input.mkv --no-hwaccel
transcode input.mkv --overwrite
transcode input.mkv --no-check-quality
transcode input.mkv --quality-threads 16
```

`--quality` maps to ffmpeg's `-global_quality` for `av1_qsv`; lower values preserve more quality but create larger files. The default is `18`. If the kept video stream is already AV1, the video stream is copied and encoder quality/preset options are not used. After a successful transcode, the tool compares the output against the input with `ffmpeg-quality-metrics` (PSNR, SSIM, and VMAF) unless `--no-check-quality` is passed. Quality checks default to CPU count minus two for ffmpeg filters and libvmaf (leaving headroom for other programs); override with `--quality-threads N`. All streams are mapped with `-map 0`, except that an MJPEG video stream is excluded when it is paired with one other video stream. Each AAC/Opus audio stream is copied, and each other audio stream is converted to Opus. Surround layouts such as 5.1 are not downmixed by this tool. Each SSA/ASS or bitmap subtitle stream is copied, and each other text subtitle stream is converted to ASS.

## Example ffmpeg command

```sh
ffmpeg -hide_banner -n -hwaccel qsv -hwaccel_output_format qsv -i input.mkv \
  -map 0 -map_metadata 0 -map_chapters 0 \
  -c:v av1_qsv -preset slow -global_quality 20 \
  -c:a:0 aac -c:s:0 ass -c:t copy \
  -f matroska -vf vpp_qsv=format=p010le transcoded_input.mkv
```
