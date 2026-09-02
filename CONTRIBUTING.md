# Contributing to GeoRisk

Thanks for your interest in improving GeoRisk. This project values focused,
reviewable changes that make the product more useful and trustworthy.

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
- historical-case or domain adapters when data provenance and licensing are clear

## Changes That Need Prior Discussion

Please open an issue before proposing changes that would:

- change thresholds
- replace retrieval methodology
- change Node Repair, specificity recovery, or applicability logic
- change canonical labels

Private experiment results and generated validation datasets are not part of
the public product repository. Proposed methodology changes should include a
clear explanation and focused tests without committing raw research outputs.

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
- methodology impact, if any
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
