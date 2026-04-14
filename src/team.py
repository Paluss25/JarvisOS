"""Jarvis CEO Team — Multi-agent coordination (deferred to P11).

Architecture (future):
  Jarvis (CEO)
  ├── CTO (code, architecture, DevOps)
  │   ├── Coder (worker)
  │   └── Reviewer (worker)
  ├── CRO (research, analysis)
  │   └── Researcher (worker)
  ├── COO (operations, scheduling)
  │   └── Scheduler (worker)
  └── CCO (communications, reports)

Each C-level agent:
- Has its own model chain (agent-models.yaml)
- Has its own session table
- Can delegate to its workers
- Reports to Jarvis CEO

Implementation: P11
"""

# Team assembly is deferred to P11.
# This module is intentionally empty — it is imported by main.py as a
# placeholder so the import graph is complete from Day 1.


def create_team():
    """Create the full C-level agent team (not yet implemented).

    Raises:
        NotImplementedError: Until P11 is complete.
    """
    raise NotImplementedError("Team mode is scheduled for P11.")
