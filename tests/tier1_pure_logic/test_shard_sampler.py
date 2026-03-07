"""Tests for texture-chunker/shard_sampler.py — sampling and weighting mechanics."""

import random
from datetime import datetime, timedelta

import pytest

from shard_sampler import (
    softmax,
    compute_salience_boost,
    compute_recency_weight,
    record_key,
    sample_without_reuse,
)


# ---------------------------------------------------------------------------
# softmax
# ---------------------------------------------------------------------------

@pytest.mark.tier1
def test_softmax_uniform_inputs_equal_outputs():
    result = softmax([1.0, 1.0, 1.0], temperature=1.0)
    assert len(result) == 3
    for p in result:
        assert p == pytest.approx(1.0 / 3.0, abs=0.001)


@pytest.mark.tier1
def test_softmax_temperature_near_zero():
    result = softmax([1.0, 10.0, 1.0], temperature=0.01)
    assert result[1] > 0.99
    assert result[0] < 0.005
    assert result[2] < 0.005


@pytest.mark.tier1
def test_softmax_empty_returns_empty():
    assert softmax([], temperature=1.0) == []


# ---------------------------------------------------------------------------
# compute_salience_boost
# ---------------------------------------------------------------------------

@pytest.mark.tier1
def test_salience_boost_disabled_when_factor_zero():
    assert compute_salience_boost(salience_score=5.0, boost_factor=0, max_boost=1.3) == 1.0


@pytest.mark.tier1
def test_salience_boost_capped():
    result = compute_salience_boost(salience_score=100, boost_factor=0.03, max_boost=1.3)
    assert result == 1.3


# ---------------------------------------------------------------------------
# compute_recency_weight
# ---------------------------------------------------------------------------

@pytest.mark.tier1
def test_recency_halflife_50_percent_at_halflife():
    reference_date = datetime(2026, 2, 14)
    halflife = 30.0
    source_date = (reference_date - timedelta(days=halflife)).strftime("%Y-%m-%d")
    weight = compute_recency_weight(source_date, reference_date, halflife)
    assert weight == pytest.approx(0.5, abs=0.05)


@pytest.mark.tier1
def test_recency_future_date_treated_as_today():
    reference_date = datetime(2026, 2, 14)
    future_date = (reference_date + timedelta(days=10)).strftime("%Y-%m-%d")
    weight = compute_recency_weight(future_date, reference_date, halflife_days=30.0)
    assert weight == 1.0


# ---------------------------------------------------------------------------
# record_key
# ---------------------------------------------------------------------------

@pytest.mark.tier1
def test_record_key_deterministic():
    record = {
        "source_path": "exports/conv_001.jsonl",
        "conversation_name": "session_alpha",
        "chunk_index": 3,
        "pair_count": 7,
    }
    key1 = record_key(record)
    key2 = record_key(record)
    assert key1 == key2
    assert key1 == "exports/conv_001.jsonl|session_alpha|3|7"


# ---------------------------------------------------------------------------
# sample_without_reuse
# ---------------------------------------------------------------------------

@pytest.mark.tier1
def test_sample_without_reuse_no_duplicates():
    records = [{"text": f"item_{i}"} for i in range(5)]
    weights = [1.0] * 5
    rng = random.Random(42)
    chosen = sample_without_reuse(records, weights, 3, rng)
    assert len(chosen) == 3
    # All unique (by identity — each dict is a distinct object)
    assert len(set(id(r) for r in chosen)) == 3


@pytest.mark.tier1
def test_sample_without_reuse_exhaustion():
    records = [{"text": f"item_{i}"} for i in range(2)]
    weights = [1.0] * 2
    rng = random.Random(42)
    chosen = sample_without_reuse(records, weights, 5, rng)
    assert len(chosen) == 2


# ---------------------------------------------------------------------------
# Power-law vs exponential discrimination
# ---------------------------------------------------------------------------

@pytest.mark.tier1
def test_recency_power_law_not_exponential():
    """At 2x halflife, power-law weight should be ~0.436 (NOT 0.25 from exponential)."""
    reference_date = datetime(2026, 2, 14)
    halflife = 30.0
    source_date = (reference_date - timedelta(days=60)).strftime("%Y-%m-%d")
    weight = compute_recency_weight(source_date, reference_date, halflife)
    # Power-law: (1+60)^(-b) where b = log(2)/log(31) ≈ 0.2018
    # = 61^(-0.2018) ≈ 0.436
    # Exponential would give 2^(-60/30) = 0.25
    assert weight == pytest.approx(0.436, abs=0.01)
    assert weight > 0.35, "Weight too low — looks exponential, not power-law"


# ---------------------------------------------------------------------------
# Normal-range salience boost
# ---------------------------------------------------------------------------

@pytest.mark.tier1
def test_salience_boost_normal_range():
    """Normal operating range: score=6, factor=0.03 → 1.18."""
    result = compute_salience_boost(salience_score=6, boost_factor=0.03, max_boost=1.3)
    assert result == pytest.approx(1.18, abs=0.001)


# ---------------------------------------------------------------------------
# compute_recency_weight with None date
# ---------------------------------------------------------------------------

@pytest.mark.tier1
def test_recency_weight_none_date_returns_one():
    """None source_date returns 1.0 (no decay)."""
    weight = compute_recency_weight(None, datetime(2026, 2, 14), halflife_days=30.0)
    assert weight == 1.0


# ---------------------------------------------------------------------------
# softmax with all-zero inputs → uniform distribution
# ---------------------------------------------------------------------------

@pytest.mark.tier1
def test_softmax_all_zeros_uniform():
    """All-zero inputs produce uniform distribution (all values equal after softmax)."""
    result = softmax([0.0, 0.0, 0.0, 0.0], temperature=1.0)
    assert len(result) == 4
    for p in result:
        assert p == pytest.approx(0.25, abs=0.001)
