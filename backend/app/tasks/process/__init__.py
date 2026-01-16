"""Image processing tasks package."""

from app.tasks.process.generate_coloring import generate_coloring
from app.tasks.process.vectorize_image import vectorize_image

__all__ = ["generate_coloring", "vectorize_image"]
