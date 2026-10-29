"""Internal opt-ins only; the Web contract and real execution gates stay unchanged."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from apps.ai_backend.execution import RequestHandle,request_scope
from apps.ai_backend.model_gateway import ModelResponse
from apps.ai_backend.tests.support import ScriptedGateway
from apps.ai_backend.tool_conversation import ToolCallingService,ToolExecutionMode
from apps.ai_backend.tools.policy import ToolPolicy
from apps.ai_service.business_tools.registry import bind_tools
from apps.ai_service.runtime.assistant import AssistantService,AssistantRequest,AssistantError,SINGLE_ROUND_PROMPT_ID
from apps.ai_service.runtime.tests import test_foundation as foundation
from apps.ai_service.service import ManagementAssistantService


QWEN,WATER,KNOWLEDGE=foundation.QWEN,foundation.WATER,foundation.KNOWLEDGE


class M1CompositionTests(unittest.TestCase):
    setUp=foundation.FoundationTests.setUp
    registry=foundation.FoundationTests.registry

    def coordinator(self):
        class RecordingGateway(ScriptedGateway):
            def __init__(self):
                super().__init__([ModelResponse('offline answer',finish_reason='stop')]);self.requests=[]
            def complete(self,request,runtime):
                self.requests.append(request);return super().complete(request,runtime)
        self.gateway=RecordingGateway()
        return ToolCallingService(self.gateway,self.registry(),self.traces,
            policy=ToolPolicy('assistant',True,(WATER,KNOWLEDGE)),execution_mode=ToolExecutionMode.SINGLE_ROUND)

    def test_default_prompt_and_request_contract_unchanged(self):
        service=AssistantService(self.coordinator())
        self.assertEqual(service.prompt_id,SINGLE_ROUND_PROMPT_ID)
        self.assertIsNone(service._single_round_prompt)
        with self.assertRaises(AssistantError):
            AssistantRequest.from_dict({'preset_id':QWEN,'question':'x','single_round_prompt':['x','x']})

    def test_explicit_internal_prompt_uses_original_runtime_and_commit(self):
        service=AssistantService(self.coordinator(),single_round_prompt=('M1_INTERNAL_TEST@1','offline instruction'))
        handle=RequestHandle();handle.start()
        with request_scope(handle):result=service.send(AssistantRequest(QWEN,'offline question'),self.runtime)
        self.assertTrue(result.to_dict()['successful_turn'])
        self.assertEqual(handle.state,'COMPLETED')
        self.assertEqual(len(self.gateway.requests),1)
        self.assertEqual(self.gateway.requests[0].messages[0].content,'offline instruction')
        self.assertEqual(service.prompt_id,'M1_INTERNAL_TEST@1')

    def test_bad_internal_prompt_rejected_before_model(self):
        coordinator=self.coordinator()
        for value in (['ID','text'],('bad id','text'),('ID',''),('ID','x'*8193)):
            with self.subTest(value_type=type(value).__name__),self.assertRaisesRegex(AssistantError,'INVALID_ASSISTANT_PROMPT'):
                AssistantService(coordinator,single_round_prompt=value)
        self.assertEqual(self.gateway.requests,[])

    def test_water_only_registry_is_explicit_and_does_not_register_knowledge(self):
        monitoring=SimpleNamespace(capture_water=Mock())
        knowledge=Mock()
        default=bind_tools(monitoring,'pond-a',knowledge)
        limited=bind_tools(monitoring,'pond-a',None,include_knowledge=False)
        self.assertEqual(default.registered_names(),(WATER,KNOWLEDGE))
        self.assertEqual(limited.registered_names(),(WATER,))
        with self.assertRaises(Exception):limited.lookup(KNOWLEDGE)
        knowledge.assert_not_called();monitoring.capture_water.assert_not_called()
        with self.assertRaisesRegex(ValueError,'INVALID_BUSINESS_TOOL_ASSEMBLY'):
            bind_tools(monitoring,'pond-a',None,include_knowledge='false')

    def test_web_still_requires_knowledge_and_creates_no_policy(self):
        directory=self.root/'must-not-create'
        credentials=Mock()
        with self.assertRaisesRegex(ValueError,'KNOWLEDGE_SERVICE_REQUIRED'):
            ManagementAssistantService(SimpleNamespace(devices=lambda:[{'id':'pond-a'}]),knowledge=None,
                credentials=credentials,traces=self.traces,policy_directory=directory)
        self.assertFalse(directory.exists());credentials.resolve.assert_not_called()


if __name__=='__main__':unittest.main()
