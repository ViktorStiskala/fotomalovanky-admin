#!/usr/bin/env python
"""
Run ariadne-codegen with proper .env loading.

Usage:
    uv run codegen

This script loads environment variables from ../.env (project root)
before running ariadne-codegen, ensuring SHOPIFY_ACCESS_TOKEN is available.
"""

import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv


def main() -> int:
    """Run ariadne-codegen with environment variables loaded from .env."""
    # Find the project root (where .env is located)
    # Script is in backend/app/scripts/, .env is in project root (backend/..)
    script_dir = Path(__file__).parent
    backend_dir = script_dir.parent.parent  # backend/
    project_root = backend_dir.parent  # fotomalovanky-admin/
    env_file = project_root / ".env"

    if env_file.exists():
        print(f"Loading environment from: {env_file}")
        load_dotenv(env_file)
    else:
        print(f"Warning: .env file not found at {env_file}", file=sys.stderr)

    print(f"Running ariadne-codegen from: {backend_dir}")

    result = subprocess.run(
        ["uv", "run", "ariadne-codegen"],
        cwd=backend_dir,
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
