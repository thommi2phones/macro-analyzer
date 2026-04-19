"""Brain module — macro reasoning, synthesis, and chart vision.

Everything LLM-powered lives here. The rest of the app only touches this
module through the BrainClient interface, so when Phase 2 extracts the
Brain into its own hosted service, the consumers don't have to change.
"""

from macro_positioning.brain.client import BrainClient, build_brain_client
from macro_positioning.brain.heuristic import HeuristicThesisExtractor

__all__ = [
    "BrainClient",
    "build_brain_client",
    "HeuristicThesisExtractor",
]
