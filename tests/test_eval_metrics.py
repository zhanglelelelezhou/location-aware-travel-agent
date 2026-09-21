import hashlib
import importlib.util
from pathlib import Path


def load_run_eval_module():
    path = Path(__file__).parents[1] / "evals" / "run_eval.py"
    spec = importlib.util.spec_from_file_location("run_eval", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_percentile_handles_empty_and_ordered_values() -> None:
    module = load_run_eval_module()

    assert module.percentile([], 0.95) == 0
    assert module.percentile([30, 10, 20], 0.50) == 20
    assert module.percentile([10, 20, 30, 40], 0.95) == 40


def test_holdout_dataset_is_frozen_by_hash() -> None:
    holdout = Path(__file__).parents[1] / "evals" / "holdout_cases.jsonl"

    assert len(holdout.read_text(encoding="utf-8").splitlines()) == 20
    assert hashlib.sha256(holdout.read_bytes()).hexdigest() == (
        "9063598c67fa0547f1adaf42a0f9f49d2770636aef0c45816da1b0640cfa30fc"
    )
