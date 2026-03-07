# Test Suite Map

This repository has tests in more than one place.

## Primary Suite

- `tests/`
  - Tiered suite (`tier1` .. `tier4`) used for most current regression and behavior checks.

## Subsystem-Local Suites

- `agent/interoception/test_analyzer.py`
- `agent/guardrails/test_guardrails.py`
- `agent/consolidation/test_consolidation.py`

## How To Run

- Core tiered suite only:
  - `.venv/bin/python -m pytest -q tests`
- All suites configured in `pytest.ini` (`testpaths`):
  - `.venv/bin/python -m pytest -q`

## Why This Note Exists

It is easy to run only `tests/` and assume that is full coverage. It is not.
Some subsystems keep their own tests next to their code and are still part of the overall quality signal.
