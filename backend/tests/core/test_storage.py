"""Object storage: the seam's key rules, both backends' behaviour, backend selection."""

from io import BytesIO
from typing import Any

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from pydantic import ValidationError

from app.core import storage
from app.core.config import StorageBackend
from app.core.exceptions import DomainError
from app.core.storage import (
    LocalObjectStore,
    ObjectNotFoundError,
    S3ObjectStore,
    StorageError,
    get_object_store,
    r2_object_store,
)
from tests.conftest import R2_ENV, r2_config

KEY = "32023R1805/32023R1805/abc.html"
HTML = b"<html>act</html>"


def test_put_then_get_round_trips(local_store: LocalObjectStore):
    local_store.put(KEY, HTML)
    assert local_store.get(KEY) == HTML


def test_put_creates_the_directories_the_key_names(local_store: LocalObjectStore):
    local_store.put(KEY, HTML)
    assert (local_store.root / KEY).read_bytes() == HTML


def test_exists_is_false_before_put_and_true_after(local_store: LocalObjectStore):
    assert not local_store.exists(KEY)
    local_store.put(KEY, HTML)
    assert local_store.exists(KEY)


def test_get_of_a_missing_key_raises_storage_error(local_store: LocalObjectStore):
    with pytest.raises(StorageError, match="get failed"):
        local_store.get(KEY)


def test_a_key_with_nothing_at_it_is_absent_rather_than_a_failed_store(
    local_store: LocalObjectStore,
):
    """Callers that can recover from an absent object must not recover from an unreachable store."""
    with pytest.raises(ObjectNotFoundError):
        local_store.get(KEY)


def test_a_local_store_that_cannot_be_read_is_not_reported_as_absent(
    local_store: LocalObjectStore,
):
    local_store.put(KEY, HTML)
    (local_store.root / KEY).chmod(0o000)
    with pytest.raises(StorageError) as raised:
        local_store.get(KEY)
    assert not isinstance(raised.value, ObjectNotFoundError)


def test_a_failed_operation_names_what_refused_it(local_store: LocalObjectStore):
    """The run row records only this message, so the cause has to be in it."""
    with pytest.raises(StorageError, match="No such file or directory"):
        local_store.get(KEY)


def test_a_storage_failure_is_a_domain_error(local_store: LocalObjectStore):
    """Serving a stored document must fail in the one shape every handler returns."""
    with pytest.raises(DomainError):
        local_store.get(KEY)


def test_put_replaces_the_object_already_at_the_key(local_store: LocalObjectStore):
    local_store.put(KEY, HTML)
    local_store.put(KEY, b"<html>newer</html>")
    assert local_store.get(KEY) == b"<html>newer</html>"


@pytest.mark.parametrize("key", ["../../etc/passwd", "/etc/passwd", "a/./b.html", ""])
def test_a_key_that_is_not_a_plain_relative_path_is_refused(local_store: LocalObjectStore, key):
    with pytest.raises(StorageError, match="access failed"):
        local_store.get(key)


def test_exists_refuses_such_a_key_rather_than_calling_it_absent(local_store: LocalObjectStore):
    """Both backends have to agree here, so exists must not quietly answer for a bad key."""
    with pytest.raises(StorageError, match="access failed"):
        local_store.exists("../../etc/passwd")


class FakeS3:
    """Records calls and answers from a dict, raising whatever the client is scripted to raise."""

    def __init__(self, objects: dict[str, bytes] | None = None):
        self.objects = objects or {}
        self.calls: list[tuple[str, str]] = []
        self.error: Exception | None = None

    def _record(self, operation: str, key: str) -> None:
        self.calls.append((operation, key))
        if self.error is not None:
            raise self.error

    def put_object(self, *, Bucket: str, Key: str, Body: bytes) -> None:
        self._record("put_object", Key)
        self.objects[Key] = Body

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        self._record("get_object", Key)
        if Key not in self.objects:
            raise not_found()
        return {"Body": BytesIO(self.objects[Key])}

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        self._record("head_object", Key)
        if Key not in self.objects:
            raise not_found()
        return {}


def not_found() -> ClientError:
    return ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")


def denied() -> ClientError:
    return ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, "HeadObject")


