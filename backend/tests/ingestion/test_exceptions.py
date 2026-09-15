"""Every ingestion failure is catchable as one family."""

import pytest

from app.ingestion.exceptions import (
    CorpusShrankError,
    DiscoveryError,
    EmptyDownloadError,
    IngestionError,
    MalformedDiscoveryError,
    NoFetchableVersionError,
    ParseError,
)


@pytest.mark.parametrize(
    "error",
    [
        MalformedDiscoveryError,
        CorpusShrankError,
        NoFetchableVersionError,
        EmptyDownloadError,
        ParseError,
    ],
)
def test_ingestion_failures_share_a_base(error: type[IngestionError]) -> None:
    with pytest.raises(IngestionError):
        raise error("boom")


@pytest.mark.parametrize("error", [MalformedDiscoveryError, CorpusShrankError])
def test_discovery_failures_share_a_base(error: type[DiscoveryError]) -> None:
    with pytest.raises(DiscoveryError):
        raise error("boom")


def test_ingestion_errors_are_not_domain_errors() -> None:
    from app.core.exceptions import DomainError

    assert not issubclass(IngestionError, DomainError)
