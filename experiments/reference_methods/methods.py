from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from statistics import mean
from typing import Any, Callable


_ALLOWED_STATUS = {"success", "not_applicable", "invalid_config"}


@dataclass
class TimePoint:
    period_date: date
    value: float


def _as_float_series(series: list[float]) -> list[float]:
    return [float(x) for x in series]


def _invalid_result(reason: str, min_history_required: int, params_used: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "invalid_config",
        "status_reason": reason,
        "forecasts": [],
        "simulated_holdout": [],
        "params_used": params_used,
        "min_history_required": int(min_history_required),
    }


def _not_applicable_result(reason: str, min_history_required: int, params_used: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "not_applicable",
        "status_reason": reason,
        "forecasts": [],
        "simulated_holdout": [],
        "params_used": params_used,
        "min_history_required": int(min_history_required),
    }


def _success_result(
    forecasts: list[float],
    simulated_holdout: list[dict[str, Any]],
    params_used: dict[str, Any],
    min_history_required: int,
) -> dict[str, Any]:
    return {
        "status": "success",
        "status_reason": "",
        "forecasts": [round(float(x), 6) for x in forecasts],
        "simulated_holdout": simulated_holdout,
        "params_used": params_used,
        "min_history_required": int(min_history_required),
    }


def _validate_status(result: dict[str, Any]) -> dict[str, Any]:
    status = str(result.get("status", ""))
    if status not in _ALLOWED_STATUS:
        raise ValueError(f"Unsupported status: {status}")
    return result


def _simulate_holdout(
    series: list[float],
    pbf: int,
    one_step_forecast: Callable[[list[float]], float],
) -> list[dict[str, Any]]:
    holdout_start = len(series) - pbf
    rows: list[dict[str, Any]] = []
    for idx in range(holdout_start, len(series)):
        hist = series[:idx]
        forecast = float(one_step_forecast(hist))
        rows.append(
            {
                "period_offset": idx - holdout_start + 1,
                "actual": round(float(series[idx]), 6),
                "forecast": round(float(forecast), 6),
            }
        )
    return rows


def _recursive_future_forecasts(
    series: list[float],
    horizon: int,
    one_step_forecast: Callable[[list[float]], float],
) -> list[float]:
    history = list(series)
    out: list[float] = []
    for _ in range(horizon):
        pred = float(one_step_forecast(history))
        out.append(pred)
        history.append(pred)
    return out


def _weights_linear(n: int) -> list[float]:
    weights = [float(n - i) for i in range(n)]
    total = sum(weights)
    return [w / total for w in weights]


def method_4_moving_average(
    series: list[float],
    config: dict[str, Any],
    pbf: int,
    granularity: str,
) -> dict[str, Any]:
    _ = granularity
    n = int(config.get("n", 3))
    min_hist = (2 * n) + pbf
    params = {"n": n}
    if n <= 0:
        return _validate_status(_invalid_result("n must be > 0", min_hist, params))
    if len(series) < min_hist:
        return _validate_status(_not_applicable_result("insufficient_history", min_hist, params))

    values = _as_float_series(series)

    def one_step(hist: list[float]) -> float:
        window = hist[-n:]
        return sum(window) / n

    simulated = _simulate_holdout(values, pbf, one_step)
    forecasts = _recursive_future_forecasts(values, pbf, one_step)
    return _validate_status(_success_result(forecasts, simulated, params, min_hist))


def method_5_linear_approximation(
    series: list[float],
    config: dict[str, Any],
    pbf: int,
    granularity: str,
) -> dict[str, Any]:
    _ = granularity
    n = int(config.get("n", 3))
    min_hist = n + 1 + pbf
    params = {"n": n}
    if n < 2:
        return _validate_status(_invalid_result("n must be >= 2", min_hist, params))
    if len(series) < min_hist:
        return _validate_status(_not_applicable_result("insufficient_history", min_hist, params))

    values = _as_float_series(series)

    def slope(hist: list[float]) -> tuple[float, float]:
        y_last = hist[-1]
        y_base = hist[-n]
        step = (y_last - y_base) / float(n - 1)
        return y_last, step

    def one_step(hist: list[float]) -> float:
        y_last, step = slope(hist)
        return y_last + step

    simulated = _simulate_holdout(values, pbf, one_step)

    y_last, step = slope(values)
    forecasts = [y_last + (step * float(m)) for m in range(1, pbf + 1)]
    return _validate_status(_success_result(forecasts, simulated, params, min_hist))


