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
    endpoint_url: str | None = None,
    connect_timeout: float = 3,
    read_timeout: float = 10,
    total_attempts: int = 3,
) -> S3Client:
    """An S3 client for the configured storage.

    Path-style addressing, because RustFS (D9) needs it. Each client gets its own boto3
    session: boto3's shared default session is not safe to use from several threads.
    Clients themselves are thread-safe and should be created once and reused.
    """
    return boto3.session.Session().client(
        "s3",
        endpoint_url=endpoint_url or settings.s3_endpoint_url,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            # total_max_attempts counts the first try; botocore's max_attempts would not.
            retries={"mode": "standard", "total_max_attempts": total_attempts},
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
        ),
    )


def presign_client(settings: Settings) -> S3Client:
    """Signs links for browsers. It never connects anywhere: links are signed for the
    public storage address (settings.s3_public_url), which browsers can reach."""
    return s3_client(settings, endpoint_url=settings.s3_public_url)
