from __future__ import annotations

from experiments.reference_methods import methods


SERIES_2005 = [128, 117, 115, 125, 122, 137, 129, 140, 131, 114, 119, 137]


def _sim_forecasts(result: dict) -> list[float]:
    return [float(row["forecast"]) for row in result["simulated_holdout"]]


def _assert_close(actual: list[float], expected: list[float], tol: float = 1e-3) -> None:
    assert len(actual) == len(expected)
    for a, e in zip(actual, expected):
        assert abs(a - e) <= tol


def test_method_4_formula_alignment() -> None:
    result = methods.method_4_moving_average(SERIES_2005, {"n": 3}, pbf=3, granularity="day")
    assert result["status"] == "success"
    _assert_close(_sim_forecasts(result), [133.3333, 128.3333, 121.3333])


def test_method_5_formula_alignment() -> None:
    result = methods.method_5_linear_approximation(SERIES_2005, {"n": 3}, pbf=3, granularity="day")
    assert result["status"] == "success"
    _assert_close(_sim_forecasts(result), [132.0, 101.0, 113.0])


def test_method_6_formula_alignment() -> None:
    result = methods.method_6_least_square_regression(SERIES_2005, {"n": 3}, pbf=3, granularity="day")
    assert result["status"] == "success"
    _assert_close(_sim_forecasts(result), [135.3333, 102.3333, 109.3333], tol=1e-2)


def test_method_7_formula_alignment() -> None:
    result = methods.method_7_second_degree_approximation(SERIES_2005, {"n": 3}, pbf=3, granularity="day")
    assert result["status"] == "success"
    _assert_close(_sim_forecasts(result), [136.0, 136.0, 136.0], tol=1e-2)


def test_method_8_formula_alignment() -> None:
    result = methods.method_8_flexible(SERIES_2005, {"n": 3, "factor": 1.15}, pbf=3, granularity="day")
    assert result["status"] == "success"
    _assert_close(_sim_forecasts(result), [148.35, 161.0, 150.65], tol=1e-2)


def test_method_9_formula_alignment() -> None:
    result = methods.method_9_weighted_moving_average(
        SERIES_2005,
        {"n": 3, "weights": [0.6, 0.3, 0.1]},
        pbf=3,
        granularity="day",
    )
    assert result["status"] == "success"
    _assert_close(_sim_forecasts(result), [133.5, 121.7, 118.7], tol=1e-2)


def test_method_10_formula_alignment() -> None:
    result = methods.method_10_linear_smoothing(SERIES_2005, {"n": 3}, pbf=3, granularity="day")
    assert result["status"] == "success"
    _assert_close(_sim_forecasts(result), [133.6666, 124.0, 119.3333], tol=1e-2)


def test_method_11_formula_alignment() -> None:
    result = methods.method_11_exponential_smoothing(SERIES_2005, {"n": 3, "alpha": None}, pbf=3, granularity="day")
    assert result["status"] == "success"
    _assert_close(_sim_forecasts(result), [133.6666, 124.0, 119.3333], tol=1e-2)


def test_method_12_returns_not_applicable_when_history_short() -> None:
    short_series = [10.0] * 10
    result = methods.method_12_exponential_smoothing_trend_seasonality(
        short_series,
        {"season_length": 7, "alpha": None, "beta": None},
        pbf=3,
        granularity="day",
    )
    assert result["status"] == "not_applicable"
    assert result["status_reason"] == "insufficient_history"


def test_method_12_strict_mode_seasonal_cycle_alignment() -> None:
    seasonal_series = [10.0, 20.0, 30.0] * 4
    result = methods.method_12_exponential_smoothing_trend_seasonality(
        seasonal_series,
        {"season_length": 3, "alpha": None, "beta": None, "strict_mode": True},
        pbf=3,
        granularity="day",
    )
    assert result["status"] == "success"
    sim = _sim_forecasts(result)
    _assert_close(sim, [10.0, 20.0, 30.0], tol=1e-4)
    _assert_close(result["forecasts"], [10.0, 20.0, 30.0], tol=1e-4)
