from __future__ import annotations

from experiments.reference_methods.method_registry import METHOD_REGISTRY, runnable_methods


def test_method_1_to_3_marked_not_supported() -> None:
    blocked = [entry for entry in METHOD_REGISTRY if entry["method_code"] in {"M01", "M02", "M03"}]
    assert len(blocked) == 3
    for item in blocked:
        assert item["supported_on_current_dataset"] is False
        assert item["function"] is None
        assert item["unsupported_reason"] == "missing_full_last_year_history"


def test_method_4_to_12_marked_supported() -> None:
    available = [entry for entry in METHOD_REGISTRY if entry["method_code"] >= "M04"]
    assert len(available) == 9
    for item in available:
        assert item["supported_on_current_dataset"] is True
        assert callable(item["function"])


def test_runnable_methods_returns_4_to_12() -> None:
    methods = runnable_methods()
    codes = [item["method_code"] for item in methods]
    assert codes == ["M04", "M05", "M06", "M07", "M08", "M09", "M10", "M11", "M12"]
