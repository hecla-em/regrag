"""Context formatting: numbered blocks the citation markers bind to, under the acts they
come from."""

import pytest

from app.chat.prompts import format_context
from tests.conftest import retrieved_chunk

FUELEU = "Regulation (EU) 2023/1805 on renewable and low-carbon fuels in maritime transport"
MRV = "Regulation (EU) 2015/757 on monitoring, reporting and verification of CO2 emissions"


@pytest.mark.parametrize(
    ("acts", "opening"),
    [
        pytest.param(
            [("32015R0757", MRV), ("32023R1805", FUELEU), ("32015R0757", MRV)],
            f"Acts:\nRegulation (EU) 2015/757: {MRV}\nRegulation (EU) 2023/1805: {FUELEU}\n\n"
            "[1] (Regulation (EU) 2015/757, Article 4(1))\n",
            id="each act is named once, in order of first appearance",
        ),
        pytest.param(
            [("32015R0757", None), ("32023R1805", FUELEU)],
            f"Acts:\nRegulation (EU) 2023/1805: {FUELEU}\n\n"
            "[1] (Regulation (EU) 2015/757, Article 4(1))\n",
            id="an act without a stored title is left off, its block still named by number",
        ),
        pytest.param(
            [("32023R1805", None)],
            "[1] (Regulation (EU) 2023/1805, Article 4(1))\n",
            id="no titles means no legend",
        ),
    ],
)
def test_the_context_opens_with_a_legend_of_the_acts_it_draws_on(acts, opening):
    """The full title is long, so it is given once per act rather than on every block; the
    block headers carry the short name the legend keys on."""
    sources = tuple(
        retrieved_chunk(id=n, celex=celex, act_title=title)
        for n, (celex, title) in enumerate(acts, start=1)
    )

    assert format_context(sources).startswith(opening)
