from __future__ import annotations

from tools.run_freqtrade_offline import offline_catalog


def test_catalog_is_single_pair_spot_usdc() -> None:
    catalog = offline_catalog()
    assert set(catalog) == {"BTC/USDC"}
    market = catalog["BTC/USDC"]
    assert market["active"] is True
    assert market["spot"] is True
    assert market["quote"] == "USDC"
    assert market["swap"] is False
    assert market["future"] is False
    assert market["contract"] is False


def test_catalog_returns_deep_copies() -> None:
    first = offline_catalog()
    first["BTC/USDC"]["limits"]["amount"]["min"] = -1
    assert offline_catalog()["BTC/USDC"]["limits"]["amount"]["min"] > 0
