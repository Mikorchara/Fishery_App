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


class ManagementLedger(HybridLedger):
    output_token_limit=OUTPUT_TOKENS

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._plan.update(contract=CONTRACT, environment='MANAGEMENT_PROCESS_RUNCONSENT')


class ManagementRun(HybridRun):
    channel_budget=CHANNEL_BUDGET

    def __init__(self, request, directory, *, async_client_factory=None, clock=None, monotonic=None):
        import time
        self.request, self.permit = request, None
        self._notice_recipient = self._notice_recipient_path = None
        self._notice_summary = None
        self._notice_report = {'enabled':False}
        self._issuer = LivePermitIssuer(self.check)
        kwargs = dict(async_client_factory=async_client_factory, limits=request.limits, members=request.members,
                      clock=clock, monotonic=monotonic or time.monotonic)
        # Inherits the existing initialization/ledger/store, not the Fake-only constructor.
        from apps.ai_service.channel_validation import ValidationBoundary
        self.boundary = ValidationBoundary(); self._issuer.boundary = self.boundary
        SessionRun._initialize(self, request.inputs, directory, **kwargs)

    def scope_for_options(self): return prepared_scope(self.options)

    def _new_ledger(self, limits):
        return ManagementLedger(self.directory, scope_sha256=self.scope_sha256,
            bindings_sha256=self._binding_digest, limits=limits, clock=self.clock, monotonic=self.now)

    def plan(self):
        return {**SessionRun.plan(self), 'contract': CONTRACT, 'offline': self.offline_test,
                'request_sha256': self.request.digest, 'risk': RISK,
                **({'event_notifications':self._notice_summary} if self._notice_summary else {})}

    def approve(self, plan, *, confirmed=False):
        if not self.request.enabled: raise BotError('AI_DISABLED')
        self.request.check(); self._check_configuration()
        result = SessionRun.approve(self, plan, confirmed=confirmed)
        self.permit = self._issuer.issue(scope_sha256=self.scope_sha256, bindings_sha256=self._binding_digest,
            consent_id=self.ledger._id, lease_authority=self.ledger.authority, offline=self.offline_test)
        return result

    def _check_configuration(self):
        def verify():
            current = load_request(self.request.path)
            if current.digest != self.request.digest: raise BotError('MANAGEMENT_REQUEST_CHANGED')
            SessionRun._check_configuration(self)
            if read_json(PREPARATION) != preparation_record(self.scope):
                raise BotError('MANAGEMENT_SCOPE_REVIEW_REQUIRED')
        return validation_once(('management-live-config', id(self)), verify)

    def _turn_credentials(self):
        if self.offline_test: return None
        self.permit.check()
        location = private_project_location(ROOT)
        return CredentialStore(location.env_path, private_location=location)

    def _create_turn(self, lease, snapshot, validate):
        if self.permit is None: raise BotError('MANAGEMENT_RUN_PERMIT_REQUIRED')
        return ManagementLiveTurn(lease, permit=self.permit, authority=self.store.authority,
            conversation_epoch=self.base_service.epoch, options=self.options, snapshot=snapshot,
            validate=validate, claim=lambda: self.ledger.check_lease(lease),
            async_client_factory=self.factory, clock=self.clock, monotonic=self.now)

    def enable_event_notifications(self, recipient_path):
        from .event_recipients import load_recipient
        from .event_notifications import approval_summary
        if self.permit is not None:raise BotError('INVALID_RUN_APPROVAL')
        recipient=load_recipient(recipient_path,self.access.app_id)
        group=next(g for g in self.access.groups if g.group_id==self.inputs.group_id)
        if 'current' not in group.capabilities:raise BotError('EVENT_NOTIFICATION_PERMISSION_REQUIRED')
        self._notice_recipient,self._notice_recipient_path=recipient,recipient_path
        self._notice_summary=approval_summary(recipient)

    def report(self,code='RUN_SNAPSHOT'):
        return {**SessionRun.report(self,code),'event_notifications':self._notice_report}
