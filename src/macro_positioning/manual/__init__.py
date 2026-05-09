"""Manual input layer — capture chart screenshots and text drops from chat
groups, self-charted setups, etc., and route them through the existing
documents → pre_tagger → watchlist → scoring pipeline.

Piece 1 (this round): capture + DB wiring + UI. No LLM cost.
Piece 2 (next session): real Gemini chart vision wired into brain/vision.py.
"""