def _lsr_coefficients(window: list[float]) -> tuple[float, float]:
    n = len(window)
    xs = [float(i + 1) for i in range(n)]
    x_mean = sum(xs) / n
    y_mean = sum(window) / n
    num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, window))
    den = sum((x - x_mean) ** 2 for x in xs)
    b = 0.0 if den == 0 else num / den
    a = y_mean - (b * x_mean)
    return a, b


def method_6_least_square_regression(
    series: list[float],
    config: dict[str, Any],
    pbf: int,
    granularity: str,
) -> dict[str, Any]:
    _ = granularity
    n = int(config.get("n", 3))
    min_hist = n + pbf
    params = {"n": n}
    if n < 2:
        return _validate_status(_invalid_result("n must be >= 2", min_hist, params))
    if len(series) < min_hist:
        return _validate_status(_not_applicable_result("insufficient_history", min_hist, params))

    values = _as_float_series(series)

    def one_step(hist: list[float]) -> float:
        window = hist[-n:]
        a, b = _lsr_coefficients(window)
        return a + (b * float(n + 1))

    simulated = _simulate_holdout(values, pbf, one_step)

    a, b = _lsr_coefficients(values[-n:])
    forecasts = [a + (b * float(n + m)) for m in range(1, pbf + 1)]
    return _validate_status(_success_result(forecasts, simulated, params, min_hist))


def _method_7_coefficients(window: list[float], block_n: int) -> tuple[float, float, float]:
    q1 = sum(window[0:block_n])
    q2 = sum(window[block_n:(2 * block_n)])
    q3 = sum(window[(2 * block_n):(3 * block_n)])

    a = q3 - (3 * (q2 - q1))
    c = ((q3 - q2) + (q1 - q2)) / 2.0
    b = (q2 - q1) - (3 * c)
    return a, b, c


