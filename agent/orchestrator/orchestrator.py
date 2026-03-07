"""
Session Orchestrator

Event-based subsystem coordinator. Fires events, runs registered subsystems
in priority order, tracks state.

Usage:
    from agent.orchestrator import Orchestrator

    orch = Orchestrator()
    orch.trigger('post_session')
    orch.trigger('post_session', dry_run=False)
    orch.status()
"""

import importlib
import json
import sys
import yaml
from datetime import datetime
from pathlib import Path
from typing import Optional, Iterator, Any

# Ensure repo root is in path for subsystem imports
_repo_root = Path(__file__).parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

# Load .env for API keys
try:
    from dotenv import load_dotenv
    load_dotenv(_repo_root / '.env')
except ImportError:
    pass


class Orchestrator:
    """Event-based subsystem coordinator."""

    def __init__(self, config_path: Optional[Path] = None):
        self.base_dir = Path(__file__).parent
        self.repo_root = self.base_dir.parent.parent
        self.config_path = config_path or self.base_dir / "config.yaml"
        self.config = self._load_config()
        self.state_file = self.repo_root / self.config.get('state_file', 'agent/orchestrator/state.json')
        self.state = self._load_state()

    def _load_config(self) -> dict:
        """Load configuration from YAML."""
        if self.config_path.exists():
            return yaml.safe_load(self.config_path.read_text())
        return {'subsystems': {}, 'events': {}}

    def _load_state(self) -> dict:
        """Load orchestrator state from disk."""
        if self.state_file.exists():
            try:
                return json.loads(self.state_file.read_text())
            except json.JSONDecodeError:
                pass
        return {'last_run': {}, 'results': {}}

    def _save_state(self):
        """Persist state to disk."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(self.state, indent=2, default=str))

    def _load_subsystem(self, module_path: str) -> Any:
        """
        Dynamic import from 'module.path:ClassName' format.

        Args:
            module_path: e.g., 'agent.consolidation:IntegrationScanner'

        Returns:
            Instantiated subsystem object
        """
        mod_path, cls_name = module_path.rsplit(':', 1)

        # Convert module path to file path to avoid agent/__init__.py issues
        # agent.consolidation -> agent/consolidation/__init__.py
        parts = mod_path.split('.')
        file_path = self.repo_root / '/'.join(parts) / '__init__.py'

        if not file_path.exists():
            # Try as single file: agent.consolidation.scanner -> agent/consolidation/scanner.py
            file_path = self.repo_root / '/'.join(parts[:-1]) / f'{parts[-1]}.py'

        if not file_path.exists():
            raise ImportError(f"Cannot find module file for {mod_path}")

        # Load via spec to bypass package __init__.py
        import importlib.util
        spec = importlib.util.spec_from_file_location(mod_path, file_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_path] = module
        spec.loader.exec_module(module)

        cls = getattr(module, cls_name)
        return cls()

    def _for_event(self, event: str) -> Iterator[tuple[str, Any]]:
        """
        Yield (name, instance) for subsystems registered to an event.

        Ordered by priority (lower = earlier).
        """
        subsystems = self.config.get('subsystems', {})
        for name, cfg in sorted(
            subsystems.items(),
            key=lambda x: x[1].get('priority', 50)
        ):
            if event in cfg.get('triggers', []):
                try:
                    instance = self._load_subsystem(cfg['module'])
                    yield name, instance
                except Exception as e:
                    print(f"Failed to load {name}: {e}")

    def trigger(self, event: str, dry_run: Optional[bool] = None, force: bool = False) -> dict:
        """
        Fire an event, run all subsystems registered for it.

        Args:
            event: Event name (post_session, scheduled, manual, etc.)
            dry_run: Override event's dry_run_default. None = use config.
            force: If True, run even if subsystem triggers not met.

        Returns:
            Dict of {subsystem_name: result_dict}
        """
        event_config = self.config.get('events', {}).get(event, {})

        # Resolve dry_run
        if dry_run is None:
            dry_run = event_config.get('dry_run_default', True)

        print(f"\n{'=' * 60}")
        print(f"ORCHESTRATOR: {event.upper()}")
        print(f"dry_run={dry_run}, force={force}")
        print('=' * 60)

        results = {}
        for name, instance in self._for_event(event):
            print(f"\n--- Running: {name} ---")
            try:
                # Pass force to subsystem if it supports it
                if hasattr(instance, 'run'):
                    if force and hasattr(instance.run, '__code__') and 'force' in instance.run.__code__.co_varnames:
                        result = instance.run(dry_run=dry_run, force=force)
                    else:
                        result = instance.run(dry_run=dry_run)
                    results[name] = result
                    success = result.get('success', False)
                    print(f"Result: {'SUCCESS' if success else 'FAILED'}")
                else:
                    results[name] = {'success': False, 'error': 'No run() method'}
            except Exception as e:
                results[name] = {'success': False, 'error': str(e)}
                print(f"Error: {e}")

        # Record run
        self._record_run(event, results, dry_run)

        print(f"\n{'=' * 60}")
        print(f"ORCHESTRATOR: {event.upper()} complete")
        print('=' * 60)

        return results

    def _record_run(self, event: str, results: dict, dry_run: bool):
        """Record run in state (only if not dry_run)."""
        if dry_run:
            return

        self.state['last_run'][event] = datetime.now().isoformat()
        self.state['results'][event] = results
        self._save_state()

    def run_one(self, name: str, dry_run: bool = True) -> dict:
        """
        Run a single subsystem by name.

        Args:
            name: Subsystem name from config
            dry_run: Whether to run in dry-run mode

        Returns:
            Result dict from subsystem
        """
        cfg = self.config.get('subsystems', {}).get(name)
        if not cfg:
            return {'success': False, 'error': f'Unknown subsystem: {name}'}

        try:
            instance = self._load_subsystem(cfg['module'])
            return instance.run(dry_run=dry_run)
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def status(self) -> dict:
        """
        Get orchestrator status.

        Returns:
            Dict with subsystem list, last runs, etc.
        """
        subsystems = {}
        for name, cfg in self.config.get('subsystems', {}).items():
            subsystems[name] = {
                'triggers': cfg.get('triggers', []),
                'priority': cfg.get('priority', 50),
                'description': cfg.get('description', '')
            }

        return {
            'subsystems': subsystems,
            'events': list(self.config.get('events', {}).keys()),
            'last_run': self.state.get('last_run', {}),
            'state_file': str(self.state_file)
        }

    def list_subsystems(self) -> list[str]:
        """List available subsystem names."""
        return list(self.config.get('subsystems', {}).keys())

    def list_events(self) -> list[str]:
        """List available event names."""
        return list(self.config.get('events', {}).keys())
