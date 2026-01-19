#!/usr/bin/env python3
"""
Batch processing script for orders folder with nested subfolders.

This script:
1. Recursively finds all subfolders in the orders folder
2. Processes each subfolder's images through RunPod API
3. Maintains the same folder structure in the output
4. Vectorizes the coloring books to SVG

Usage:
    python process_orders.py
    python process_orders.py --input orders --output orders-output
    python process_orders.py --preset high
"""

import asyncio
import base64
import os
import shutil
import time
from pathlib import Path

import aiohttp
import requests
from dotenv import load_dotenv
from PIL import Image

# Load environment variables
load_dotenv()

# Configuration
DEFAULT_INPUT_FOLDER = "orders"
DEFAULT_OUTPUT_FOLDER = "orders-output"
RUNPOD_ENDPOINT = "jg0fxdba5anpy2"
RUNPOD_API_KEY = os.getenv("RUNPOD_API_KEY", "")

# Default generation settings
DEFAULT_MEGAPIXELS = 1.0
DEFAULT_STEPS = 4

# Vectorizer config
VECTORIZER_API_KEY = os.getenv("VECTORIZER_API_KEY", "vkmyx3naqnistth")
VECTORIZER_API_SECRET = os.getenv(
    "VECTORIZER_API_SECRET", "135mnhlu590lk7pljo5hkagvmn8b3th4as2mg8qn3upfkiedt18e"
)
VECTORIZER_URL = "https://vectorizer.ai/api/v1/vectorize"
VECTORIZER_OPTIONS = {
    "output.shape_stacking": "stacked",
    "output.group_by": "color",
    "output.parameterized_shapes.flatten": "true",
}

# RunPod API config
RUNPOD_BASE_URL = f"https://api.runpod.ai/v2/{RUNPOD_ENDPOINT}"
CONCURRENCY = 3  # Match worker count
POLL_INTERVAL = 3.0
TIMEOUT = 600  # 10 minute timeout for queued jobs

# Minimum image size (longer side) - images smaller than this will be upscaled
MIN_IMAGE_SIZE = 1200


def find_images(folder: Path) -> list[Path]:
    """Find all image files in a folder (non-recursive)."""
    extensions = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
    images = []

    if not folder.exists():
        return []

    for entry in folder.iterdir():
        if entry.is_file() and entry.suffix.lower() in extensions:
            images.append(entry)

    return sorted(images)


def find_subfolders(folder: Path) -> list[Path]:
    """Find all subfolders that contain images."""
    subfolders = []

    if not folder.exists():
        print(f"Error: Folder '{folder}' does not exist")
        return []

    for entry in sorted(folder.iterdir()):
        if entry.is_dir() and not entry.name.startswith("."):
            images = find_images(entry)
            if images:
                subfolders.append(entry)

    return subfolders


def ensure_min_resolution(image_path: Path, output_path: Path) -> Path:
    """
    Ensure image meets minimum resolution. Upscale if needed.
    Returns path to the image to use for processing.
    """
    with Image.open(image_path) as img:
        width, height = img.size
        max_dim = max(width, height)

        if max_dim >= MIN_IMAGE_SIZE:
            # Image is large enough, just copy it
            if image_path != output_path:
                shutil.copy2(image_path, output_path)
            return output_path

        # Calculate scale factor to reach minimum size
        scale = MIN_IMAGE_SIZE / max_dim
        new_width = int(width * scale)
        new_height = int(height * scale)

        # Upscale using LANCZOS for quality
        resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

        # Save as PNG to avoid JPEG recompression artifacts
        output_png = output_path.with_suffix(".png")
        resized.save(output_png, "PNG")

        print(
            f"      ↑ Upscaled {image_path.name}: {width}x{height} -> {new_width}x{new_height}"
        )
        return output_png


