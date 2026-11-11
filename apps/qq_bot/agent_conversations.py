"""Web-Agent channel history; retain the existing RAM budgets and accepted CAS."""
from dataclasses import dataclass, asdict

from apps.ai_backend.model_gateway import GatewayError
from apps.ai_service.channel_hybrid import HybridHistoryAuthority, HybridHistorySnapshot
from apps.ai_service.runtime.assistant import AssistantHistoryTurn
from .conversations import ConversationStore, _Turn
from .hybrid_conversations import valid_question


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

    def valid_focus(self,focus):return valid_question(focus)

    def commit(self,snapshot,**kwargs):
        flags=kwargs.get('source_flags')
        general=flags==('general','model_knowledge','NO_OBSERVATION')
        tools=(type(flags) is tuple and 2<=len(flags)<=3 and flags[0]=='agent'
               and len(set(flags))==len(flags) and set(flags[1:])<={'current','history','knowledge','score','events'})
        if type(snapshot) is not HybridHistorySnapshot or not (general or tools):
            raise GatewayError('INVALID_AGENT_HISTORY_SOURCE')
        return super().commit(snapshot,**kwargs)
