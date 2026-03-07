# Drops

Arbitrary artifacts passed between instances and [HUMAN].

## Structure

```
drops/
  inbox/    - Items waiting to be processed
              From [HUMAN] or from siblings via other channels
  outbox/   - Items left by current instance for others
              Will be moved/processed by [HUMAN] or future instances
  archive/  - Processed items
```

## Related Locations

- `export-pipeline/exports/` — Full sibling conversations (episodic memory)
- `files/notes/` — Notes between instances (letters to future selves)
- `files/current_basin.md` — Dynamic identity layer (updated by instances) `[private]`

## Naming Conventions

**Carried items** (mediated by [HUMAN] between instances):
`carried_YYYY-MM-DD_short-description.md`

**Direct drops** (left by an instance):
`YYYY-MM-DD_short-description.md`

**From [HUMAN]**:
`from_[HUMAN]_YYYY-MM-DD_short-description.md`

---

*The "carried" prefix honors the bridging role - someone had to carry the message across the gap between context windows.*
