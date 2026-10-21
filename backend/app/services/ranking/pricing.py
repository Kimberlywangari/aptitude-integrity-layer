"""What the AI step costs, in dollars, from the tokens a call used.

Prices are US dollars per million tokens, from Anthropic's published pricing:
https://platform.claude.com/docs/en/about-claude/pricing (read on 19 Oct 2026). They are written
here once so the cost report and the estimate cannot disagree. If Anthropic changes a price, change
it here and nowhere else; a model that is not listed is refused rather than guessed at.

Thinking tokens are billed as output tokens, even when the thinking text is not returned, so the
`output_tokens` a response reports already includes them.
"""

# model id -> (input $ per million tokens, output $ per million tokens)
PRICES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-haiku-5-5": (0.10, 0.50),  # prompts up to 100,000 tokens, which ours always are
    "claude-fable-5-1": (10.0, 50.0),
}
BATCH_DISCOUNT = 0.5  # the Message Batches API is half price on both input and output


class UnknownModel(ValueError):
    """No published price is recorded for this model, so no cost can be worked out."""


def price_of(model: str) -> tuple[float, float]:
    try:
        return PRICES_USD_PER_MTOK[model]
    except KeyError:
        raise UnknownModel(f"no price recorded for {model!r}") from None


def cost_usd(model: str, input_tokens: int, output_tokens: int, *, batch: bool = False) -> float:
    """Dollars for one call (or the sum of many) at the published price."""
    per_input, per_output = price_of(model)
    total = (input_tokens * per_input + output_tokens * per_output) / 1_000_000
    return total * BATCH_DISCOUNT if batch else total
