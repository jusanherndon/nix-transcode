# nix-transcode Context

A small CLI context for transcoding media files to AV1/QSV Matroska outputs while preserving non-video streams if in the correct codec.

## Language

**Directory transcode run**:
An ordered batch over the eligible files in one input directory, using shared transcode settings and wait policy between successful jobs.
_Avoid_: batch job, directory mode

**Transcode job**:
One planned input-to-output media transcode with the settings needed to build, display, and execute the ffmpeg invocation.
_Avoid_: task, item

**Eligible input file**:
A regular file in an input directory that is not a previous transcode output.
_Avoid_: source file, candidate file

**Previous transcode output**:
A file whose name starts with `transcoded_`, skipped during a Directory transcode run.
_Avoid_: generated file, old output

**Directory transcode result**:
The outcome of a Directory transcode run, including whether all jobs completed, no Eligible input file values existed, or a specific Transcode job failed.
_Avoid_: exit code, status
