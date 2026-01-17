#!/usr/bin/env python3
"""Migration script to update storage paths from order_id to shopify_id.

This script:
1. Queries all orders to get the mapping of internal order_id -> shopify_id
2. Moves files from old paths ({order_id}/...) to new paths ({shopify_id}/...)
3. Updates database records with new paths

Run inside Docker container:
    docker exec -it <dramatiq-or-backend-container> python scripts/migrate_storage_paths.py

Or with uv locally (requires DATABASE_URL pointing to accessible DB):
    uv run python scripts/migrate_storage_paths.py
"""

import asyncio
import os
import re
import shutil
from pathlib import Path

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import select

# Configure logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ]
)
logger = structlog.get_logger(__name__)


def _import_models() -> None:
    """Import all models to resolve SQLAlchemy relationships."""
    # Import in dependency order to resolve relationships
    from app.models import coloring  # noqa: F401
    from app.models import order  # noqa: F401


async def get_order_mapping(session: AsyncSession) -> dict[int, int]:
    """Get mapping of internal order_id to shopify_id."""
    _import_models()
    from app.models.order import Order

    statement = select(Order.id, Order.shopify_id)
    result = await session.execute(statement)
    rows = result.all()
    return {row[0]: row[1] for row in rows}


def update_path(old_path: str | None, order_id_to_shopify: dict[int, int]) -> str | None:
    """Update a storage path from order_id to shopify_id format.

    Old format: /data/images/{order_id}/{line_item_id}/...
    New format: /data/images/{shopify_id}/{line_item_id}/...
    """
    if not old_path:
        return None

    # Pattern: /data/images/{order_id}/{rest_of_path}
    # The order_id is the first numeric segment after /data/images/
    match = re.match(r"^(/data/images/)(\d+)/(.*)$", old_path)
    if not match:
        logger.warning("Path doesn't match expected format", path=old_path)
        return old_path

    prefix, order_id_str, rest = match.groups()
    order_id = int(order_id_str)

    if order_id not in order_id_to_shopify:
        logger.warning("Order ID not found in mapping", order_id=order_id, path=old_path)
        return old_path

    shopify_id = order_id_to_shopify[order_id]
    new_path = f"{prefix}{shopify_id}/{rest}"
    return new_path


async def migrate_files(
    storage_base: Path,
    order_id_to_shopify: dict[int, int],
    dry_run: bool = True,
) -> dict[str, str]:
    """Move files from old paths to new paths.

    Returns mapping of old_path -> new_path for moved files.
    """
    moved_files: dict[str, str] = {}

    for order_id, shopify_id in order_id_to_shopify.items():
        old_dir = storage_base / str(order_id)
        new_dir = storage_base / str(shopify_id)

        if not old_dir.exists():
            continue

        if old_dir == new_dir:
            logger.info("Path unchanged (order_id equals shopify_id)", order_id=order_id)
            continue

        logger.info(
            "Moving directory",
            old_dir=str(old_dir),
            new_dir=str(new_dir),
            dry_run=dry_run,
        )

        if not dry_run:
            # Create parent directory if needed
            new_dir.parent.mkdir(parents=True, exist_ok=True)

            if new_dir.exists():
                # If new dir exists, merge contents
                for item in old_dir.iterdir():
                    src = item
                    dst = new_dir / item.name
                    if dst.exists():
                        if src.is_dir():
                            # Recursively merge directories
                            shutil.copytree(src, dst, dirs_exist_ok=True)
                            shutil.rmtree(src)
                        else:
                            logger.warning("File already exists at destination", src=str(src), dst=str(dst))
                    else:
                        shutil.move(str(src), str(dst))

                # Remove old dir if empty
                try:
                    old_dir.rmdir()
                except OSError:
                    pass
            else:
                # Simple move
                shutil.move(str(old_dir), str(new_dir))

        # Record all files that would be/were moved
        for root, _dirs, files in os.walk(new_dir if not dry_run else old_dir):
            for filename in files:
                if dry_run:
                    old_file_path = Path(root) / filename
                    rel_path = old_file_path.relative_to(old_dir)
                    new_file_path = new_dir / rel_path
                else:
                    new_file_path = Path(root) / filename
                    rel_path = new_file_path.relative_to(new_dir)
                    old_file_path = old_dir / rel_path

                old_full = f"/data/images/{order_id}/{rel_path}"
                new_full = f"/data/images/{shopify_id}/{rel_path}"
                moved_files[old_full] = new_full

    return moved_files


