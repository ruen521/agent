from __future__ import annotations

from collections.abc import Callable
from typing import Any

from experiments.reference_methods import methods


MethodFn = Callable[[list[float], dict[str, Any], int, str], dict[str, Any]]


METHOD_REGISTRY: list[dict[str, Any]] = [
    {
        "method_code": "M01",
        "method_name": "Specified Percent Over Last Year",
        "document_method": "Method 1",
        "supported_on_current_dataset": False,
        "unsupported_reason": "missing_full_last_year_history",
        "function": None,
        "default_config": {},
    },
    {
        "method_code": "M02",
        "method_name": "Calculated Percent Over Last Year",
        "document_method": "Method 2",
        "supported_on_current_dataset": False,
        "unsupported_reason": "missing_full_last_year_history",
        "function": None,
        "default_config": {},
    },
    {
        "method_code": "M03",
        "method_name": "Last year to This year",
        "document_method": "Method 3",
        "supported_on_current_dataset": False,
        "unsupported_reason": "missing_full_last_year_history",
        "function": None,
        "default_config": {},
    },
    {
        "method_code": "M04",
        "method_name": "Moving Average",
        "document_method": "Method 4",
        "supported_on_current_dataset": True,
        "unsupported_reason": "",
        "function": methods.method_4_moving_average,
        "default_config": {"n": 3},
    },
    {
        "method_code": "M05",
        "method_name": "Linear Approximation",
        "document_method": "Method 5",
        "supported_on_current_dataset": True,
        "unsupported_reason": "",
        "function": methods.method_5_linear_approximation,
        "default_config": {"n": 3},
    },
    {
        "method_code": "M06",
        "method_name": "Least Square Regression",
        "document_method": "Method 6",
        "supported_on_current_dataset": True,
        "unsupported_reason": "",
        "function": methods.method_6_least_square_regression,
        "default_config": {"n": 3},
    },
    {
        "method_code": "M07",
        "method_name": "Second Degree Approximation",
        "document_method": "Method 7",
        "supported_on_current_dataset": True,
        "unsupported_reason": "",
        "function": methods.method_7_second_degree_approximation,
        "default_config": {"n": 3},
    },
    {
        "method_code": "M08",
        "method_name": "Flexible Method",
        "document_method": "Method 8",
        "supported_on_current_dataset": True,
        "unsupported_reason": "",
        "function": methods.method_8_flexible,
        "default_config": {"n": 3, "factor": 1.15},
    },
    {
        "method_code": "M09",
        "method_name": "Weighted Moving Average",
        "document_method": "Method 9",
        "supported_on_current_dataset": True,
        "unsupported_reason": "",
        "function": methods.method_9_weighted_moving_average,
        "default_config": {"n": 3, "weights": [0.6, 0.3, 0.1]},
    },
    {
        "method_code": "M10",
        "method_name": "Linear Smoothing",
        "document_method": "Method 10",
        "supported_on_current_dataset": True,
        "unsupported_reason": "",
        "function": methods.method_10_linear_smoothing,
        "default_config": {"n": 3},
    },
    {
        "method_code": "M11",
        "method_name": "Exponential Smoothing",
        "document_method": "Method 11",
        "supported_on_current_dataset": True,
        "unsupported_reason": "",
        "function": methods.method_11_exponential_smoothing,
        "default_config": {"n": 3, "alpha": None},
    },
    {
        "method_code": "M12",
        "method_name": "Exponential Smoothing with Trend and Seasonality",
        "document_method": "Method 12",
        "supported_on_current_dataset": True,
        "unsupported_reason": "",
        "function": methods.method_12_exponential_smoothing_trend_seasonality,
        "default_config": {"season_length": 7, "alpha": None, "beta": None, "strict_mode": True},
    },
]


def runnable_methods() -> list[dict[str, Any]]:
    return [entry for entry in METHOD_REGISTRY if bool(entry.get("supported_on_current_dataset"))]
