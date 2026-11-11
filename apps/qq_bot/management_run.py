"""Management process-local consent; no import or reuse of Prototype approvals."""
from apps.ai_backend.credentials import CredentialStore
from apps.ai_service.runtime.locations import private_project_location
from apps.ai_service.runtime.release_contracts import _hash
from apps.ai_service.channel_management_live import (CONTRACT, ManagementLiveTurn, LivePermitIssuer,
                                                     prepared_scope, preparation_record)
from apps.ai_service.channel_validation import validation_once
from .hybrid_run import HybridRun, HybridLedger
from .session_run import SessionRun
from .management_config import ROOT, PREPARATION, RISK, load_request
from .trial_configuration import read_json
from .contracts import BotError
from apps.ai_service.management_channel_budget import CHANNEL_BUDGET, OUTPUT_TOKENS
from .management_limits import ManagementRunLimits


class ManagementLedger(HybridLedger):
    output_token_limit=OUTPUT_TOKENS
    limits_type=ManagementRunLimits

    def quota_limit_code(self):
        return 'RUN_BUDGET_EXHAUSTED' if self.limits.budget_only else 'RUN_TURN_LIMIT'

    def __init__(self, *args, **kwargs):
        self.output_token_limit=kwargs.pop('output_token_limit',OUTPUT_TOKENS)
        contract=kwargs.pop('contract',CONTRACT)
        self.requests_per_turn=kwargs.pop('requests_per_turn',2)
        super().__init__(*args, **kwargs)
        self._plan.update(contract=contract, environment='MANAGEMENT_PROCESS_RUNCONSENT')
        if self.continuous:self._plan.update(reservation_per_turn_cny=None,cumulative_limits=False)

    def report(self):
        result=super().report()
        if self.continuous:result.update(contract=self._plan['contract'],mode='continuous',cumulative_limits=False)
        return result


