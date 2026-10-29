"""Separate per-Turn real-trial contract; never promotes a Fake candidate."""
from dataclasses import asdict
import hashlib
from pathlib import Path

from apps.ai_backend.model_gateway import GatewayError
from apps.ai_backend.tool_conversation import ToolExecutionMode
from .channel import ChannelBudget
from .channel_conversation import INSTRUCTION,PROMPT_ID,validate_options
from .channel_trial import QwenTrialSession,PRESET,fast_trial_scope
from .execution import ExecutionDecision
from .runtime.assistant import assistant_profile
from .runtime.release_contracts import _hash,AssistantExecutionProfile

CONTRACT='qq-qwen-conversation-turn-trial@1'


def trial_scope(profile,policy,registry,options):
    from .channel_validation import implementation_sha256
    options=validate_options(options)
    if options['trigger_mode']!='mention_ai' or options['memory_enabled'] is not True:
        raise GatewayError('CONVERSATION_TRIAL_MENTION_REQUIRED')
    # Reuse SDK/cost definitions, not its approval or published qualification.
    base=fast_trial_scope(profile,policy,registry)
    runtime=dict(base['base_scope']['runtime'])
    runtime.update(prompt_id=PROMPT_ID,prompt_sha256=_hash(INSTRUCTION))
    root=Path(__file__).parents[1]
    extra = ('ai_service/channel_conversation_trial.py',)
    return dict(contract=CONTRACT,runtime=runtime,conversation=options,
        implementation={**base['implementation'],**{p:implementation_sha256(root/p) for p in extra}},
        sdk=base['base_scope']['backend'],transport=base['transport'],cost=base['cost'],
        process={'max_model_turns':2,'independent_approval_per_turn':True,'max_seconds':600},
        execution={'mode':'SINGLE_ROUND','model_requests':2,'tool_calls':1,'tool_rounds':1,
            'max_output_tokens':512,'turn_timeout_s':90,'retries':0},
        history='SERVER_SNAPSHOT_UNTRUSTED_TRANSCRIPT_V1',commit='API_ACCEPTED_SAFE_TEXT_CAS@1',
        presentation=base['presentation'],source_requirement='CURRENT_OBSERVATION_QUERY',
        isolation=base['isolation'])


def prepared_scope(options):
    from apps.ai_backend.tools import ToolDefinition,ToolRegistry
    from apps.ai_backend.tools.policy import ToolPolicy
    from .business_tools.current_water_quality import WATER_DEFINITION
    return trial_scope(assistant_profile(PRESET),ToolPolicy('assistant',True,('get_current_water_quality',)),
        ToolRegistry((ToolDefinition(WATER_DEFINITION,lambda:None),)),asdict(options))


def candidate_record(scope):
    return dict(schema_version=1,contract=CONTRACT,status='candidate',qualification_id=None,
        scope=scope,scope_sha256=_hash(scope),real_execution_requires='PER_TURN_OPERATOR_APPROVAL')

