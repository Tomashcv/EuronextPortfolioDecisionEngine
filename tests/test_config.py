from __future__ import annotations

import pytest

from euronext_pde.config import load_config


def test_dimension_weights_sum_to_one() -> None:
    config = load_config()

    total = sum(
        dimension["weight"]
        for dimension in config["dimensions"].values()
    )

    assert total == pytest.approx(1.0)


def test_opportunity_weights_sum_to_one() -> None:
    config = load_config()

    opportunity = config["opportunity"]

    total = (
        opportunity["state_weight"]
        + opportunity["trajectory_weight"]
    )

    assert total == pytest.approx(1.0)


def test_v1_scope_is_deliberately_simple() -> None:
    config = load_config()

    scope = config["scope"]

    assert scope["equities"] is True
    assert scope["news"] is False
    assert scope["geopolitics"] is False
    assert scope["themes"] is False
    assert scope["machine_learning"] is False