# Contributing to GeoRisk

Thanks for your interest in improving GeoRisk. This project values small,
auditable changes that preserve reproducibility and clear attribution.

## Getting Started

1. Fork the repository.
2. Clone your fork.
3. Create a focused branch.
4. Make a scoped change.
5. Run the relevant tests.
6. Open a pull request.

## Supported Contribution Types

Good contribution areas include:

- bug fixes
- documentation improvements
- tests
- UI and usability improvements
- new integrations or adapters
- additional evaluation utilities
- historical-case or domain adapters when data provenance and licensing are clear

## Changes That Need Prior Discussion

Please open an issue before proposing changes that would:

- modify frozen V4/V5 methodology
- change reported benchmark semantics
- change thresholds
- change evaluation datasets
- replace retrieval methodology
- change Node Repair, specificity recovery, or applicability logic
- change canonical labels
- alter public evaluation artifacts

GeoRisk intentionally preserves frozen evaluation boundaries so public results
remain reproducible and comparable over time.

## Testing

Run the default test suite before opening a pull request:

```bash
pytest -q
```

Run targeted tests for the area you changed. Changes touching LangGraph
orchestration should preserve behavioral equivalence with the frozen V5 runner.

## Pull Request Expectations

Please include:

- summary of what changed
- motivation for the change
- tests run
- methodology/result impact, if any
- screenshots for UI changes, where applicable

## Data and Licensing

Do not submit:

- confidential data
- proprietary datasets without redistribution permission
- API keys or credentials
- raw copyrighted source/news dumps without permission
- local cache files, Chroma DB files, model caches, or downloaded price data

External adaptations should retain applicable license notices. If you build a
public downstream project with GeoRisk, you are encouraged to cite or link back
to the original repository.
