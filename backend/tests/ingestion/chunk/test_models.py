from tests.conftest import chunk


def test_differing_text_hashes_differently():
    assert chunk().content_hash != chunk(text="Something else entirely.").content_hash


def test_same_text_under_a_different_article_hashes_differently():
    assert chunk().content_hash != chunk(article="5").content_hash


def test_same_text_in_a_different_document_hashes_differently():
    assert chunk().content_hash != chunk(celex="32015R0757").content_hash


def test_topic_does_not_affect_the_hash():
    assert chunk().content_hash == chunk(topic="mrv").content_hash


def test_heading_path_affects_the_hash():
    assert chunk().content_hash != chunk(heading_path=("Chapter I",)).content_hash


def test_position_does_not_affect_the_hash():
    """An inserted paragraph shifts every position after it; none of those chunks may churn."""
    shifted = chunk(position=7)
    assert shifted.position == 7
    assert shifted.content_hash == chunk().content_hash


def test_topic_affects_the_metadata_hash_not_the_content_hash():
    assert chunk().metadata_hash != chunk(topic="mrv").metadata_hash


def test_position_affects_the_metadata_hash_not_the_content_hash():
    assert chunk().metadata_hash != chunk(position=7).metadata_hash


def test_text_affects_the_content_hash_not_the_metadata_hash():
    """Identity and metadata fields partition the chunk: each change lands in exactly one hash."""
    assert chunk().metadata_hash == chunk(text="Something else entirely.").metadata_hash


def test_points_affect_the_metadata_hash_not_the_content_hash():
    """Points derive from the text, so they are metadata like the references found in it."""
    assert chunk(points=("a",)).metadata_hash != chunk().metadata_hash
    assert chunk(points=("a",)).content_hash == chunk().content_hash


def test_act_title_affects_the_metadata_hash_not_the_content_hash():
    """A title is where the chunk came from, like its topic: a renamed act must not re-embed."""
    assert chunk(act_title="FuelEU").metadata_hash != chunk().metadata_hash
    assert chunk(act_title="FuelEU").content_hash == chunk().content_hash
