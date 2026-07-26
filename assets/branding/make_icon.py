"""Generate an on-brand Macro Analyzer app icon.

Aesthetic (locked, per DECISIONS): flat dark surface, 1px border, color reserved
for signal — green = bullish, gold = high conviction. No gradients/glow.
"""
from PIL import Image, ImageDraw

S = 1024
# ~10% transparent margin like standard macOS icons; rounded-rect plate inside.
margin = int(S * 0.085)
radius = int(S * 0.225)

BG      = (13, 17, 23, 255)     # flat dark surface (#0d1117)
BORDER  = (48, 54, 61, 255)     # subtle 1px-ish border (#30363d)
GRID    = (28, 34, 43, 255)     # faint baseline
GREEN   = (63, 185, 80, 255)    # bullish (#3fb950)
GREEN_D = (35, 134, 54, 255)    # bullish wick/darker
GOLD    = (212, 160, 23, 255)   # high conviction (#d4a017)

img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

plate = [margin, margin, S - margin, S - margin]
d.rounded_rectangle(plate, radius=radius, fill=BG, outline=BORDER, width=max(2, S // 220))

# Baseline
base_y = int(S * 0.70)
d.line([(int(S*0.20), base_y), (int(S*0.80), base_y)], fill=GRID, width=max(2, S//300))

# Ascending candlesticks: 4 bars, mostly green, the tallest is gold (conviction).
# Each candle: (center_x, body_top, body_bottom, wick_top, wick_bottom, color)
cw = int(S * 0.075)          # candle body width
ww = max(2, S // 150)        # wick width
candles = [
    # x_frac, body_top_frac, body_bot_frac, wick_top_frac, wick_bot_frac, color
    (0.34, 0.60, 0.70, 0.55, 0.74, GREEN),
    (0.45, 0.50, 0.64, 0.45, 0.68, GREEN),
    (0.56, 0.40, 0.56, 0.35, 0.60, GREEN),
    (0.67, 0.26, 0.50, 0.20, 0.54, GOLD),   # breakout / conviction bar
]
for xf, bt, bb, wt, wb, col in candles:
    cx = int(S * xf)
    wick_col = GOLD if col == GOLD else GREEN_D
    d.line([(cx, int(S*wt)), (cx, int(S*wb))], fill=wick_col, width=ww)
    d.rounded_rectangle(
        [cx - cw//2, int(S*bt), cx + cw//2, int(S*bb)],
        radius=max(3, cw//6), fill=col,
    )

# Upward trend arrow tip on the gold candle — a small chevron above it.
tipx, tipy = int(S*0.67), int(S*0.155)
aw = int(S*0.045)
d.line([(tipx - aw, tipy + aw), (tipx, tipy), (tipx + aw, tipy + aw)], fill=GOLD, width=max(3, S//180), joint="curve")

out = "/private/tmp/claude-502/-Users-thom-Documents-Personal-Code-Projects-Macro-Analyzer--claude-worktrees-recursing-euclid-7d2222/b3a6703f-420c-4f5b-8258-4f16d9a7d04d/scratchpad/icon_1024.png"
img.save(out)
print("wrote", out)
