# finsight-engine

Deterministic financial calculation and analysis engine for FinSight AI. The financial engine normalizes company financial records, calculates financial metrics, and detects rule-based red flags. See the source modules and tests in this directory.

Run tests from this directory:

```bash
python -m unittest discover -s tests -t .
```

The current test suite contains 104 tests. Inputs must state their units and accounting basis; missing financial values are not silently treated as zero. The engine output includes metric status, formulas, inputs, notes, sources, red flags, data-quality notes, and stable facts for downstream consumers.

See the root README for project status and the docs folder for the planned API architecture.