def method_7_second_degree_approximation(
    series: list[float],
    config: dict[str, Any],
    pbf: int,
    granularity: str,
) -> dict[str, Any]:
    _ = granularity
    n = int(config.get("n", 3))
    min_hist = (3 * n) + pbf
    params = {"n": n}
    if n <= 0:
        return _validate_status(_invalid_result("n must be > 0", min_hist, params))
    if len(series) < min_hist:
        return _validate_status(_not_applicable_result("insufficient_history", min_hist, params))

    values = _as_float_series(series)

    holdout_start = len(values) - pbf
    holdout_window = values[holdout_start - (3 * n):holdout_start]
    a_hold, b_hold, c_hold = _method_7_coefficients(holdout_window, n)
    simulated: list[dict[str, Any]] = []
    for m in range(1, pbf + 1):
        x = 4.0 + float((m - 1) // n)
        simulated.append(
            {
                "period_offset": m,
                "actual": round(float(values[holdout_start + m - 1]), 6),
                "forecast": round((a_hold + (b_hold * x) + (c_hold * x * x)) / float(n), 6),
            }
        )

    future_window = values[-(3 * n):]
    a, b, c = _method_7_coefficients(future_window, n)
    forecasts: list[float] = []
    for m in range(1, pbf + 1):
        x = 4.0 + float((m - 1) // n)
        forecasts.append((a + (b * x) + (c * x * x)) / float(n))
    return _validate_status(_success_result(forecasts, simulated, params, min_hist))


def method_8_flexible(
    series: list[float],
    config: dict[str, Any],
    pbf: int,
    granularity: str,
) -> dict[str, Any]:
    _ = granularity
    n = int(config.get("n", 3))
    factor = float(config.get("factor", 1.15))
    min_hist = n + pbf
    params = {"n": n, "factor": factor}
    if n <= 0:
        return _validate_status(_invalid_result("n must be > 0", min_hist, params))
    if len(series) < min_hist:
        return _validate_status(_not_applicable_result("insufficient_history", min_hist, params))

    values = _as_float_series(series)

    def one_step(hist: list[float]) -> float:
        return float(hist[-n]) * factor

    simulated = _simulate_holdout(values, pbf, one_step)
    forecasts = _recursive_future_forecasts(values, pbf, one_step)
    return _validate_status(_success_result(forecasts, simulated, params, min_hist))


def method_9_weighted_moving_average(
    series: list[float],
    config: dict[str, Any],
    pbf: int,
    granularity: str,
) -> dict[str, Any]:
    _ = granularity
    n = int(config.get("n", 3))
    weights = config.get("weights", [0.6, 0.3, 0.1])
    if not isinstance(weights, list):
        return _validate_status(_invalid_result("weights must be list", n + pbf, {"n": n}))
    try:
        normalized = [float(w) for w in weights]
    except Exception:
        return _validate_status(_invalid_result("weights must be numeric", n + pbf, {"n": n}))

    total = sum(normalized)
    if n <= 0 or len(normalized) != n or total <= 0:
        return _validate_status(
            _invalid_result("weights length must equal n and sum > 0", n + pbf, {"n": n, "weights": normalized})
        )

    norm = [w / total for w in normalized]
    min_hist = n + pbf
    params = {"n": n, "weights": norm}
    if len(series) < min_hist:
        return _validate_status(_not_applicable_result("insufficient_history", min_hist, params))

    values = _as_float_series(series)

    def one_step(hist: list[float]) -> float:
        recent = list(reversed(hist[-n:]))
        return sum(v * w for v, w in zip(recent, norm))

    simulated = _simulate_holdout(values, pbf, one_step)
    forecasts = _recursive_future_forecasts(values, pbf, one_step)
    return _validate_status(_success_result(forecasts, simulated, params, min_hist))


def method_10_linear_smoothing(
    series: list[float],
    config: dict[str, Any],
    pbf: int,
    granularity: str,
) -> dict[str, Any]:
    _ = granularity
    n = int(config.get("n", 3))
    min_hist = n + pbf
    params = {"n": n}
    if n <= 0:
        return _validate_status(_invalid_result("n must be > 0", min_hist, params))
    if len(series) < min_hist:
        return _validate_status(_not_applicable_result("insufficient_history", min_hist, params))

    weights = _weights_linear(n)
    params["weights"] = weights
    values = _as_float_series(series)

    def one_step(hist: list[float]) -> float:
        recent = list(reversed(hist[-n:]))
        return sum(v * w for v, w in zip(recent, weights))

    simulated = _simulate_holdout(values, pbf, one_step)
    forecasts = _recursive_future_forecasts(values, pbf, one_step)
    return _validate_status(_success_result(forecasts, simulated, params, min_hist))


def method_11_exponential_smoothing(
    series: list[float],
    config: dict[str, Any],
    pbf: int,
    granularity: str,
) -> dict[str, Any]:
    _ = granularity
    n = int(config.get("n", 3))
    alpha_raw = config.get("alpha")
    alpha = float(alpha_raw) if alpha_raw is not None else None
    min_hist = n + pbf
    params = {"n": n, "alpha": alpha}
    if n <= 0:
        return _validate_status(_invalid_result("n must be > 0", min_hist, params))
    if alpha is not None and (alpha <= 0 or alpha > 1):
        return _validate_status(_invalid_result("alpha must be in (0,1]", min_hist, params))
    if len(series) < min_hist:
        return _validate_status(_not_applicable_result("insufficient_history", min_hist, params))

    values = _as_float_series(series)

    def one_step(hist: list[float]) -> float:
        window = hist[-n:]
        smoothed = window[0]
        for index, actual in enumerate(window[1:], start=2):
            # 文档约定：alpha为空时使用随窗口位置变化的系数 2/(i+1)
            alpha_i = (2.0 / float(index + 1)) if alpha is None else alpha
            smoothed = (alpha_i * actual) + ((1 - alpha_i) * smoothed)
        return smoothed

    simulated = _simulate_holdout(values, pbf, one_step)
    forecasts = _recursive_future_forecasts(values, pbf, one_step)
    return _validate_status(_success_result(forecasts, simulated, params, min_hist))


def _compute_seasonal_indices(values: list[float], season_length: int) -> list[float]:
    seasons = len(values) // season_length
    if seasons < 2:
        raise ValueError("need at least two seasons")
    total = sum(values[: seasons * season_length])
    if total <= 0:
        raise ValueError("non-positive total for seasonal indices")

    indices: list[float] = []
    for pos in range(season_length):
        seasonal_sum = 0.0
        for season in range(seasons):
            seasonal_sum += values[(season * season_length) + pos]
        index = (seasonal_sum / total) * season_length
        indices.append(index if index > 0 else 1.0)
    return indices


def _resolved_smoothing_factor(t: int, factor: float | None) -> float:
    if factor is not None:
        return factor
    # Method 12文档规则：a/b为空时按2/(t+1)计算，且t>=6按6处理。
    effective_t = min(max(int(t), 1), 6)
    return 2.0 / float(effective_t + 1)


def _method_12_strict_state(
    values: list[float],
    season_length: int,
    alpha: float | None,
    beta: float | None,
) -> tuple[float, float, list[float]]:
    seasonals = _compute_seasonal_indices(values, season_length)
    level = values[0] / max(seasonals[0], 1e-9)
    trend = 0.0

    # t使用1-based索引，与文档A.14公式一致。
    for t in range(2, len(values) + 1):
        actual = values[t - 1]
        seasonal = max(seasonals[(t - 1) % season_length], 1e-9)
        alpha_t = _resolved_smoothing_factor(t, alpha)
        beta_t = _resolved_smoothing_factor(t, beta)
        prev_level = level
        level = (alpha_t * (actual / seasonal)) + ((1 - alpha_t) * (level + trend))
        trend = (beta_t * (level - prev_level)) + ((1 - beta_t) * trend)

    return level, trend, seasonals


def _method_12_forecast(
    level: float,
    trend: float,
    seasonals: list[float],
    time_index: int,
    m: int,
) -> float:
    seasonal = seasonals[(time_index + m - 1) % len(seasonals)]
    return (level + (trend * float(m))) * seasonal


def method_12_exponential_smoothing_trend_seasonality(
    series: list[float],
    config: dict[str, Any],
    pbf: int,
    granularity: str,
) -> dict[str, Any]:
    _ = granularity
    season_length = int(config.get("season_length", 7))
    alpha_raw = config.get("alpha")
    beta_raw = config.get("beta")
    strict_mode = bool(config.get("strict_mode", True))
    alpha = float(alpha_raw) if alpha_raw is not None else None
    beta = float(beta_raw) if beta_raw is not None else None
    min_hist = (2 * season_length) + pbf
    params = {
        "season_length": season_length,
        "alpha": alpha,
        "beta": beta,
        "strict_mode": strict_mode,
    }

    if season_length < 2:
        return _validate_status(_invalid_result("season_length must be >= 2", min_hist, params))
    if alpha is not None and (alpha <= 0 or alpha > 1):
        return _validate_status(_invalid_result("alpha must be in (0,1]", min_hist, params))
    if beta is not None and (beta <= 0 or beta > 1):
        return _validate_status(_invalid_result("beta must be in (0,1]", min_hist, params))

    values = _as_float_series(series)
    if len(values) < min_hist:
        return _validate_status(_not_applicable_result("insufficient_history", min_hist, params))
    if any(v <= 0 for v in values):
        return _validate_status(_not_applicable_result("non_positive_series_for_multiplicative_seasonality", min_hist, params))

    def one_step(hist: list[float]) -> float:
        if strict_mode:
            level, trend, seasonals = _method_12_strict_state(hist, season_length, alpha, beta)
            return _method_12_forecast(level, trend, seasonals, len(hist), 1)
        level, trend, seasonals = _method_12_strict_state(hist, season_length, alpha, beta)
        return _method_12_forecast(level, trend, seasonals, len(hist), 1)

    simulated = _simulate_holdout(values, pbf, one_step)

    if strict_mode:
        level, trend, seasonals = _method_12_strict_state(values, season_length, alpha, beta)
    else:
        level, trend, seasonals = _method_12_strict_state(values, season_length, alpha, beta)
    forecasts: list[float] = []
    for m in range(1, pbf + 1):
        forecasts.append(_method_12_forecast(level, trend, seasonals, len(values), m))

    return _validate_status(_success_result(forecasts, simulated, params, min_hist))


def compute_metrics(rows: list[dict[str, float]]) -> dict[str, float]:
    if not rows:
        return {
            "sample_count": 0.0,
            "mad": 0.0,
            "poa": 0.0,
            "mae": 0.0,
            "wape": 0.0,
            "bias": 0.0,
        }

    errors = [float(row["forecast"]) - float(row["actual"]) for row in rows]
    abs_errors = [abs(e) for e in errors]
    total_actual = sum(float(row["actual"]) for row in rows)
    total_forecast = sum(float(row["forecast"]) for row in rows)
    count = float(len(rows))

    mad = sum(abs_errors) / count
    mae = mad
    wape = 0.0 if total_actual == 0 else sum(abs_errors) / total_actual
    poa = 0.0 if total_actual == 0 else (total_forecast / total_actual) * 100.0
    bias = 0.0 if total_actual == 0 else sum(errors) / total_actual

    return {
        "sample_count": count,
        "mad": round(mad, 6),
        "poa": round(poa, 6),
        "mae": round(mae, 6),
        "wape": round(wape, 6),
        "bias": round(bias, 6),
    }


def resample_series(points: list[TimePoint], granularity: str) -> list[TimePoint]:
    if granularity == "day":
        return sorted(points, key=lambda p: p.period_date)
    if granularity == "week":
        buckets: dict[tuple[int, int], list[TimePoint]] = defaultdict(list)
        for point in points:
            iso = point.period_date.isocalendar()
            buckets[(iso.year, iso.week)].append(point)
        rows: list[TimePoint] = []
        for key in sorted(buckets):
            items = buckets[key]
            period_date = max(item.period_date for item in items)
            value = sum(item.value for item in items)
            rows.append(TimePoint(period_date=period_date, value=float(value)))
        return rows
    raise ValueError(f"Unsupported granularity: {granularity}")
