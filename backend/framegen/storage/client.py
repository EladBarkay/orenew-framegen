from __future__ import annotations

from typing import TYPE_CHECKING

import boto3
from botocore.client import Config

from framegen.settings import Settings

if TYPE_CHECKING:
    # Type stubs are a development dependency only.
    from mypy_boto3_s3 import S3Client


def s3_client(settings: Settings) -> S3Client:
    """An S3 client for the configured storage. Path-style addressing: RustFS (D9) needs it."""
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 2}),
    )
