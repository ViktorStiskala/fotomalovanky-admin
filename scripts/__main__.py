"""Entry point for running scripts: uv run scripts or python -m scripts"""

try:
    # Module execution: python -m scripts
    from .cli import cli
except ImportError:
    # Direct execution: uv run scripts
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent))
    from cli import cli  # type: ignore[import-not-found,no-redef]  # noqa: E402

if __name__ == "__main__":
    cli()
