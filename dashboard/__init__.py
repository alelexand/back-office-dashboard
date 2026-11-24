"""Back-office dashboard: one page with the results of every automation and one list of what people must fix."""

from .build import Assumptions, build, collect, render

__all__ = ["Assumptions", "build", "collect", "render"]
__version__ = "1.0.0"
