"""Management QQ-only budget; Web and legacy channel defaults are unchanged."""
from .channel import ChannelBudget
from .channel_trial import cost_reservation

OUTPUT_TOKENS = 2048
DEFAULT_RUN_BUDGET_CNY = '8.06'
CHANNEL_BUDGET = ChannelBudget(max_output_tokens=OUTPUT_TOKENS)


def reservation_per_turn():
    return cost_reservation(output_tokens=OUTPUT_TOKENS)
