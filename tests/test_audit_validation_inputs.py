import json

from src.validation.audit_validation_inputs import audit_validation_inputs


def test_audit_validation_inputs_reports_missing_and_existing_price_files(tmp_path):
    manifest = tmp_path / "validation_events.yaml"
    price_dir = tmp_path / "prices"
    output_path = tmp_path / "input_audit.json"
    price_dir.mkdir()
    (price_dir / "AAA.csv").write_text(
        "Date,Adj Close\n2024-01-02,100.0\n",
        encoding="utf-8",
    )
    (price_dir / "SPY.csv").write_text(
        "Date,Adj Close\n2024-01-02,400.0\n",
        encoding="utf-8",
    )
    manifest.write_text(
        """
validation_events:
  - event_id: accepted_event
    event_date: "2024-01-02"
    event_description: "Fake accepted event."
    held_out_from_kb: true
    clear_t0: true
    clean_estimation_window: true
    low_confounding: true
    status: accepted
    predicted_exposures:
      - event_id: accepted_event
        symbol: AAA
        node: placeholder_node
        asset_type: placeholder_asset
        expected_direction: positive
    baseline_assets:
      - symbol: BBB
        node: broad_market
        asset_type: equity_etf
        baseline_type: placeholder_baseline
  - event_id: rejected_event
    event_date: "2024-01-03"
    event_description: "Fake rejected event."
    held_out_from_kb: false
    clear_t0: true
    clean_estimation_window: true
    low_confounding: true
    status: draft
    predicted_exposures:
      - event_id: rejected_event
        symbol: CCC
        node: placeholder_node
        asset_type: placeholder_asset
""",
        encoding="utf-8",
    )

    report = audit_validation_inputs(
        manifest_path=manifest,
        price_dir=price_dir,
        benchmark_symbol="SPY",
        output_path=output_path,
    )

    assert report["accepted_events"][0]["event_id"] == "accepted_event"
    assert report["required_symbols"] == ["AAA", "BBB", "SPY"]
    assert str(price_dir / "AAA.csv") in report["existing_price_files"]
    assert str(price_dir / "SPY.csv") in report["existing_price_files"]
    assert report["missing_price_files"] == [str(price_dir / "BBB.csv")]
    assert report["ready_to_run"] is False

    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert saved == report


def test_audit_validation_inputs_ready_when_all_price_files_exist(tmp_path):
    manifest = tmp_path / "validation_events.yaml"
    price_dir = tmp_path / "prices"
    price_dir.mkdir()
    for symbol in ["AAA", "SPY"]:
        (price_dir / f"{symbol}.csv").write_text(
            "Date,Close\n2024-01-02,100.0\n",
            encoding="utf-8",
        )
    manifest.write_text(
        """
validation_events:
  - event_id: accepted_event
    event_date: "2024-01-02"
    event_description: "Fake accepted event."
    held_out_from_kb: true
    clear_t0: true
    clean_estimation_window: true
    low_confounding: true
    status: accepted
    predicted_exposures:
      - event_id: accepted_event
        symbol: AAA
        node: placeholder_node
        asset_type: placeholder_asset
        expected_direction: negative
""",
        encoding="utf-8",
    )

    report = audit_validation_inputs(
        manifest_path=manifest,
        price_dir=price_dir,
        benchmark_symbol="SPY",
        output_path=None,
    )

    assert report["required_symbols"] == ["AAA", "SPY"]
    assert report["missing_price_files"] == []
    assert report["ready_to_run"] is True
