"""Audit manual inputs required before running CAR validation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.validation.event_screening import accepted_validation_events
from src.validation.prediction_snapshot import (
    DEFAULT_MANIFEST_PATH,
    load_validation_events,
)


DEFAULT_PRICE_DIR = Path("data/prices")
DEFAULT_AUDIT_OUTPUT_PATH = Path("data/car_results/input_audit.json")
DEFAULT_BENCHMARK_SYMBOL = "SPY"


def audit_validation_inputs(
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
    price_dir: str | Path = DEFAULT_PRICE_DIR,
    benchmark_symbol: str = DEFAULT_BENCHMARK_SYMBOL,
    output_path: str | Path | None = DEFAULT_AUDIT_OUTPUT_PATH,
) -> dict[str, Any]:
    """Audit accepted validation events and required local price CSV files."""

    manifest = Path(manifest_path)
    prices = Path(price_dir)
    accepted_events = accepted_validation_events(load_validation_events(manifest))
    raw_events_by_id = _load_raw_events_by_id(manifest)

    required_symbols = collect_required_symbols(
        accepted_events=accepted_events,
        raw_events_by_id=raw_events_by_id,
        benchmark_symbol=benchmark_symbol,
    )
    existing_files, missing_files = check_price_files(required_symbols, prices)

    report = {
        "accepted_events": [
            {
                "event_id": event.event_id,
                "event_date": event.event_date,
                "event_type": event.event_type,
            }
            for event in accepted_events
        ],
        "required_symbols": required_symbols,
        "existing_price_files": existing_files,
        "missing_price_files": missing_files,
        "ready_to_run": bool(accepted_events) and not missing_files,
    }

    if output_path is not None:
        write_audit_report(report, output_path)

    return report


def collect_required_symbols(
    accepted_events: list[Any],
    raw_events_by_id: dict[str, dict[str, Any]],
    benchmark_symbol: str = DEFAULT_BENCHMARK_SYMBOL,
) -> list[str]:
    """Collect symbols from accepted event exposures, baselines, and benchmark."""

    symbols: list[str] = []
    for event in accepted_events:
        for exposure in event.predicted_exposures:
            _append_symbol(symbols, exposure.symbol)

        raw_event = raw_events_by_id.get(event.event_id, {})
        for baseline in raw_event.get("baseline_assets", []) or []:
            _append_symbol(symbols, baseline.get("symbol"))

    _append_symbol(symbols, benchmark_symbol)
    return symbols


def check_price_files(
    required_symbols: list[str],
    price_dir: str | Path = DEFAULT_PRICE_DIR,
) -> tuple[list[str], list[str]]:
    """Return existing and missing price CSV paths for required symbols."""

    prices = Path(price_dir)
    existing: list[str] = []
    missing: list[str] = []
    for symbol in required_symbols:
        csv_path = prices / f"{symbol}.csv"
        target = str(csv_path)
        if csv_path.exists():
            existing.append(target)
        else:
            missing.append(target)
    return existing, missing


def write_audit_report(report: dict[str, Any], output_path: str | Path) -> Path:
    """Write the input-audit report to JSON."""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def print_chinese_checklist(report: dict[str, Any]) -> None:
    """Print a concise Chinese-readable checklist for manual data prep."""

    print("CAR validation input audit")
    print("用途：只检查输入是否齐备，不计算 CAR，不代表模型表现。")
    print(f"accepted events count: {len(report['accepted_events'])}")

    print("required symbols:")
    _print_items(report["required_symbols"])

    print("existing price files:")
    _print_items(report["existing_price_files"])

    print("missing price files:")
    _print_items(report["missing_price_files"])

    ready_text = "yes" if report["ready_to_run"] else "no"
    print(f"ready_to_run: {ready_text}")
    if not report["ready_to_run"]:
        print("下一步：补齐 missing price files 后再运行 CAR validation。")


def _load_raw_events_by_id(manifest_path: Path) -> dict[str, dict[str, Any]]:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to load validation_events.yaml.") from exc

    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    return {
        raw_event.get("event_id"): raw_event
        for raw_event in payload.get("validation_events", [])
        if raw_event.get("event_id")
    }


def _append_symbol(symbols: list[str], symbol: Any) -> None:
    if not symbol:
        return
    normalized = str(symbol).strip().upper()
    if normalized and normalized not in symbols:
        symbols.append(normalized)


def _print_items(items: list[str]) -> None:
    if not items:
        print("- none")
        return
    for item in items:
        print(f"- {item}")


def parse_args() -> argparse.Namespace:
    """Parse command line arguments for the input-audit utility."""

    parser = argparse.ArgumentParser(
        description="Audit manual CAR validation inputs before running CAR.",
    )
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH))
    parser.add_argument("--price-dir", default=str(DEFAULT_PRICE_DIR))
    parser.add_argument("--benchmark-symbol", default=DEFAULT_BENCHMARK_SYMBOL)
    parser.add_argument("--output", default=str(DEFAULT_AUDIT_OUTPUT_PATH))
    parser.add_argument(
        "--no-json",
        action="store_true",
        help="Print the checklist without writing input_audit.json.",
    )
    return parser.parse_args()


def main() -> None:
    """Run the validation-input audit CLI."""

    args = parse_args()
    report = audit_validation_inputs(
        manifest_path=args.manifest,
        price_dir=args.price_dir,
        benchmark_symbol=args.benchmark_symbol,
        output_path=None if args.no_json else args.output,
    )
    print_chinese_checklist(report)


if __name__ == "__main__":
    main()
