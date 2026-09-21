"""Context formatting: numbered blocks the citation markers bind to, under the acts they
come from."""

from app.chat.prompts import format_context
from tests.conftest import retrieved_chunk

FUELEU = "Regulation (EU) 2023/1805 on renewable and low-carbon fuels in maritime transport"
MRV = "Regulation (EU) 2015/757 on monitoring, reporting and verification of CO2 emissions"


def test_context_opens_with_each_act_named_once_in_order_of_first_appearance():
    """The full title is long, so it is given once per act rather than on every block; the
    block headers carry the short name the legend keys on."""
    sources = (
        retrieved_chunk(id=1, celex="32015R0757", act_title=MRV),
        retrieved_chunk(id=2, act_title=FUELEU),
        retrieved_chunk(id=3, celex="32015R0757", act_title=MRV, citation="Article 5"),
    )
    context = format_context(sources)
    legend, blocks = context.split("\n\n", 1)
    assert legend == (
        f"Acts:\nRegulation (EU) 2015/757: {MRV}\nRegulation (EU) 2023/1805: {FUELEU}"
    )
    assert blocks.startswith("[1] (Regulation (EU) 2015/757, Article 4(1))\n")


def test_an_act_without_a_stored_title_is_left_off_the_legend():
    """A corpus ingested before titles were stored has none; the block header still names
    the act by number."""
    sources = (retrieved_chunk(id=1, act_title=None), retrieved_chunk(id=2, act_title=FUELEU))
    context = format_context(sources)
    assert context.startswith(f"Acts:\nRegulation (EU) 2023/1805: {FUELEU}\n\n[1] (")


def test_no_titles_means_no_legend():
    context = format_context((retrieved_chunk(act_title=None),))
    assert context.startswith("[1] (Regulation (EU) 2023/1805, Article 4(1))\n")
