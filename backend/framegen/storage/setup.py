"""Creates the storage bucket if it does not exist. Run once when the deployment starts."""

import logging
import time

from botocore.exceptions import BotoCoreError, ClientError

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
        if _error_code(error) not in ("404", "NoSuchBucket", "NotFound"):
            raise
    try:
        if settings.s3_region == "us-east-1":
            client.create_bucket(Bucket=settings.s3_bucket)
        else:
            # S3 servers that check regions require the region to be named.
            client.create_bucket(
                Bucket=settings.s3_bucket,
                CreateBucketConfiguration={"LocationConstraint": settings.s3_region},  # type: ignore[typeddict-item]
            )
    except ClientError as error:
        # Another setup run created it between our check and our create.
        if _error_code(error) in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            return False
        raise
    return True


def _error_code(error: ClientError) -> str:
    return str(error.response.get("Error", {}).get("Code", ""))


def _is_transient(error: Exception) -> bool:
    """Worth retrying: the storage is not reachable yet or answered with a server error."""
    if isinstance(error, BotoCoreError):
        return True  # connection refused, timeouts, endpoint not reachable
    if isinstance(error, ClientError):
        status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
        return status >= 500
    return False


def main(attempts: int = 6, first_wait: float = 1.0) -> None:
    """Creates the bucket, retrying while storage is starting up (about 30 s in all).

    Errors that waiting cannot fix, such as wrong credentials, fail at once.
    """
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    wait = first_wait
    for attempt in range(1, attempts + 1):
        try:
            created = ensure_bucket(settings)
        except Exception as error:
            if attempt == attempts or not _is_transient(error):
                raise
            log.warning("storage not ready (%s); retrying in %.0f s", error, wait)
            time.sleep(wait)
            wait *= 2
            continue
        log.info("bucket %s %s", settings.s3_bucket, "created" if created else "already exists")
        return