class ManagementRun(HybridRun):
    channel_budget=CHANNEL_BUDGET
    quota_feedback=True

    def __init__(self, request, directory, *, async_client_factory=None, clock=None, monotonic=None,
                 event_board_device_id=None):
        import time
        self.request, self.permit = request, None
        self.web_agent = request.web_agent
        if event_board_device_id is not None and not self.web_agent:
            raise BotError('AGENT_EVENT_BOARD_NOT_APPROVED')
        self._event_board_device_id = event_board_device_id
        self._approved_event_board_device_id = None
        if request.continuous:
            from apps.ai_service.channel_management_continuous import ContinuousChannelBudget
            from apps.ai_service.channel_management_agent import AgentChannelBudget
            budget_type=AgentChannelBudget if self.web_agent else ContinuousChannelBudget
            self.channel_budget=budget_type(max_output_tokens=request.output_tokens)
        self._notice_recipient = self._notice_recipient_path = None
        self._notice_summary = None
        self._notice_report = {'enabled':False}
        self.device_event_device_id=None
        self._issuer = LivePermitIssuer(self.check)
        kwargs = dict(async_client_factory=async_client_factory, limits=request.limits, members=request.members,
                      clock=clock, monotonic=monotonic or time.monotonic,
                      event_board_device_id=event_board_device_id)
        # Inherits the existing initialization/ledger/store, not the Fake-only constructor.
        from apps.ai_service.channel_validation import ValidationBoundary
        self.boundary = ValidationBoundary(); self._issuer.boundary = self.boundary
        SessionRun._initialize(self, request.inputs, directory, **kwargs)
        if request.continuous:
            from dataclasses import replace
            self.config=replace(self.config,enabled=request.ai_enabled)

    def _inputs_snapshot(self,inputs,monitoring=None):
        from .management_config import inputs_snapshot
        return inputs_snapshot(inputs,monitoring,budget=self.channel_budget)

    def scope_for_options(self):
        if self.web_agent:
            from apps.ai_service.channel_management_agent import prepared_scope as agent_scope
            return agent_scope(self.options,output_tokens=self.request.output_tokens)
        if self.request.continuous:
            from apps.ai_service.channel_management_continuous import prepared_scope as continuous_scope
            return continuous_scope(self.options,output_tokens=self.request.output_tokens)
        return prepared_scope(self.options)

    def _prepare_sources(self, source):
        self.knowledge=None
        if self.web_agent:
            from .knowledge_source import open_readonly_knowledge
            self.knowledge=open_readonly_knowledge(source)

    def _make_service(self, **kwargs):
        if self.web_agent:
            from apps.ai_service.service import ManagementAssistantService
            return ManagementAssistantService.channel_agent(self.monitoring,self.knowledge,**kwargs)
        return super()._make_service(**kwargs)

    def _new_store(self, monotonic):
        if self.web_agent:
            from .agent_conversations import AgentConversationStore
            return AgentConversationStore(self.options,monotonic=monotonic)
        return super()._new_store(monotonic)

    def _verified_execution(self, session, report):
        if self.web_agent:
            from apps.ai_service.channel_management_agent import AgentChannelResult
            result=getattr(session,'hybrid_result',None)
            return (type(result) is AgentChannelResult and result.completed
                and result.publication is not None and result.publication.allowed
                and report['model_requests']==result.model_requests
                and result.model_requests==result.tool_executions+1
                and 0<=result.tool_executions<=2)
        return super()._verified_execution(session,report)

    def _new_ledger(self, limits):
        return ManagementLedger(self.directory, scope_sha256=self.scope_sha256,
            bindings_sha256=self._binding_digest, limits=limits, clock=self.clock, monotonic=self.now,
            output_token_limit=self.request.output_tokens,contract=self.scope['contract'],
            requests_per_turn=3 if self.web_agent else 2)

    def plan(self):
        from .management_config import CONTINUOUS_RISK
        return {**SessionRun.plan(self), 'contract': self.scope['contract'], 'offline': self.offline_test,
                'request_sha256': self.request.digest, 'risk': CONTINUOUS_RISK if self.request.continuous else RISK,
                **({'tools':list(self.config.grants[0].tools),
                    'disclosure':'SIMULATOR_CURRENT_HISTORY_PROJECT_KNOWLEDGE_EVENT_SUMMARIES_AND_NECESSARY_CONTEXT',
                    'agent_event_board_device_id':self._event_board_device_id,
                    'notice':'普通自然语言可能持续收费；最多2次只读Tool及3次模型请求。'} if self.web_agent else {}),
                **({'event_notifications':self._notice_summary} if self._notice_summary else {})}

    def approve(self, plan, *, confirmed=False):
        if not self.request.enabled: raise BotError('AI_DISABLED')
        self.request.check(); self._check_configuration()
        result = SessionRun.approve(self, plan, confirmed=confirmed)
        self._approved_event_board_device_id = plan.get('agent_event_board_device_id')
        self.permit = self._issuer.issue(scope_sha256=self.scope_sha256, bindings_sha256=self._binding_digest,
            consent_id=self.ledger._id, lease_authority=self.ledger.authority, offline=self.offline_test)
        return result

    def _check_configuration(self):
        def verify():
            if self.permit is not None and self._event_board_device_id != self._approved_event_board_device_id:
                raise BotError('AGENT_EVENT_BOARD_NOT_APPROVED')
            current = load_request(self.request.path)
            if current.digest != self.request.digest: raise BotError('MANAGEMENT_REQUEST_CHANGED')
            SessionRun._check_configuration(self)
            if self.request.continuous:
                if self.web_agent:
                    from apps.ai_service.channel_management_agent import preparation_record as continuous_record
                else:
                    from apps.ai_service.channel_management_continuous import preparation_record as continuous_record
                record_path=self.request.path.parent/'scope.json';record=continuous_record(self.scope)
            else:record_path=PREPARATION;record=preparation_record(self.scope)
            if read_json(record_path) != record:
                raise BotError('MANAGEMENT_SCOPE_REVIEW_REQUIRED')
        return validation_once(('management-live-config', id(self)), verify)

    def _turn_credentials(self):
        if self.offline_test: return None
        self.permit.check()
        location = private_project_location(ROOT)
        return CredentialStore(location.env_path, private_location=location)

    def _create_turn(self, lease, snapshot, validate):
        if self.permit is None: raise BotError('MANAGEMENT_RUN_PERMIT_REQUIRED')
        turn=ManagementLiveTurn;extra={}
        if self.request.continuous:
            from apps.ai_service.channel_management_continuous import ContinuousManagementTurn
            from apps.ai_service.channel_management_agent import AgentManagementTurn
            turn=AgentManagementTurn if self.web_agent else ContinuousManagementTurn
            extra['output_tokens']=self.request.output_tokens
            if self.web_agent:
                extra['event_board_device_id']=self._approved_event_board_device_id
        return turn(lease, permit=self.permit, authority=self.store.authority,
            conversation_epoch=self.base_service.epoch, options=self.options, snapshot=snapshot,
            validate=validate, claim=lambda: self.ledger.check_lease(lease),
            async_client_factory=self.factory, clock=self.clock, monotonic=self.now,**extra)

    def enable_event_notifications(self, recipient_path):
        from .event_recipients import load_recipient
        from .event_notifications import approval_summary
        if self.permit is not None:raise BotError('INVALID_RUN_APPROVAL')
        recipient=load_recipient(recipient_path,self.access.app_id)
        group=next(g for g in self.access.groups if g.group_id==self.inputs.group_id)
        if 'current' not in group.capabilities:raise BotError('EVENT_NOTIFICATION_PERMISSION_REQUIRED')
        self._notice_recipient,self._notice_recipient_path=recipient,recipient_path
        self._notice_summary=approval_summary(recipient,self.device_event_device_id)

    def enable_device_events(self,device_id):
        """One explicit board binding for notices, never an AI/water device grant."""
        from .contracts import identifier
        from .event_notifications import approval_summary
        if self.permit is not None:raise BotError('INVALID_RUN_APPROVAL')
        identifier(device_id)
        if device_id==self.device_id:raise BotError('DEVICE_EVENT_SOURCE_CONFLICT')
        self.device_event_device_id=device_id
        if self._notice_summary is not None:
            self._notice_summary=approval_summary(self._notice_recipient,device_id)

    def report(self,code='RUN_SNAPSHOT'):
        return {**SessionRun.report(self,code),'event_notifications':self._notice_report}