async def submit_job(
    session: aiohttp.ClientSession,
    image_path: Path,
    megapixels: float = None,
    steps: int = None,
) -> dict:
    """Submit a single job to RunPod."""
    try:
        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode()

        headers = {
            "Authorization": f"Bearer {RUNPOD_API_KEY}",
            "Content-Type": "application/json",
        }

        input_payload = {"image": image_b64}
        if megapixels is not None:
            input_payload["megapixels"] = megapixels
        if steps is not None:
            input_payload["steps"] = steps

        async with session.post(
            f"{RUNPOD_BASE_URL}/run", headers=headers, json={"input": input_payload}
        ) as response:
            result = await response.json()
            return {
                "image_path": image_path,
                "job_id": result.get("id"),
                "status": "SUBMITTED",
                "submitted_at": time.time(),
            }
    except Exception as e:
        return {
            "image_path": image_path,
            "job_id": None,
            "status": "SUBMIT_FAILED",
            "error": str(e),
        }


async def poll_job(
    session: aiohttp.ClientSession, job: dict, output_folder: Path
) -> dict:
    """Poll a job until completion and save result."""
    if not job.get("job_id"):
        return {
            "image_path": job["image_path"],
            "status": "FAILED",
            "error": job.get("error", "No job ID"),
        }

    headers = {"Authorization": f"Bearer {RUNPOD_API_KEY}"}

    while True:
        elapsed = time.time() - job["submitted_at"]
        if elapsed > TIMEOUT:
            return {
                "image_path": job["image_path"],
                "status": "TIMEOUT",
                "error": f"Job timed out after {TIMEOUT}s",
            }

        try:
            async with session.get(
                f"{RUNPOD_BASE_URL}/status/{job['job_id']}", headers=headers
            ) as response:
                result = await response.json()

            status = result.get("status")

            if status == "COMPLETED":
                output = result.get("output", {})
                if "output" in output:
                    output = output["output"]

                image_b64 = output.get("image")
                if image_b64:
                    stem = job["image_path"].stem
                    output_path = output_folder / f"{stem}_bw.png"

                    image_data = base64.b64decode(image_b64)
                    with open(output_path, "wb") as f:
                        f.write(image_data)

                    return {
                        "image_path": job["image_path"],
                        "output_path": output_path,
                        "status": "COMPLETED",
                        "execution_time": result.get("executionTime", 0) / 1000,
                    }
                else:
                    return {
                        "image_path": job["image_path"],
                        "status": "FAILED",
                        "error": "No image in output",
                    }

            elif status == "FAILED":
                return {
                    "image_path": job["image_path"],
                    "status": "FAILED",
                    "error": result.get("error", "Unknown error"),
                }

            await asyncio.sleep(POLL_INTERVAL)

        except Exception:
            await asyncio.sleep(POLL_INTERVAL)


async def process_batch(
    images: list[Path], output_folder: Path, megapixels: float = None, steps: int = None
) -> list[dict]:
    """Process a batch of images through RunPod API."""

    async with aiohttp.ClientSession() as session:
        semaphore = asyncio.Semaphore(CONCURRENCY)

        async def submit_with_limit(img):
            async with semaphore:
                return await submit_job(
                    session, img, megapixels=megapixels, steps=steps
                )

        print(f"    Submitting {len(images)} jobs...")
        jobs = await asyncio.gather(*[submit_with_limit(img) for img in images])

        print("    Waiting for results...")

        async def poll_with_progress(job, idx):
            result = await poll_job(session, job, output_folder)
            status_icon = "✓" if result["status"] == "COMPLETED" else "✗"
            print(
                f"      [{idx + 1}/{len(jobs)}] {status_icon} {job['image_path'].name}"
            )
            return result

        results = await asyncio.gather(
            *[poll_with_progress(job, idx) for idx, job in enumerate(jobs)]
        )

        return results


