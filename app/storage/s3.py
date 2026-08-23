"""S3 storage backend (real AWS or a local emulator via endpoint_url).

- One boto3 client per backend instance, created once: boto3 clients are
  thread-safe for our use, and the service creates one backend per process.
- Credentials come from the standard AWS environment variables or the pod
  IAM role — this module has no credential parameters by design.
- With a custom endpoint (Floci locally) path-style addressing is used, the
  standard practice for local emulators; against real AWS the default
  (virtual-hosted) style applies.
- The ACL parameter is conditional on config: buckets in BucketOwnerEnforced
  mode reject PutObject calls that carry any ACL (open question with the
  platform team), so ``set_private_acl`` keeps us compatible both ways.
  No public ACL is EVER set by this service.
"""

from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.domain.exceptions import StorageError
from app.domain.models import StoredObject
from app.logging import get_logger

log = get_logger()


class S3StorageBackend:  # pylint: disable=too-few-public-methods
    """StorageBackend implementation backed by S3-compatible object storage."""

    def __init__(
        self,
        *,
        bucket: str,
        region: str | None = None,
        endpoint_url: str | None = None,
        set_private_acl: bool = True,
        client: Any | None = None,
    ) -> None:
        """Create the backend and its boto3 client.

        Args:
            bucket: Target bucket name.
            region: AWS region; None defers to the default resolution chain.
            endpoint_url: Custom S3 endpoint (Floci locally); None means real AWS.
            set_private_acl: Whether PutObject sends ACL=private (see module docs).
            client: Pre-built S3 client, injected by tests (botocore Stubber).
        """
        self._bucket = bucket
        self._set_private_acl = set_private_acl
        if client is None:
            config = Config(s3={"addressing_style": "path"}) if endpoint_url else None
            client = boto3.client("s3", region_name=region, endpoint_url=endpoint_url, config=config)
        self._client = client

    def put(self, *, key: str, data: bytes, content_type: str) -> StoredObject:
        """Upload the bytes with put_object and return the object metadata.

        Raises:
            StorageError: on any boto3/botocore failure. The boto detail goes
                to the exception message (logs only — never client responses).
        """
        params: dict[str, Any] = {"Bucket": self._bucket, "Key": key, "Body": data, "ContentType": content_type}
        if self._set_private_acl:
            params["ACL"] = "private"
        try:
            self._client.put_object(**params)
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(f"S3 upload failed for key '{key}': {exc}") from exc
        return StoredObject(bucket=self._bucket, key=key, size_bytes=len(data), content_type=content_type)
