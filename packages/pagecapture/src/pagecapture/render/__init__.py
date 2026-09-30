"""Adaptive browser rendering for pages whose raw HTML lacks content."""

from .adaptive import RENDERER_VERSION, BrowserCapacity, Rendered, Renderer, content_lines

__all__ = ["Renderer", "Rendered", "BrowserCapacity", "content_lines", "RENDERER_VERSION"]
