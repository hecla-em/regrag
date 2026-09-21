"""The curated params: every name and value still fits the live config."""

from app.core.config import Config
from app.evals.tune.params import TUNABLE_PARAMS


def test_every_curated_param_and_value_still_fits_the_config() -> None:
    """The drift gate: a renamed or retightened setting fails here, not mid-sweep."""
    for param in TUNABLE_PARAMS:
        param.validate_config()

    assert all(param.name in Config.model_fields for param in TUNABLE_PARAMS)
