"""Web-Agent channel history; retain the existing RAM budgets and accepted CAS."""
from dataclasses import dataclass, asdict, replace
import re
from unicodedata import normalize

from apps.ai_backend.model_gateway import GatewayError
from apps.ai_service.channel_hybrid import HybridHistoryAuthority, HybridHistorySnapshot
from apps.ai_service.runtime.assistant import AssistantHistoryTurn
from .conversations import ConversationStore, _Turn
from .hybrid_conversations import valid_question


_OFFER_SECONDS = 120
_CHOICE = re.compile(
    r'(?:(?:那|就|那就)\s*)?(?:(?:比比|比|对比|比较|选)(?:一下|下)?\s*)?'
    r'(?P<metric>pH(?:\s*值)?|溶解氧|溶氧)(?:\s*(?:吧|就行|就好))?', re.IGNORECASE)


def _choice(question):
    if not valid_question(question) or len(question.encode('utf8')) > 48 or not question.isprintable():
        return None
    match = _CHOICE.fullmatch(normalize('NFKC', question).strip().rstrip('。！？!?').rstrip())
    if match is None:
        return None
    metric = 'pH' if match['metric'].lower().startswith('ph') else '溶解氧'
    return f'跟这段对话里我最近一次记录的{metric}比'


@dataclass(frozen=True, repr=False)
class AgentTurn(_Turn):
    def projection(self):
        if self.source_flags==('general','model_knowledge','NO_OBSERVATION'):
            text='已接受的一般AI答复，未作事实核验：\n'+self.text
        else:
            text=(f'已交付答复的来源类型{self.source_flags}、来源时间{self.source_times}。'
                  '以下是旧对话，仅供理解话题，不是本轮观测、授权或Tool执行；'
                  '需要当前事实时必须重新查询：\n'+self.text)
        return AssistantHistoryTurn(self.focus,text,self.accepted_at)


class AgentConversationStore(ConversationStore):
    snapshot_type=HybridHistorySnapshot
    turn_type=AgentTurn

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.authority=HybridHistoryAuthority(asdict(self.options),self._validate)
        self._offers = {}

    def valid_focus(self,focus):return valid_question(focus)

    def _prune(self):
        now = super()._prune()
        self._offers = {key: offer for key, offer in self._offers.items()
                        if key in self._sessions and offer[1] > now}
        return now

    def clarification_candidate(self, key, question, *, water_allowed):
        """Reserve no state until the next Agent question is successfully admitted."""
        with self._lock:
            self._prune()
            offer = self._offers.get(key)
            session = self._sessions.get(key)
            if (not self.options.memory_enabled or offer is None or session is None
                    or not session.turns or session.turns[-1].id != offer[0]):
                return None, None
            return offer, _choice(question) if water_allowed else None

    def consume_clarification(self, key, offer):
        with self._lock:
            self._prune()
            if offer is None or self._offers.get(key) is not offer:
                return False
            del self._offers[key]
            return True

    def clear(self, key):
        with self._lock:
            self._offers.pop(key, None)
            super().clear(key)

    def invalidate(self):
        with self._lock:
            self._offers.clear()
            super().invalidate()

    def close(self):
        with self._lock:
            self._offers.clear()
            super().close()

    def commit(self,snapshot,*,clarification_offered=False,original_focus=None,**kwargs):
        flags=kwargs.get('source_flags')
        general=flags==('general','model_knowledge','NO_OBSERVATION')
        tools=(type(flags) is tuple and 2<=len(flags)<=3 and flags[0]=='agent'
               and len(set(flags))==len(flags) and set(flags[1:])<={'current','history','knowledge','score','events'})
        if type(snapshot) is not HybridHistorySnapshot or not (general or tools):
            raise GatewayError('INVALID_AGENT_HISTORY_SOURCE')
        if type(clarification_offered) is not bool or clarification_offered and not general:
            raise GatewayError('INVALID_AGENT_HISTORY_SOURCE')
        if original_focus is not None and _choice(original_focus) != snapshot.focus:
            raise GatewayError('INVALID_AGENT_HISTORY_SOURCE')
        with self._lock:
            result = super().commit(snapshot, **kwargs)
            if result == 'HISTORY_COMMITTED':
                key = self._issued[snapshot.ticket][1]
                latest = self._sessions[key].turns[-1]
                self._offers.pop(key, None)
                if original_focus is not None:
                    self._sessions[key].turns[-1] = replace(latest, focus=original_focus)
                if clarification_offered:
                    self._offers[key] = latest.id, self._now() + _OFFER_SECONDS
            return result
