"""Object storage: the seam's key rules, both backends' behaviour, backend selection."""

from io import BytesIO
from typing import Any

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from app.core import storage
from app.core.config import StorageBackend
from app.core.storage import (
    LocalObjectStore,
    ObjectNotFoundError,
    S3ObjectStore,
    StorageError,
    get_object_store,
)

KEY = "32023R1805/32023R1805/abc.html"
HTML = b"<html>act</html>"


class FakeS3:
    """Answers from a dict, raising whatever the client is scripted to raise."""

    def __init__(self, objects: dict[str, bytes] | None = None):
        self.objects = objects or {}
        self.error: Exception | None = None

    def _raise_scripted(self) -> None:
        if self.error is not None:
            raise self.error

    def put_object(self, *, Bucket: str, Key: str, Body: bytes) -> None:
        self._raise_scripted()
        self.objects[Key] = Body

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        self._raise_scripted()
        if Key not in self.objects:
            raise not_found()
        return {"Body": BytesIO(self.objects[Key])}

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        self._raise_scripted()
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


def unreadable(local_store: LocalObjectStore) -> LocalObjectStore:
    local_store.put(KEY, HTML)
    (local_store.root / KEY).chmod(0o000)
    return local_store


@pytest.mark.parametrize(
    ("store_of", "absent"),
    [
        pytest.param(lambda local: local, True, id="local: nothing at the key"),
        pytest.param(unreadable, False, id="local: a file that cannot be read"),
        pytest.param(lambda local: s3_store(), True, id="s3: no such object"),
        pytest.param(lambda local: failing_s3(denied()), False, id="s3: a refused read"),
    ],
)
def test_an_absent_object_is_told_apart_from_a_store_that_failed(
    local_store: LocalObjectStore, store_of, absent: bool
):
    """Callers recover from an absent object and must not recover from an unreachable store:
    a rotated credential answers every read the same way, an outage and not an empty bucket."""
    with pytest.raises(StorageError) as raised:
        store_of(local_store).get(KEY)

    assert isinstance(raised.value, ObjectNotFoundError) is absent


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(None, id="a missing object is absent"),
        pytest.param(denied(), id="a refused head is a failure"),
        pytest.param(
            EndpointConnectionError(endpoint_url="https://r2.example"),
            id="so is an unreachable endpoint",
        ),
    ],
)
def test_s3_exists_answers_false_only_for_a_missing_object(error: Exception | None):
    if error is None:
        assert s3_store().exists(KEY) is False
        return
    with pytest.raises(StorageError, match="head failed"):
        failing_s3(error).exists(KEY)


@pytest.mark.parametrize(
    "touch",
    [
        pytest.param(lambda local, key: local.get(key), id="local get"),
        pytest.param(lambda local, key: local.exists(key), id="local exists"),
        pytest.param(lambda local, key: s3_store().put(key, HTML), id="s3 put"),
    ],
)
def test_a_key_that_is_not_a_plain_relative_path_is_refused_by_both_backends(
    local_store: LocalObjectStore, touch
):
    """exists included: it must not quietly answer absent for a key it would never look up."""
    for key in ("../../etc/passwd", "/etc/passwd", "a/./b.html", ""):
        with pytest.raises(StorageError, match="access failed"):
            touch(local_store, key)


def test_the_r2_backend_is_an_s3_store_on_the_configured_bucket(monkeypatch):
    monkeypatch.setattr(storage.config, "STORAGE_BACKEND", StorageBackend.R2)
    monkeypatch.setattr(storage, "r2_client", lambda r2: FakeS3())
    monkeypatch.setenv("R2_ACCOUNT_ID", "acc")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "key")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("R2_BUCKET", "regrag-raw")

    store = get_object_store()

    assert isinstance(store, S3ObjectStore)
    assert store.bucket == "regrag-raw"
