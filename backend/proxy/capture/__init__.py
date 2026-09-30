"""POST /v1/capture: pagecapture hosted on Stolosio's fleet, egress and network policy."""

from backend.proxy.capture.service import CaptureRunner, CaptureUnavailable

__all__ = ["CaptureRunner", "CaptureUnavailable"]
