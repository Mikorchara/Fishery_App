"""Management demonstration quotas; legacy five-turn trial limits stay unchanged."""
from dataclasses import dataclass, field
from decimal import Decimal

from apps.ai_service.channel_trial import money
from apps.ai_service.management_channel_budget import reservation_per_turn
from .contracts import BotError


@dataclass(frozen=True)
class ManagementRunLimits:
    max_turns: int | None = 5
    seconds: int | None = 1800
    total_budget_cny: str | None = '8.06'
    mode: str = 'bounded'
    budget_only: bool = field(default=False, init=False)

    def __post_init__(self):
        if self.mode == 'continuous':
            if any(value is not None for value in (self.max_turns,self.seconds,self.total_budget_cny)):
                raise BotError('INVALID_CONTINUOUS_RUN_LIMITS')
            return
        if self.mode != 'bounded':raise BotError('INVALID_RUN_LIMITS')
        if type(self.seconds) is not int or not 1 <= self.seconds <= 28800:
            raise BotError('INVALID_RUN_LIMITS')
        try:
            budget = money(self.total_budget_cny)
        except Exception:
            raise BotError('INVALID_RUN_BUDGET') from None
        if not Decimal('0') < budget <= Decimal('2000'):
            raise BotError('INVALID_RUN_BUDGET')
        capacity = int(budget // reservation_per_turn())
        if self.max_turns is None:
            if capacity < 1:
                raise BotError('RUN_BUDGET_INSUFFICIENT')
            # Finite budget also bounds ledger, lease and report memory. There is
            # no additional five-turn counter in this explicitly selected mode.
            object.__setattr__(self, 'budget_only', True)
            object.__setattr__(self, 'max_turns', capacity)
        elif type(self.max_turns) is not int or not 1 <= self.max_turns <= 1000:
            raise BotError('INVALID_RUN_LIMITS')
        if self.max_turns > capacity:
            raise BotError('RUN_BUDGET_INSUFFICIENT')

    @property
    def continuous(self):return self.mode=='continuous'

    @classmethod
    def continuous_run(cls):return cls(None,None,None,'continuous')
