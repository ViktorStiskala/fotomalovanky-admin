"""S3 storage service for file operations.

This module provides an S3 storage implementation using aioboto3.
Compatible with MinIO (local development) and Cloudflare R2 / AWS S3 (production).
"""

import hashlib
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import aioboto3
import structlog
from botocore.config import Config

from app.config import settings
from app.models.types import S3ObjectRefData

logger = structlog.get_logger(__name__)


class S3StorageService:
    """S3-compatible object storage service (MinIO/R2/AWS S3)."""

    def __init__(self) -> None:
        """Initialize S3 storage service using settings."""
        self.endpoint_url = settings.s3_endpoint
        self.access_key_id = settings.s3_access_key_id
        self.secret_access_key = settings.s3_secret_access_key
        self.bucket = settings.s3_bucket
        self.region = settings.s3_region
        self.force_path_style = settings.s3_force_path_style
        self.public_url = settings.s3_public_url
        self._session = aioboto3.Session()

    @asynccontextmanager
    async def _get_client(self) -> AsyncIterator[Any]:
        """Get an S3 client from the session."""
        config = Config(s3={"addressing_style": "path"}) if self.force_path_style else None
        async with self._session.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
            region_name=self.region,
            config=config,
        ) as client:
            yield client

    async def upload(
        self,
        upload_to: str,
        data: bytes,
        content_type: str,
        original_filename: str | None = None,
    ) -> S3ObjectRefData:
        """Upload file to S3 and return object reference.

        Args:
            upload_to: S3 key (path within bucket)
            data: File contents as bytes
            content_type: MIME type of the file
            original_filename: Original filename (for metadata)

        Returns:
            S3ObjectRefData with all metadata
        """
        async with self._get_client() as client:
            response = await client.put_object(
                Bucket=self.bucket,
                Key=upload_to,
                Body=data,
                ContentType=content_type,
            )

        etag = response.get("ETag", "").strip('"')
        sha256 = hashlib.sha256(data).hexdigest()

        logger.info("Uploaded file to S3", key=upload_to, size=len(data), content_type=content_type)

        return S3ObjectRefData(
            key=upload_to,
            bucket=self.bucket,
            content_type=content_type,
            size=len(data),
            etag=etag,
            sha256=sha256,
            original_filename=original_filename,
        )

    async def download(self, file_ref: S3ObjectRefData) -> bytes:
        """Download file from S3.

        Args:
            file_ref: S3 object reference

        Returns:
            File contents as bytes
        """
        async with self._get_client() as client:
            response = await client.get_object(Bucket=file_ref.bucket, Key=file_ref.key)
            data: bytes = await response["Body"].read()

        logger.debug("Downloaded file from S3", key=file_ref.key, size=len(data))
        return data

    async def download_to_path(self, file_ref: S3ObjectRefData, local_path: str) -> None:
        """Download file from S3 to local path.

        Useful for RunPod processing that requires local files.

        Args:
            file_ref: S3 object reference
            local_path: Local filesystem path to save to
        """
        data = await self.download(file_ref)
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        Path(local_path).write_bytes(data)
        logger.debug("Downloaded file to local path", key=file_ref.key, local_path=local_path)

    def get_public_url(self, file_ref: S3ObjectRefData | None) -> str | None:
        """Get public URL for S3 object.

        Args:
            file_ref: S3 object reference (or None)

        Returns:
            Public URL for browser access, or None if file_ref is None

        Note:
            Requires S3_PUBLIC_URL environment variable to be set.
            For MinIO: http://localhost:9000/fotomalovanky
            For R2/CloudFront: https://cdn.example.com
        """
        if not file_ref:
            return None
        return f"{self.public_url.rstrip('/')}/{file_ref.key}"

    async def get_presigned_url(self, file_ref: S3ObjectRefData, expires_in: int = 3600) -> str:
        """Generate presigned URL for S3 object.

        Args:
            file_ref: S3 object reference
            expires_in: URL expiration time in seconds (default: 1 hour)

        Returns:
            Presigned URL with temporary access
        """
        async with self._get_client() as client:
            url: str = await client.generate_presigned_url(
                "get_object",
                Params={"Bucket": file_ref.bucket, "Key": file_ref.key},
                ExpiresIn=expires_in,
            )
        return url

    async def exists(self, file_ref: S3ObjectRefData) -> bool:
        """Check if object exists in S3.

        Args:
            file_ref: S3 object reference

        Returns:
            True if object exists
        """
        async with self._get_client() as client:
            try:
                await client.head_object(Bucket=file_ref.bucket, Key=file_ref.key)
                return True
            except client.exceptions.ClientError:
                return False

    async def delete(self, file_ref: S3ObjectRefData) -> None:
        """Delete object from S3.

        Args:
            file_ref: S3 object reference
        """
        async with self._get_client() as client:
            await client.delete_object(Bucket=file_ref.bucket, Key=file_ref.key)
        logger.info("Deleted file from S3", key=file_ref.key)

    async def ensure_bucket_exists(self) -> None:
        """Ensure the S3 bucket exists, creating it if necessary.

        Called during application startup.
        """
        async with self._get_client() as client:
            try:
                await client.head_bucket(Bucket=self.bucket)
                logger.info("S3 bucket exists", bucket=self.bucket)
            except Exception:
                # Bucket doesn't exist, create it
                try:
                    await client.create_bucket(Bucket=self.bucket)
                    logger.info("Created S3 bucket", bucket=self.bucket)

                    # Set bucket policy for public read (MinIO)
                    policy = {
                        "Version": "2012-10-17",
                        "Statement": [
                            {
                                "Effect": "Allow",
                                "Principal": "*",
                                "Action": ["s3:GetObject"],
                                "Resource": [f"arn:aws:s3:::{self.bucket}/*"],
                            }
                        ],
                    }
                    import json

                    await client.put_bucket_policy(Bucket=self.bucket, Policy=json.dumps(policy))
                    logger.info("Set bucket policy for public read", bucket=self.bucket)
                except Exception as e:
                    logger.error("Failed to create S3 bucket", bucket=self.bucket, error=str(e))
                    raise
