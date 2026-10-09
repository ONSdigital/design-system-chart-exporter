"""Fast S3 backend tests using botocore's built-in Stubber (no network).

The Stubber intercepts calls on a real boto3 client and asserts the exact
request parameters our code constructs — which is precisely what these tests
are about (Bucket/Key/ContentType/conditional ACL). The real wire protocol
is covered by the Floci integration tests (marked e2e).
"""

import boto3
import pytest
from botocore.exceptions import EndpointConnectionError
from botocore.stub import Stubber

from app.domain.exceptions import StorageError
from app.domain.models import StoredObject
from app.storage.s3 import S3StorageBackend


@pytest.fixture()
def s3_client():
    return boto3.client("s3", region_name="us-east-1")


def test_put_sends_private_acl_and_content_type(s3_client):
    backend = S3StorageBackend(bucket="ons-charts", set_private_acl=True, client=s3_client)
    with Stubber(s3_client) as stubber:
        stubber.add_response(
            "put_object",
            {},
            expected_params={
                "Bucket": "ons-charts",
                "Key": "charts/abc.png",
                "Body": b"png-bytes",
                "ContentType": "image/png",
                "ACL": "private",
            },
        )

        stored = backend.put(key="charts/abc.png", data=b"png-bytes", content_type="image/png")

        stubber.assert_no_pending_responses()
    assert stored == StoredObject(bucket="ons-charts", key="charts/abc.png", size_bytes=9, content_type="image/png")


def test_put_omits_acl_when_disabled(s3_client):
    """BucketOwnerEnforced buckets reject any ACL: the flag must omit it entirely."""
    backend = S3StorageBackend(bucket="ons-charts", set_private_acl=False, client=s3_client)
    with Stubber(s3_client) as stubber:
        stubber.add_response(
            "put_object",
            {},
            expected_params={
                "Bucket": "ons-charts",
                "Key": "charts/abc.png",
                "Body": b"png-bytes",
                "ContentType": "image/png",
            },
        )

        backend.put(key="charts/abc.png", data=b"png-bytes", content_type="image/png")

        stubber.assert_no_pending_responses()


def test_client_error_raises_storage_error(s3_client):
    backend = S3StorageBackend(bucket="ons-charts", client=s3_client)
    with Stubber(s3_client) as stubber:
        stubber.add_client_error("put_object", service_error_code="AccessDenied", http_status_code=403)

        with pytest.raises(StorageError, match=r"charts/abc\.png"):
            backend.put(key="charts/abc.png", data=b"x", content_type="image/png")


def test_builds_own_client_with_custom_endpoint():
    """Constructor path: a custom endpoint gets path-style addressing (no call made)."""
    backend = S3StorageBackend(bucket="ons-charts", region="eu-west-2", endpoint_url="http://floci:4566")

    assert backend._client.meta.endpoint_url == "http://floci:4566"
    assert backend._client.meta.config.s3 == {"addressing_style": "path"}


def test_builds_own_client_for_real_aws():
    """No endpoint_url: default addressing, no custom config (no call made)."""
    backend = S3StorageBackend(bucket="ons-charts", region="eu-west-2")

    assert backend._client.meta.endpoint_url.startswith("https://")
    assert backend._client.meta.config.s3 is None


def test_botocore_error_raises_storage_error():
    """Client-side failures (unreachable endpoint, no credentials) are BotoCoreError, not ClientError."""

    class UnreachableClient:
        def put_object(self, **kwargs):
            raise EndpointConnectionError(endpoint_url="http://floci:4566")

    backend = S3StorageBackend(bucket="ons-charts", client=UnreachableClient())

    with pytest.raises(StorageError, match=r"charts/abc\.png"):
        backend.put(key="charts/abc.png", data=b"x", content_type="image/png")


def test_private_acl_is_the_default(s3_client):
    """Without explicit configuration the safe behaviour (ACL=private) applies."""
    backend = S3StorageBackend(bucket="ons-charts", client=s3_client)
    with Stubber(s3_client) as stubber:
        stubber.add_response(
            "put_object",
            {},
            expected_params={
                "Bucket": "ons-charts",
                "Key": "charts/abc.png",
                "Body": b"x",
                "ContentType": "image/png",
                "ACL": "private",
            },
        )

        backend.put(key="charts/abc.png", data=b"x", content_type="image/png")

        stubber.assert_no_pending_responses()