def s3_store(objects: dict[str, bytes] | None = None) -> S3ObjectStore:
    return S3ObjectStore(FakeS3(objects), "regrag-raw")


def failing_s3(error: Exception) -> S3ObjectStore:
    client = FakeS3()
    client.error = error
    return S3ObjectStore(client, "regrag-raw")


def test_s3_put_then_get_round_trips():
    store = s3_store()
    store.put(KEY, HTML)
    assert store.get(KEY) == HTML


def test_s3_put_targets_the_configured_bucket():
    client = FakeS3()
    S3ObjectStore(client, "regrag-raw").put(KEY, HTML)
    assert client.calls == [("put_object", KEY)]


def test_s3_exists_reads_a_missing_object_as_absent_not_an_error():
    assert s3_store().exists(KEY) is False


def test_s3_exists_is_true_for_a_stored_object():
    assert s3_store({KEY: HTML}).exists(KEY) is True


def test_s3_exists_surfaces_a_non_404_client_error():
    with pytest.raises(StorageError, match="head failed"):
        failing_s3(denied()).exists(KEY)


def test_s3_exists_surfaces_a_transport_failure():
    with pytest.raises(StorageError, match="head failed"):
        failing_s3(EndpointConnectionError(endpoint_url="https://r2.example")).exists(KEY)


def test_s3_get_of_a_missing_object_raises_storage_error():
    with pytest.raises(StorageError, match="get failed"):
        s3_store().get(KEY)


def test_s3_get_of_a_missing_object_is_absent_rather_than_a_failed_store():
    with pytest.raises(ObjectNotFoundError):
        s3_store().get(KEY)


def test_s3_get_that_is_refused_is_not_reported_as_absent():
    """A rotated credential answers every read the same way: an outage, not an empty bucket."""
    with pytest.raises(StorageError) as raised:
        failing_s3(denied()).get(KEY)
    assert not isinstance(raised.value, ObjectNotFoundError)


def test_s3_put_failure_raises_storage_error():
    with pytest.raises(StorageError, match="put failed"):
        failing_s3(EndpointConnectionError(endpoint_url="https://r2.example")).put(KEY, HTML)


def test_s3_failure_names_the_botocore_cause():
    """An operator reading the run row has only this message to tell AccessDenied from a 404."""
    with pytest.raises(StorageError, match="AccessDenied"):
        failing_s3(denied()).exists(KEY)


def test_s3_refuses_a_key_that_is_not_a_plain_relative_path():
    """The local backend refuses these, so the S3 backend must not silently accept them."""
    with pytest.raises(StorageError, match="access failed"):
        s3_store().put("../../etc/passwd", HTML)


def test_an_unusable_endpoint_fails_as_a_storage_error(monkeypatch):
    """The CLI contracts on StorageError, so boto3's ValueError must not escape as-is."""
    r2_config(monkeypatch, R2_ACCOUNT_ID="not a host")

    with pytest.raises(StorageError, match="connect failed"):
        r2_object_store()


def test_the_default_backend_is_local_and_rooted_at_the_raw_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage.config, "STORAGE_BACKEND", StorageBackend.LOCAL)
    monkeypatch.setattr(storage.config, "RAW_DATA_DIR", tmp_path)
    store = get_object_store()
    assert isinstance(store, LocalObjectStore)
    assert store.root == tmp_path.resolve()


def test_the_r2_backend_is_an_s3_store_on_the_configured_bucket(monkeypatch):
    monkeypatch.setattr(storage.config, "STORAGE_BACKEND", StorageBackend.R2)
    monkeypatch.setattr(storage, "r2_client", lambda r2: FakeS3())
    for name, value in R2_ENV.items():
        monkeypatch.setenv(name, value)

    store = get_object_store()

    assert isinstance(store, S3ObjectStore)
    assert store.bucket == "regrag-raw"


def test_selecting_r2_without_its_credentials_fails_before_any_work(monkeypatch):
    """The store is built before the run opens, so a misconfigured bucket stops it there."""
    monkeypatch.setattr(storage.config, "STORAGE_BACKEND", StorageBackend.R2)
    for name in R2_ENV:
        monkeypatch.setenv(name, "")

    with pytest.raises(ValidationError, match="R2_BUCKET"):
        get_object_store()