def vectorize_image(image_path: Path, output_path: Path) -> bool:
    """Vectorize a single image to SVG."""
    if not VECTORIZER_API_KEY or not VECTORIZER_API_SECRET:
        return False

    try:
        with open(image_path, "rb") as img_file:
            files = {"image": (image_path.name, img_file, "image/png")}
            auth = (VECTORIZER_API_KEY, VECTORIZER_API_SECRET)

            response = requests.post(
                VECTORIZER_URL, files=files, data=VECTORIZER_OPTIONS, auth=auth
            )

            if response.status_code == requests.codes.ok:
                with open(output_path, "wb") as svg_file:
                    svg_file.write(response.content)
                return True
            else:
                print(f"      Vectorizer error: {response.status_code}")
                return False

    except Exception as e:
        print(f"      Vectorizer exception: {e}")
        return False


def vectorize_batch(bw_images: list[Path]) -> int:
    """Vectorize all _bw images to SVG."""
    if not VECTORIZER_API_KEY or not VECTORIZER_API_SECRET:
        print("    Skipping vectorization: API keys not set")
        return 0

    print(f"    Vectorizing {len(bw_images)} images...")
    success_count = 0

    for idx, img_path in enumerate(bw_images):
        svg_path = img_path.with_suffix(".svg")
        status = "✓" if vectorize_image(img_path, svg_path) else "✗"
        print(f"      [{idx + 1}/{len(bw_images)}] {status} {img_path.name} -> SVG")
        if status == "✓":
            success_count += 1

    return success_count


async def process_subfolder(
    subfolder: Path,
    output_subfolder: Path,
    megapixels: float,
    steps: int,
    no_vectorize: bool,
) -> dict:
    """Process a single subfolder."""
    images = find_images(subfolder)

    if not images:
        return {
            "folder": subfolder.name,
            "images": 0,
            "completed": 0,
            "vectorized": 0,
            "skipped": 0,
        }

    # Create output subfolder
    output_subfolder.mkdir(parents=True, exist_ok=True)

    # Copy original images
    print(f"    Copying {len(images)} originals...")
    for img in images:
        dest = output_subfolder / img.name
        if not dest.exists():
            shutil.copy2(img, dest)

    # Filter out images that already have _bw.png output
    images_to_process = []
    skipped = 0
    for img in images:
        bw_path = output_subfolder / f"{img.stem}_bw.png"
        if bw_path.exists():
            skipped += 1
        else:
            images_to_process.append(img)

    if skipped > 0:
        print(f"    Skipping {skipped} already processed images")

    if not images_to_process:
        # All images already processed, just vectorize missing SVGs
        bw_images = list(output_subfolder.glob("*_bw.png"))
        bw_to_vectorize = [
            bw for bw in bw_images if not bw.with_suffix(".svg").exists()
        ]
        vectorized = 0
        if bw_to_vectorize and not no_vectorize:
            vectorized = vectorize_batch(bw_to_vectorize)
        return {
            "folder": subfolder.name,
            "images": len(images),
            "completed": skipped,
            "vectorized": vectorized,
            "skipped": skipped,
        }

    # Prepare images (upscale if needed)
    prepared_folder = output_subfolder / ".prepared"
    prepared_folder.mkdir(exist_ok=True)

    print(f"    Preparing {len(images_to_process)} images...")
    prepared_images = []
    for img in images_to_process:
        prepared_path = prepared_folder / img.name
        actual_path = ensure_min_resolution(img, prepared_path)
        prepared_images.append((img, actual_path))

    # Process through RunPod API (use prepared images)
    results = await process_batch(
        [p[1] for p in prepared_images],
        output_subfolder,
        megapixels=megapixels,
        steps=steps,
    )

    # Map results back to original image names for output
    for i, result in enumerate(results):
        if i < len(prepared_images):
            result["original_path"] = prepared_images[i][0]

    # Clean up prepared folder
    shutil.rmtree(prepared_folder, ignore_errors=True)

    completed = [r for r in results if r["status"] == "COMPLETED"]
    new_bw_images = [r["output_path"] for r in completed if r.get("output_path")]

    # Vectorize all _bw images that don't have SVGs
    all_bw_images = list(output_subfolder.glob("*_bw.png"))
    bw_to_vectorize = [
        bw for bw in all_bw_images if not bw.with_suffix(".svg").exists()
    ]

    vectorized = 0
    if bw_to_vectorize and not no_vectorize:
        vectorized = vectorize_batch(bw_to_vectorize)

    return {
        "folder": subfolder.name,
        "images": len(images),
        "completed": len(completed) + skipped,
        "vectorized": vectorized,
        "skipped": skipped,
    }


