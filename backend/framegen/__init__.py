"""FrameGen backend: one Python package run as the API and as the worker (DESIGN.md section 9)."""

from importlib.metadata import version

__version__ = version("framegen")
