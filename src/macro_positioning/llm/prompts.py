EXTRACTION_PROMPT = """
You are extracting macro theses from trusted market commentary.

Return structured thesis objects with:
- thesis
- theme
- horizon
- direction
- affected assets
- catalysts
- risks
- implied positioning
- confidence
- source evidence

Only extract claims that are specific enough to influence positioning over a horizon of weeks to months.
"""
