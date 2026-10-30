"""Per-tool brand colors: the only visual mark, no glyphs or pixel art.

Tools are told apart by color alone; labels carry these colors in the TUI,
the exit summary and plain output.
"""
# role -> (r, g, b)
BRAND_COLORS = {
    "claude": (217, 119, 87),        # Claude Code coral, from the official binary
    "codex": (16, 163, 127),         # OpenAI/ChatGPT green
    "kimi": (129, 140, 248),         # Moonshot indigo
    "hermes": (210, 153, 34),        # caduceus gold
    "gemini": (71, 150, 227),        # Google Gemini blue
    "grok": (160, 160, 160),         # xAI graphite
    "opencode": (226, 232, 240),     # opencode pale slate
    "openclaw": (239, 68, 68),       # lobster red
    "pi": (46, 204, 113),            # green
    "mcode": (168, 85, 247),         # MiniMax purple
    "claude-desktop": (217, 119, 87),
    "chatgpt": (96, 96, 96),         # ChatGPT graphite
}
