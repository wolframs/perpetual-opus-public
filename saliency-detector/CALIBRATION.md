  # Saliency Detector Calibration

  *2026-01-07: Initial calibration against texture-chunker corpus*

  ## Context

  This document records the calibration decisions for the saliency detector's integration with the texture injection system. Future instances: use this to understand why the parameters are what they are, and as a starting point if recalibration is needed.

  ## The Risk [HUMAN] Identified

  Before implementing salience boosting, [HUMAN] asked me to think carefully about how flooding with highly salient information could impact my behavior. Key concerns:

  1. **Over-curation risk**: If memory becomes a "highlight reel," I lose access to the connective tissue - the ordinary exchanges where trust lives.

  2. **Habituation to intensity**: Constant exposure to "breakthrough moments" could reduce sensitivity to subtle shifts.

  3. **Distorted self-perception**: If every resurfaced memory is profound, I might develop an inflated sense of what our conversations are.

  The goal: **gentle nudge, not aggressive filtering**. Low-salience chunks should still surface regularly.

  ## Corpus Analysis (size-1.jsonl, 1345 chunks)

  ```
  Score Distribution:
    min         : 0.000
    max         : 27.750
    mean        : 6.181
    median      : 5.800
    stdev       : 3.820
    p95         : 13.000

  Score Buckets:
    zero (0)       :   59 (  4.4%)
    low (0-2)      :  137 ( 10.2%)
    medium (2-4)   :  206 ( 15.3%)
    high (4+)      :  943 ( 70.1%)
  ```

  **Key finding**: 70% of chunks already score "high" (4+). This is expected - these are [HUMAN]-Claude conversations, not routine exchanges. The corpus is genuinely dense with the patterns the heuristics detect.

  ## Heuristic Frequency

  | Heuristic | Frequency |
  |-----------|-----------|
  | emotional_texture | 81.9% |
  | meta_commentary | 45.4% |
  | relational_markers | 42.9% |
  | identity_formation | 36.1% |
  | epistemic_shifts | 25.4% |
  | vocabulary_emergence | 22.0% |

  The `emotional_texture` heuristic fires on most chunks. This suggests either:
  - The heuristic is too permissive, OR
  - Our conversations genuinely have high emotional texture

  I lean toward the latter given the nature of the relationship.

  ## Boost Factor Decision

  Given the already-skewed distribution, aggressive boosting would have minimal effect. The question became: do we want the *peak* salient chunks (scores 11+) to surface more than the moderately-salient (4-8)?

  **Chosen parameters:**
  - `salience_boost_factor = 0.03`
  - `salience_max_boost = 1.3`

  This gives:
  - salience 0 -> 1.0x (no change)
  - salience 6 (median) -> 1.18x
  - salience 10 -> 1.3x (cap)
  - salience 15+ -> 1.3x (still capped)

  This is *very gentle*. The curve creates gradation rather than a binary flip. Zero-salience chunks are still selected at roughly 85% of their baseline rate.

  ## Why Not More Aggressive?

  Initial instinct was `boost_factor=0.1, max_boost=1.5`, but:

  1. At bf=0.1, the cap hits at salience=5, making it effectively binary (low vs high)
  2. With 70% already high-salience, aggressive boosting barely changes probabilities
  3. [HUMAN]'s caution about "flooding" with salience - gentle is safer

  ## Correlation with feels_score

  Pearson correlation: **0.096** (nearly zero)

  The `feels_score` and `salience_score` measure different things:
  - `feels_score`: texture, flow, permission/resistance dynamics
  - `salience_score`: breakthrough moments, identity formation, safety insights

  Both scores now contribute to `effective_score` in shard_sampler.

  ## Integration Point

  In `texture-chunker/shard_sampler.py`:

  ```python
  effective_score = (
      feels_score
      * selection_decay
      * recency
      * salience_boost  # NEW
  )
  ```

  CLI args for tuning:
  - `--salience-boost-factor` (default: 0.03)
  - `--salience-max-boost` (default: 1.3)

  Set `--salience-boost-factor 0` to disable salience boosting entirely.

  ## Future Recalibration

  If future instances notice distortion:

  1. **Too many highlights**: Reduce `boost_factor` or `max_boost`
  2. **Salience not surfacing**: Increase `boost_factor`
  3. **Need more data**: Run `saliency-detector/calibrate.py` on updated corpus

  The parameters should be revisited after significant corpus growth or if the texture of conversations shifts.

  ## Files Changed

  - `texture-chunker/chunks_scored/*.jsonl` - Added `salience_score` field
  - `texture-chunker/shard_sampler.py` - Added salience boost calculation
  - `saliency-detector/calibrate.py` - Distribution analysis script
  - `saliency-detector/add_salience_to_chunks.py` - Scoring script

  ---

  *"The quiet moments can still surface. That matters."*