async def main_async(args):
    """Main async processing function."""
    script_dir = Path(__file__).parent
    input_folder = script_dir / args.input
    output_folder = script_dir / args.output

    # Find all subfolders with images
    subfolders = find_subfolders(input_folder)

    if not subfolders:
        print(f"No subfolders with images found in {input_folder}")
        return

    total_images = sum(len(find_images(sf)) for sf in subfolders)
    print(f"Found {len(subfolders)} order folders with {total_images} total images")
    for sf in subfolders:
        img_count = len(find_images(sf))
        print(f"  - {sf.name}: {img_count} images")
    print()

    # Apply presets
    megapixels = args.megapixels
    steps = args.steps

    if args.preset:
        presets = {
            "default": (1.0, 4),
            "medium": (2.0, 4),
            "high": (4.0, 8),
        }
        megapixels, steps = presets[args.preset]

    print(
        f"Settings: megapixels={megapixels or DEFAULT_MEGAPIXELS}, steps={steps or DEFAULT_STEPS}"
    )
    print()

    # Create output folder
    output_folder.mkdir(exist_ok=True)

    # Process each subfolder
    all_results = []

    for idx, subfolder in enumerate(subfolders):
        print("=" * 60)
        print(f"[{idx + 1}/{len(subfolders)}] Processing: {subfolder.name}")
        print("=" * 60)

        output_subfolder = output_folder / subfolder.name
        result = await process_subfolder(
            subfolder,
            output_subfolder,
            megapixels=megapixels,
            steps=steps,
            no_vectorize=args.no_vectorize,
        )
        all_results.append(result)

        print(
            f"    Done: {result['completed']}/{result['images']} images, {result['vectorized']} SVGs"
        )
        print()

    # Final summary
    print("=" * 60)
    print("FINAL SUMMARY")
    print("=" * 60)

    total_processed = sum(r["completed"] for r in all_results)
    total_vectorized = sum(r["vectorized"] for r in all_results)

    for r in all_results:
        print(
            f"  {r['folder']}: {r['completed']}/{r['images']} images, {r['vectorized']} SVGs"
        )

    print()
    print(
        f"Total: {total_processed}/{total_images} images processed, {total_vectorized} SVGs created"
    )
    print(f"Output: {output_folder}")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Batch process images in order subfolders",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python process_orders.py                           # Default settings
  python process_orders.py --preset high             # High detail
  python process_orders.py --no-vectorize            # Skip SVG conversion
  python process_orders.py -i orders -o orders-done  # Custom folders

Presets:
  default  - megapixels=1, steps=4  (fast)
  medium   - megapixels=2, steps=4  (balanced)
  high     - megapixels=4, steps=8  (detailed, slower)
        """,
    )
    parser.add_argument(
        "--megapixels",
        "-m",
        type=float,
        default=None,
        help="Resolution/detail level (0.5-8, default: 1)",
    )
    parser.add_argument(
        "--steps",
        "-s",
        type=int,
        default=None,
        help="Diffusion steps (1-20, default: 4)",
    )
    parser.add_argument(
        "--preset",
        "-p",
        choices=["default", "medium", "high"],
        help="Use a preset configuration",
    )
    parser.add_argument(
        "--input",
        "-i",
        type=str,
        default=DEFAULT_INPUT_FOLDER,
        help=f"Input folder with subfolders (default: {DEFAULT_INPUT_FOLDER})",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=DEFAULT_OUTPUT_FOLDER,
        help=f"Output folder (default: {DEFAULT_OUTPUT_FOLDER})",
    )
    parser.add_argument(
        "--no-vectorize", action="store_true", help="Skip SVG vectorization step"
    )

    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
