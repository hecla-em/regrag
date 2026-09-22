"""Object storage behind one S3-compatible interface: R2 in prod, local files in dev and tests."""

import logging
from pathlib import Path
from typing import Any, Protocol

import boto3
from boto3.exceptions import S3UploadFailedError
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import status

from app.core.config import R2Config, StorageBackend, config
from app.core.exceptions import DomainError, ErrorCode
from app.core.retry import MAX_ATTEMPTS

BOTO_ERRORS = (ClientError, BotoCoreError, S3UploadFailedError)
NOT_FOUND_CODES = frozenset({"404", "NoSuchKey", "NotFound"})


class StorageError(DomainError):
    """An object storage operation failed, named by the operation and what refused it."""

    status_code = status.HTTP_502_BAD_GATEWAY
    code = ErrorCode.STORAGE
    log_level = logging.ERROR

    def __init__(self, operation: str, key: str, reason: object | None = None):
        detail = f": {reason}" if reason is not None else ""
        super().__init__(f"Storage {operation} failed for '{key}'{detail}")


class ObjectNotFoundError(StorageError):
    """Nothing is stored at the key, which the store answered rather than failed to answer."""

    code = ErrorCode.OBJECT_NOT_FOUND


def is_missing_object(exc: ClientError) -> bool:
    """Whether the error says the object is not there, rather than that the read failed."""
    return exc.response.get("Error", {}).get("Code") in NOT_FOUND_CODES


def validate_key(key: str) -> None:
    """Refuse anything but a plain relative path, so both backends accept the same keys.

    Split on the raw string, not a path type: S3 keeps '.' and '' segments literally,
    so a key the local backend would normalise is a different object there.
    """
    if not key or {"", ".", ".."} & set(key.split("/")):
        raise StorageError("access", key, "key is not a plain relative path")


class ObjectStore(Protocol):
    """The object operations the pipeline needs, whichever backend serves them."""

    def put(self, key: str, content: bytes) -> None:
        """Write an object, replacing any object already at the key."""
        ...

    def get(self, key: str) -> bytes:
        """Read an object's bytes, raising StorageError if it is not there."""
        ...

    def exists(self, key: str) -> bool:
        """Whether an object is stored at the key."""
        ...


class LocalObjectStore:
    """Objects as files under a root directory, so dev and tests need no network."""

    def __init__(self, root: Path):
        self.root = root.resolve()

    def _path(self, key: str) -> Path:
        """The file a key names, once the key is known to stay inside the root."""
        validate_key(key)
        return self.root / key

    def put(self, key: str, content: bytes) -> None:
        path = self._path(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        except OSError as exc:
            raise StorageError("put", key, exc) from exc

    def get(self, key: str) -> bytes:
        path = self._path(key)
        try:
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise ObjectNotFoundError("get", key, exc) from exc
        except OSError as exc:
            raise StorageError("get", key, exc) from exc

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()


class S3ObjectStore:
    """Objects in an S3-compatible bucket; R2 is the one this project points it at."""

    def __init__(self, client: Any, bucket: str):
        self.client = client
        self.bucket = bucket

    def put(self, key: str, content: bytes) -> None:
        validate_key(key)
        try:
            self.client.put_object(Bucket=self.bucket, Key=key, Body=content)
        except BOTO_ERRORS as exc:
            raise StorageError("put", key, exc) from exc

    def put_file(self, key: str, path: Path) -> None:
        """Upload from disk in parts, for a file too large to hold in memory."""
        validate_key(key)
        try:
            self.client.upload_file(str(path), self.bucket, key)
        except BOTO_ERRORS as exc:
            raise StorageError("put", key, exc) from exc

    def get_file(self, key: str, path: Path) -> None:
        """Download to disk in parts, for a file too large to hold in memory."""
        validate_key(key)
        try:
            self.client.download_file(self.bucket, key, str(path))
        except ClientError as exc:
            if is_missing_object(exc):
                raise ObjectNotFoundError("get", key, exc) from exc
            raise StorageError("get", key, exc) from exc
        except BotoCoreError as exc:
            raise StorageError("get", key, exc) from exc

    def get(self, key: str) -> bytes:
        validate_key(key)
        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except ClientError as exc:
            if is_missing_object(exc):
                raise ObjectNotFoundError("get", key, exc) from exc
            raise StorageError("get", key, exc) from exc
        except BotoCoreError as exc:
            raise StorageError("get", key, exc) from exc

    def exists(self, key: str) -> bool:
        validate_key(key)
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if is_missing_object(exc):
                return False
            raise StorageError("head", key, exc) from exc
        except BotoCoreError as exc:
            raise StorageError("head", key, exc) from exc
        return True

    def list_keys(self, prefix: str) -> list[str]:
        """Every key that starts with the prefix."""
        pages = self.client.get_paginator("list_objects_v2").paginate(
            Bucket=self.bucket, Prefix=prefix
        )
        try:
            return [item["Key"] for page in pages for item in page.get("Contents", [])]
        except BOTO_ERRORS as exc:
            raise StorageError("list", prefix, exc) from exc


def r2_client(r2: R2Config) -> Any:
    """An S3 client pointed at this account's R2 endpoint, retrying transient failures."""
    return boto3.client(
        "s3",
        endpoint_url=r2.R2_ENDPOINT_URL,
        aws_access_key_id=r2.R2_ACCESS_KEY_ID,
        aws_secret_access_key=r2.R2_SECRET_ACCESS_KEY,
        region_name="auto",
        config=BotoConfig(retries={"mode": "standard", "max_attempts": MAX_ATTEMPTS}),
    )


def r2_object_store(r2: R2Config | None = None) -> S3ObjectStore:
    """An R2 bucket as an object store: the raw-docs one unless handed other settings, its
    credentials read as it is built."""
    r2 = r2 or R2Config()
    try:
        client = r2_client(r2)
    except ValueError as exc:
        raise StorageError("connect", r2.R2_BUCKET, exc) from exc
    return S3ObjectStore(client, r2.R2_BUCKET)


def get_object_store() -> ObjectStore:
    """The store this environment is configured for; R2 credentials are read only if selected."""
    match config.STORAGE_BACKEND:
        case StorageBackend.LOCAL:
            return LocalObjectStore(config.RAW_DATA_DIR)
        case StorageBackend.R2:
            return r2_object_store()
