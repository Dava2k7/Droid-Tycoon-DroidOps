"""Canonical notification identities. Colours never establish an identity."""

VARIANT_NAMES = (
    "Default",
    "Gold",
    "Diamond",
    "Rainbow",
    "Beskar",
    "Galactic",
    "Stellar",
    "Kyber",
    "Scourge",
)
RARITY_NAMES = ("Common", "Rare", "Epic", "Legendary", "Mythic")
VARIANTS = {name.lower(): name for name in VARIANT_NAMES}
VARIANTS.update(stella="Stellar", basic="Default")
RARITIES = {name.lower(): name for name in RARITY_NAMES}
RARITIES["mythical"] = "Mythic"
ALERT_CHOICES = tuple(f"{variant} {rarity}" for variant in VARIANT_NAMES for rarity in RARITY_NAMES)
