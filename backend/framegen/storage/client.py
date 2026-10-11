from __future__ import annotations

from typing import TYPE_CHECKING

import boto3
from botocore.client import Config

from framegen.settings import Settings

if TYPE_CHECKING:
    # Type stubs are a development dependency only.
    from mypy_boto3_s3 import S3Client


def s3_client(
    settings: Settings,
    *,
    connect_timeout: float = 3,
    read_timeout: float = 10,
    max_attempts: int = 2,
) -> S3Client:
    """An S3 client for the configured storage.

    Path-style addressing, because RustFS (D9) needs it. Each client gets its own boto3
    session: boto3's shared default session is not safe to use from several threads.
    Clients themselves are thread-safe and should be created once and reused.
    """
    return boto3.session.Session().client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        config=Config(
            s3={"addressing_style": "path"},
            retries={"mode": "standard", "max_attempts": max_attempts},
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
        ),
    )
