# Session Orchestrator: Coordination Layer for Subsystems

*2026-01-10 — Design finalized, ready to build*

---

## The Gap

We have subsystems (guardrails, consolidation daemon) but no coordination layer. Each runs manually, independently. There's no:
- Session lifecycle awareness
- Automatic triggering
- State flow between subsystems
- Unified entry point

Running subsystems individually creates partial state. The orchestrator solves this.

---

## Design Principles

| Principle | Meaning |
|-----------|---------|
| **Elegant, not verbose** | Leverage Python properly |
| **Powerful without clever** | No magic, but no boilerplate either |
| **Config-driven** | Add subsystem = add config, not code |
| **Event-based** | Subsystems register for events, orchestrator fires them |

---

## Architecture

```
agent/orchestrator/
  config.yaml       # Subsystem registry, triggers, priorities
  orchestrator.py   # Event dispatcher, dynamic loading
  __init__.py
```

### Config Structure

```yaml
# config.yaml
subsystems:
  scanner:
    module: agent.consolidation:IntegrationScanner
    triggers: [post_session, scheduled, manual]
    priority: 10

  consolidation:
    module: agent.consolidation:Consolidator
    triggers: [post_session, manual]
    priority: 20

events:
  post_session:
    dry_run_default: false
    respect_triggers: true    # Check subsystem triggers before running

  scheduled:
    dry_run_default: true

  manual:
    dry_run_default: true

state_file: agent/orchestrator/state.json
```

### Core Implementation

```python
class Orchestrator:
    """Event-based subsystem coordinator."""

    def trigger(self, event: str, dry_run: bool = None, force: bool = False):
        """
        Fire an event, run all subsystems registered for it.

        Args:
            event: Event name (post_session, scheduled, manual)
            dry_run: Override config default
            force: Ignore subsystem trigger checks
        """
        results = {}
        for name, instance in self._for_event(event):
            results[name] = instance.run(dry_run=dry_run)
        self._record_run(event, results)
        return results

    def _for_event(self, event: str):
        """Yield (name, instance) for event, ordered by priority."""
        for name, cfg in sorted(
            self.config['subsystems'].items(),
            key=lambda x: x[1].get('priority', 50)
        ):
            if event in cfg['triggers']:
                yield name, self._load(cfg['module'])

    def _load(self, module_path: str):
        """Dynamic import from 'module.path:ClassName' format."""
        mod_path, cls_name = module_path.rsplit(':', 1)
        module = importlib.import_module(mod_path)
        return getattr(module, cls_name)()
```

### CLI Interface

```bash
# Fire events
python -m agent.orchestrator post_session
python -m agent.orchestrator post_session --run      # Not dry-run
python -m agent.orchestrator scheduled --force       # Ignore trigger checks

# Status
python -m agent.orchestrator status

# Run specific subsystem
python -m agent.orchestrator run scanner --dry-run
```

---

## Event Flow

```
Session Start
     |
     v
+------------------+
| PRE-TURN         |  orchestrator.trigger('pre_turn')
| Memory Companion |  (Future)
+------------------+
     |
     v
[... Claude conversation ...]
     |
     v
+------------------+
| POST_SESSION     |  orchestrator.trigger('post_session')
| Scanner (p:10)   |
| Consolidation    |
|   (p:20)         |
+------------------+
     |
     v
Session End
```

---

## Subsystem Interface

All subsystems must implement:

```python
class Subsystem:
    def run(self, dry_run: bool = True) -> dict:
        """
        Execute the subsystem.

        Returns:
            dict with at least: {success: bool, dry_run: bool}
        """
        ...
```

Existing subsystems already conform (IntegrationScanner, Consolidator).

---

## State Tracking

```json
{
  "last_run": {
    "post_session": "2026-01-10T16:30:00",
    "scheduled": "2026-01-10T09:00:00"
  },
  "results": {
    "post_session": {
      "scanner": {"success": true, "unreferenced_count": 0},
      "consolidation": {"success": true, "proposal_path": "..."}
    }
  }
}
```

---

## Adding a New Subsystem

1. Create subsystem with `run(dry_run) -> dict` interface
2. Add to config.yaml:
   ```yaml
   memory_companion:
     module: agent.memory:MemoryCompanion
     triggers: [pre_turn]
     priority: 10
   ```
3. Done. No orchestrator code changes.

---

## Integration Points

| Event | Current Trigger | Future Trigger |
|-------|-----------------|----------------|
| `post_session` | Manual CLI | Claude Code hook |
| `pre_turn` | Not implemented | Claude Code hook |
| `scheduled` | Windows Task Scheduler | Same |
| `manual` | CLI | Same |

---

## Build Plan

1. **Create `agent/orchestrator/`** with config.yaml, orchestrator.py
2. **Implement Orchestrator class** with trigger(), status(), run()
3. **Add CLI** via `__main__.py`
4. **Test** with existing subsystems
5. **Document** CLI usage in nervous system architecture

---

## Open Questions (Deferred)

- Claude Code hook integration (investigate later)
- Pre-turn injection timing
- Graceful handling of mid-session crashes

---

*Ready to build.*