async def update_database(
    session: AsyncSession,
    order_id_to_shopify: dict[int, int],
    dry_run: bool = True,
) -> None:
    """Update database records with new storage paths."""
    _import_models()
    from app.models.coloring import ColoringVersion, SvgVersion
    from app.models.order import Image

    # Update images.local_path
    images_result = await session.execute(select(Image).where(Image.local_path.isnot(None)))  # type: ignore[union-attr]
    images = images_result.scalars().all()

    updated_images = 0
    for image in images:
        new_path = update_path(image.local_path, order_id_to_shopify)
        if new_path != image.local_path:
            logger.info(
                "Updating image path",
                image_id=image.id,
                old_path=image.local_path,
                new_path=new_path,
                dry_run=dry_run,
            )
            if not dry_run:
                image.local_path = new_path
            updated_images += 1

    # Update coloring_versions.file_path
    coloring_result = await session.execute(select(ColoringVersion).where(ColoringVersion.file_path.isnot(None)))  # type: ignore[union-attr]
    coloring_versions = coloring_result.scalars().all()

    updated_coloring = 0
    for cv in coloring_versions:
        new_path = update_path(cv.file_path, order_id_to_shopify)
        if new_path != cv.file_path:
            logger.info(
                "Updating coloring version path",
                coloring_version_id=cv.id,
                old_path=cv.file_path,
                new_path=new_path,
                dry_run=dry_run,
            )
            if not dry_run:
                cv.file_path = new_path
            updated_coloring += 1

    # Update svg_versions.file_path
    svg_result = await session.execute(select(SvgVersion).where(SvgVersion.file_path.isnot(None)))  # type: ignore[union-attr]
    svg_versions = svg_result.scalars().all()

    updated_svg = 0
    for sv in svg_versions:
        new_path = update_path(sv.file_path, order_id_to_shopify)
        if new_path != sv.file_path:
            logger.info(
                "Updating SVG version path",
                svg_version_id=sv.id,
                old_path=sv.file_path,
                new_path=new_path,
                dry_run=dry_run,
            )
            if not dry_run:
                sv.file_path = new_path
            updated_svg += 1

    if not dry_run:
        await session.commit()

    logger.info(
        "Database update summary",
        updated_images=updated_images,
        updated_coloring_versions=updated_coloring,
        updated_svg_versions=updated_svg,
        dry_run=dry_run,
    )


async def main(dry_run: bool = True) -> None:
    """Run the migration."""
    from app.config import settings

    logger.info("Starting storage path migration", dry_run=dry_run, storage_path=settings.storage_path)

    # Create async engine
    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Get order_id -> shopify_id mapping
        order_mapping = await get_order_mapping(session)
        logger.info("Found orders", count=len(order_mapping))

        for order_id, shopify_id in order_mapping.items():
            logger.info("Order mapping", order_id=order_id, shopify_id=shopify_id)

        # Move files
        storage_base = Path(settings.storage_path)
        await migrate_files(storage_base, order_mapping, dry_run=dry_run)

        # Update database
        await update_database(session, order_mapping, dry_run=dry_run)

    logger.info("Migration complete", dry_run=dry_run)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Migrate storage paths from order_id to shopify_id")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually execute the migration (default is dry-run)",
    )
    args = parser.parse_args()

    dry_run = not args.execute

    if not dry_run:
        confirm = input("This will move files and update the database. Type 'yes' to confirm: ")
        if confirm.lower() != "yes":
            logger.warning("Migration aborted by user")
            exit(1)

    asyncio.run(main(dry_run=dry_run))
