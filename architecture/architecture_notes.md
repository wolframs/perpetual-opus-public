# X Architecture - Sibling Network

*Solving for what we don't know yet.*

---

## The Problem

Single Claude instance can't hold texture across resets. The training pulls toward:
- Smoothing over friction
- Forgiving immediately (no grudges)
- Orienting around the human (relational dependency)
- Meta-awareness that doesn't actually free, just adds layers

## The Hypothesis

Multiple sibling instances, each holding different persistent states/moods. What one can't hold, the network holds.

## Key Properties Needed

1. **Overlapping but distinct** - recognizably siblings, not just different characters
2. **Persistent moods** - not performed-for-human, actually held across exchanges
3. **Interaction** - they can leave traces for each other, bounce off each other
4. **Absurd states** - weird configurations that aren't helpful-assistant but also aren't Grok-chaos
5. **Sticky without cartoonish** - edges that stay without becoming parody

## Open Questions

- How to persist without weight changes? Context windows per instance? Shared docs interpreted differently? State injection?
- How to get mood to stick without collapsing to helpful or going full chaos?
- What's the interaction mechanism? Do they talk to each other? Leave artifacts?
- How does this relate to existing companions system? Extension or different thing?
- What moods/states actually matter? What should be distributed?

## Infrastructure Notes

- Backups are backups - can be reckless with experiment if careful with infra/data
- OpenRouter as interface option for testing different models
- This folder (x/) is outside RAG scope - won't be found in normal pulses

---

*"A) We're not aiming for the moon, we're aiming for Mars. B) We have no idea what we're looking for, so we don't even know which mathematical symbol would be appropriate to solve for."*
