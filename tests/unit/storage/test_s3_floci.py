"""S3 backend integration tests against the Floci emulator (docker compose).

Marked e2e: excluded from `make test`. Skipped with a loud reason when the
Floci container is not reachable — start it with `make up`.
"""

import socket
import uuid

import boto3
import pytest

from app.storage.s3 import S3StorageBackend

FLOCI_ENDPOINT = "http://localhost:4566"
BUCKET = "ons-charts"

pytestmark = pytest.mark.e2e


def _floci_reachable():
    try:
        with socket.create_connection(("localhost", 4566), timeout=1):
            return True
    except OSError:
        return False


@pytest.fixture(autouse=True)
def floci(monkeypatch):
    if not _floci_reachable():
        pytest.skip("Floci is not running on localhost:4566 — start it with `make up`")
    # Floci accepts any dummy credentials; never real ones here
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")


@pytest.fixture()
def backend():
    return S3StorageBackend(bucket=BUCKET, region="us-east-1", endpoint_url=FLOCI_ENDPOINT)


@pytest.fixture()
def verify_client():
    return boto3.client("s3", region_name="us-east-1", endpoint_url=FLOCI_ENDPOINT)


def test_put_roundtrip(backend, verify_client):
    """The object exists at charts/{id}.png with the right bytes and content type."""
    chart_id = uuid.uuid4()
    key = f"charts/{chart_id}.png"

    stored = backend.put(key=key, data=b"fake-png-bytes", content_type="image/png")

    assert stored.bucket == BUCKET
    assert stored.key == key
    fetched = verify_client.get_object(Bucket=BUCKET, Key=key)
    assert fetched["Body"].read() == b"fake-png-bytes"
    assert fetched["ContentType"] == "image/png"


def test_no_public_acl_applied(backend, verify_client):
    """ACL=private means no AllUsers/AuthenticatedUsers grants on the object."""
    key = f"charts/{uuid.uuid4()}.png"
    backend.put(key=key, data=b"x", content_type="image/png")

    acl = verify_client.get_object_acl(Bucket=BUCKET, Key=key)

    public_grantees = [
        grant
        for grant in acl["Grants"]
        if "AllUsers" in grant["Grantee"].get("URI", "") or "AuthenticatedUsers" in grant["Grantee"].get("URI", "")
    ]
    assert public_grantees == []
