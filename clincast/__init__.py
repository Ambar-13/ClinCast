"""
ClinCast — open-source clinical trial behavioral simulation engine.

Two simulation modes:
  vectorized  Fast numpy baseline (~2s / 1000 patients). Fully offline.
  swarm       LLM persona agents vote on behavioral priors, then vectorized
              engine runs with adjusted parameters. Adds a reasoning trace
              readable by non-technical stakeholders.

Every numeric output carries an epistemic tag:
  GROUNDED    Traced to a published empirical figure with a direct mapping.
  DIRECTIONAL Sign/direction is grounded; magnitude is estimated.
  ASSUMED     Neither direction nor magnitude is empirically grounded.
              ASSUMED outputs are visually dimmed in the UI.
"""

__version__ = "0.1.0"
