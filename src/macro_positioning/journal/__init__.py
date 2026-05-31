"""Journal feedback loop — closed-trade review framework.

Closes the loop between trade close and the scoring/source-weight
machinery: a 7-question review per closed trade fans out into
`source_outcomes` (one row per credited source) and a calibration log
(one entry per Q4 hindsight setup score). See
`.claude/context/briefs/journal-feedback-loop.md` for the full
framework + state machine.
"""

from macro_positioning.journal import feedback_writer, repository, webhook

__all__ = ["feedback_writer", "repository", "webhook"]
