"""Economies and trade goods (pure).

Every system has an economy (trading class). The game's trading table
(``metadata/reality/tables/tradingclassdatatable.mbin``, GcTradingClassTable)
gives each economy one trade-goods category it *sells* (cheap there) and one it
*needs* (pays well for), with price multipliers. Trade goods are the products
``TRA_<CATEGORY><tier>`` (tiers 1-5, base value 1,000 to 50,000 units).

Read from the game files; FALLBACK is what the table held on 2026-10-04 (game
build 25625620) and is used when the file cannot be read or its layout changed.
"""

from __future__ import annotations

import struct

from . import galaxy

CATEGORIES = ["Mineral", "Tech", "Commodity", "Component", "Alloy", "Exotic", "Energy"]
CATEGORY_NAMES = {"Mineral": "Minerals", "Tech": "Technology", "Commodity": "Commodities", "Component": "Components",
                  "Alloy": "Alloys", "Exotic": "Exotics", "Energy": "Energy"}
GOODS_PREFIX = {"Mineral": "TRA_MINERALS", "Tech": "TRA_TECH", "Commodity": "TRA_COMMODITY",
                "Component": "TRA_COMPONENT", "Alloy": "TRA_ALLOY", "Exotic": "TRA_EXOTICS", "Energy": "TRA_ENERGY"}
TIERS = 5
# The game's names for the economies (UI_ECON_CLASS_*), resolved in English and the game language.
ECONOMY_KEYS = {"Mining": "UI_ECON_CLASS_MINING_1", "HighTech": "UI_ECON_CLASS_TECH_2", "Trading": "UI_ECON_CLASS_TRADE_2",
                "Manufacturing": "UI_ECON_CLASS_MANUFACT_1", "Fusion": "UI_ECON_CLASS_ALLOY_1",
                "Scientific": "UI_ECON_CLASS_SCIENCE_1", "PowerGeneration": "UI_ECON_CLASS_POWER_1"}
ECONOMY_FALLBACK_NAMES = {"Mining": "Mining", "HighTech": "Technology", "Trading": "Trading",
                          "Manufacturing": "Manufacturing", "Fusion": "Advanced Materials", "Scientific": "Scientific",
                          "PowerGeneration": "Power Generation"}
CONFLICT_KEYS = {"Low": "UI_CONFLICT_LEVEL_LOW_2", "Default": "UI_CONFLICT_LEVEL_MED_2", "High": "UI_CONFLICT_LEVEL_HIGH_1",
                 "Pirate": "UI_CONFLICT_LEVEL_PIRATE1"}
TRADING_CLASS_ORDER = ["Mining", "HighTech", "Trading", "Manufacturing", "Fusion", "Scientific", "PowerGeneration"]

# economy: needs, sells, (min, max) price factor when the station buys from you, (min, max) when it sells to you
FALLBACK = {
    "Mining": {"needs": "Energy", "sells": "Mineral", "buys_at": (1.4, 1.8), "sells_at": (0.7, 0.9)},
    "HighTech": {"needs": "Component", "sells": "Tech", "buys_at": (1.4, 1.8), "sells_at": (0.7, 0.9)},
    "Trading": {"needs": "Exotic", "sells": "Commodity", "buys_at": (1.4, 1.8), "sells_at": (0.7, 0.9)},
    "Manufacturing": {"needs": "Mineral", "sells": "Component", "buys_at": (1.4, 1.8), "sells_at": (0.7, 0.9)},
    "Fusion": {"needs": "Commodity", "sells": "Alloy", "buys_at": (1.4, 1.8), "sells_at": (0.7, 0.9)},
    "Scientific": {"needs": "Alloy", "sells": "Exotic", "buys_at": (1.4, 1.8), "sells_at": (0.7, 0.9)},
    "PowerGeneration": {"needs": "Tech", "sells": "Energy", "buys_at": (1.4, 1.8), "sells_at": (0.7, 0.9)},
}
TABLE_FILE = "metadata/reality/tables/tradingclassdatatable.mbin"
_ROOT = 0x20                         # MBIN header
_CLASSES_AT = 0x360                  # GcTradingClassTable.TradingClassesData
_CLASS_SIZE = 0x38                   # GcTradingClassData
_ALL_CATEGORIES = CATEGORIES + ["None", "SpecialShop"]


def parse_trading_table(data: bytes) -> dict | None:
    """{economy: {needs, sells, buys_at, sells_at}} from the game's trading table, or None if the layout differs."""
    out = {}
    for i, name in enumerate(TRADING_CLASS_ORDER):
        at = _ROOT + _CLASSES_AT + i * _CLASS_SIZE
        if at + _CLASS_SIZE > len(data):
            return None
        max_buy, _max_buy_surge, max_sell, min_buy, _min_buy_surge, min_sell = struct.unpack_from("<6f", data, at + 0x18)
        needs, sells = struct.unpack_from("<2i", data, at + 0x30)
        if not (0 <= needs < len(CATEGORIES) and 0 <= sells < len(CATEGORIES)) or needs == sells \
                or not (0 < min_sell <= max_sell < min_buy <= max_buy < 10):
            return None
        out[name] = {"needs": _ALL_CATEGORIES[needs], "sells": _ALL_CATEGORIES[sells],
                     "buys_at": (round(min_buy, 2), round(max_buy, 2)), "sells_at": (round(min_sell, 2), round(max_sell, 2))}
    return out


def goods(category: str) -> list[str]:
    """The trade goods of a category, tier 1 to 5 (item ids)."""
    prefix = GOODS_PREFIX.get(category)
    return [f"{prefix}{tier}" for tier in range(1, TIERS + 1)] if prefix else []


def routes(economies: dict[int, dict], table: dict, origin: int | None) -> list[dict]:
    """For each trade-goods category: the best known place to buy it and the best known place to sell it.

    Buy where the economy *sells* the category, sell where it *needs* it - the nearest such systems to
    `origin` (your system first), and only within one galaxy. A category with no known buyer or seller is
    still listed with the missing half as None, so you see which economy to look for.
    Returns [{category, buy: key|None, sell: key|None, buy_distance, sell_distance, between}].
    """
    def nearest(keys):
        def rank(k):
            d = galaxy.distance_ly(origin, k) if origin is not None else None
            return (d is None, k != origin, d or 0.0, k)
        return min(keys, key=rank) if keys else None

    out = []
    for category in CATEGORIES:
        sellers = [k for k, e in economies.items() if table.get(e.get("economy"), {}).get("sells") == category]
        buyers = [k for k, e in economies.items() if table.get(e.get("economy"), {}).get("needs") == category]
        buy, sell = nearest(sellers), nearest(buyers)
        if buy is not None and sell is not None and origin is None:
            # Without a position, prefer the closest pair to each other.
            pairs = [(galaxy.distance_ly(a, b), a, b) for a in sellers for b in buyers if galaxy.distance_ly(a, b) is not None]
            if pairs:
                _, buy, sell = min(pairs)
        out.append({"category": category, "buy": buy, "sell": sell,
                    "buy_distance": galaxy.distance_ly(origin, buy) if origin is not None and buy is not None else None,
                    "sell_distance": galaxy.distance_ly(origin, sell) if origin is not None and sell is not None else None,
                    "between": galaxy.distance_ly(buy, sell) if buy is not None and sell is not None else None})
    return out
