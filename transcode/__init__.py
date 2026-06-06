"""AV1 transcoding CLI package."""

import importlib.metadata

try:
    __version__ = importlib.metadata.version("transcode")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.1"
