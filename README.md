# nix-transcode

A small Python CLI that shells out to `ffmpeg` to transcode video to AV1 with Intel Quick Sync Video (`av1_qsv`).

The default command:

- writes a Matroska (`.mkv`) container
- probes the input video codec with `ffprobe`
- encodes video with Intel's AV1 QSV encoder using 10-bit `p010le`, unless the input is already AV1
- copies AV1 video streams without re-encoding
- copies audio streams without re-encoding
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

A directory transcode creates outputs next to each source file with a `transcoded_` prefix, such as `transcoded_input.mkv`. Files that already start with `transcoded_` are skipped. Directory transcodes wait at least 300 seconds (5 minutes) between files to give the GPU a break.

Useful options:

```sh
transcode input.mkv -o output.mkv
transcode --input-file input.mkv -o output.mkv
transcode --input-directory /path/to/videos --wait-seconds 600
transcode input.mkv --quality 16 --preset slow
transcode input.mkv --dry-run
transcode input.mkv --no-hwaccel
transcode input.mkv --overwrite
```

`--quality` maps to ffmpeg's `-global_quality` for `av1_qsv`; lower values preserve more quality but create larger files. The default is `18`. If the first video stream is already AV1, the video stream is copied and encoder quality/preset options are not used. All subtitle streams are mapped with `-map 0`; each SSA/ASS subtitle stream is copied, and each other subtitle stream is converted to ASS.

## Example ffmpeg command

```sh
ffmpeg -hide_banner -n -hwaccel qsv -hwaccel_output_format qsv -i input.mkv \
  -map 0 -map_metadata 0 -map_chapters 0 \
  -c:v av1_qsv -preset slow -global_quality 18 -b:v 0 \
  -c:a copy -c:s:0 ass -c:t copy \
  -f matroska -max_muxing_queue_size 4096 -vf vpp_qsv=format=p010le transcoded_input.mkv
```
