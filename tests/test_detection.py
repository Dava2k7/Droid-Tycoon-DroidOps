import pytest
from droidops.droid_catalog import ALERT_CHOICES, RARITY_NAMES, VARIANT_NAMES
from droidops.droid_alert import (
    Word,
    DroidMatch,
    matching_droids,
    cautious_label_repair,
    UncertainMatchConfirmation,
    DroidTracker,
)
from droidops.hybrid_droid_detection import (
    visual_pair_matches,
)


def words(variant="diamond", rarity="mythic", y=20):
    return [
        Word(s, (10 + i * 85, y, 85 + i * 85, y + 20))
        for i, s in enumerate([variant, "droid", rarity, "spawned", "at", "the", "sandcrawler"])
    ]


@pytest.mark.parametrize("variant", VARIANT_NAMES)
@pytest.mark.parametrize("rarity", RARITY_NAMES)
def test_catalogue_pairs_are_recognised(variant, rarity):
    assert [m.pair for m in matching_droids(words(variant.lower(), rarity.lower()))] == [
        f"{variant} {rarity}"
    ]


def test_one_character_diamond_repair_and_aliases():
    assert cautious_label_repair("diamnd") == ("diamond", True)
    assert matching_droids(words("stella"))[0].pair == "Stellar Mythic"
    assert matching_droids(words("basic"))[0].pair == "Default Mythic"


@pytest.mark.parametrize("rarity", ["mythic", "legendary", "epic", "rare", "common"])
def test_unreadable_variant_cannot_create_an_alert_pair(rarity):
    assert matching_droids(words("unreadable", rarity)) == []


def test_uncertain_named_match_needs_another_capture():
    matches = matching_droids(words("kyber"))
    state = UncertainMatchConfirmation()
    assert state.confirm(matches, 1) == []
    assert state.confirm(matches, 1) == []
    assert len(state.confirm(matches, 1.1)) == 1


def test_visible_occurrence_does_not_repeat():
    matches = matching_droids(words("kyber"))
    state = DroidTracker()
    assert len(state.update(matches, 1)) == 1
    assert state.update(matches, 1.1) == []
    assert state.update(matches, 2) == []


def test_visual_pair_does_not_borrow_a_later_rarity():
    hits = [
        ("diamond", (10, 20, 80, 40), 0.99),
        ("rare", (100, 20, 150, 40), 0.99),
        ("mythic", (170, 20, 235, 40), 0.99),
    ]
    assert [m.pair for m in visual_pair_matches(hits, DroidMatch, Word)] == ["Diamond Rare"]


def test_catalogue_has_45_exact_choices():
    assert len(ALERT_CHOICES) == 45
    assert len(set(ALERT_CHOICES)) == 45
