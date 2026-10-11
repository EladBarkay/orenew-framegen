"""Creates the storage bucket if it does not exist. Run once when the deployment starts."""

import logging

from botocore.exceptions import ClientError

from framegen.settings import Settings, get_settings
from framegen.storage.client import s3_client

log = logging.getLogger("framegen.storage")


def ensure_bucket(settings: Settings) -> bool:
    """Returns True if the bucket was created, False if it already existed."""
    client = s3_client(settings)
    try:
        client.head_bucket(Bucket=settings.s3_bucket)
        return False
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") not in ("404", "NoSuchBucket", "NotFound"):
            raise
    if settings.s3_region == "us-east-1":
        client.create_bucket(Bucket=settings.s3_bucket)
    else:
        # S3 servers that check regions require the region to be named.
        client.create_bucket(
            Bucket=settings.s3_bucket,
            CreateBucketConfiguration={"LocationConstraint": settings.s3_region},  # type: ignore[typeddict-item]
        )
    return True


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    created = ensure_bucket(settings)
    log.info("bucket %s %s", settings.s3_bucket, "created" if created else "already exists")
