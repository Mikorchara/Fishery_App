"""Offline request checks for server-owned instructions after tool results."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from apps.ai_backend.contracts import Mode, Status
from apps.ai_backend.credentials import CredentialStore
from apps.ai_backend.execution import RequestHandle, request_scope
from apps.ai_backend.model_gateway import ModelMessage, ModelProfile, ModelRequest, ModelToolDefinition, ProfileRegistry
from apps.ai_backend.model_options import ModelCapabilities, Support
from apps.ai_backend.observability import JsonlTraceSink
from apps.ai_backend.openai_compatible_adapter import OpenAICompatibleAdapter
from apps.ai_backend.providers import AuthSpec
from apps.ai_backend.tests.support import FakeSDK, final_chunks, sdk_final, sdk_tool, tool_chunks
from apps.ai_backend.tool_conversation import ToolCallingService, ToolExecutionMode, ToolModelTransport
from apps.ai_backend.tools import ToolDefinition, ToolRegistry
from apps.ai_backend.tools.policy import ToolPolicy


class ToolResultGuidanceTests(unittest.TestCase):
    def setUp(self):
        url = "http://mock.invalid/v1"
        capabilities = ModelCapabilities(tool_calling=Support.SUPPORTED, streaming=Support.SUPPORTED,
            service_id="custom", adapter_id="generic_openai_chat", model_id="fixture-model", base_url=url)
        profile = ModelProfile("fixture", "Fixture", "local", url, "fixture-model",
            auth_spec=AuthSpec.NONE, max_retries=0, capabilities=capabilities)
        self.runtime = ProfileRegistry([profile], CredentialStore(process_env={})).snapshot("fixture")

    def run_turn(self, definitions, plans, messages, transport=ToolModelTransport.NORMAL):
        registry = ToolRegistry(definitions)
        sdk = FakeSDK(plans)
        def forbid_sync_client(*_):
            raise AssertionError("offline tests must use the fake SDK")

        gateway = OpenAICompatibleAdapter(client_factory=forbid_sync_client, async_client_factory=sdk.factory)
        policy = ToolPolicy("assistant", True, registry.registered_names())
        with TemporaryDirectory() as temp:
            service = ToolCallingService(gateway, registry, JsonlTraceSink(Path(temp) / "trace"),
                execution_mode=ToolExecutionMode.BOUNDED_MULTI_ROUND,
                model_transport=transport, policy=policy)
            handle = RequestHandle()
            handle.start()
            with request_scope(handle):
                result = service.run_request(ModelRequest(Mode.CHAT, messages), self.runtime)
        return result, sdk.bodies

    def test_guidance_follows_successful_tools_in_normal_and_streaming_requests(self):
        payload = {"status": "OK", "detail": "From the result, never part of the system."}
        definitions = (
            ToolDefinition(ModelToolDefinition("first", "First tool", {"type": "object"}),
                lambda: payload, result_instruction="Explain the first result."),
            ToolDefinition(ModelToolDefinition("second", "Second tool", {"type": "object"}),
                lambda: {"status": "NO_DATA"}, result_instruction="Explain the second result."),
            ToolDefinition(ModelToolDefinition("unused", "Unused tool", {"type": "object"}),
                lambda: {"status": "OK"}, result_instruction="Unused result explanation."),
        )
        messages = (ModelMessage("system", "Common rules."), ModelMessage("user", "Check the sources."))
        for transport, plans in (
            (ToolModelTransport.NORMAL, [sdk_tool("first", "call_1"), sdk_tool("second", "call_2"), sdk_final()]),
            (ToolModelTransport.STREAMING, [tool_chunks("first", "call_1"), tool_chunks("second", "call_2"), final_chunks()]),
        ):
            with self.subTest(transport=transport):
                result, bodies = self.run_turn(definitions, plans, messages, transport)
                self.assertEqual(result.status, Status.COMPLETED, result.error_code)
                initial, after_first, after_second = bodies
                first_system = "Common rules.\n\nTool result guidance (first):\nExplain the first result."
                final_system = first_system + "\n\nTool result guidance (second):\nExplain the second result."
                self.assertEqual(initial["messages"], [
                    {"role": "system", "content": "Common rules."},
                    {"role": "user", "content": "Check the sources."},
                ])
                self.assertEqual(after_first["messages"][0], {"role": "system", "content": first_system})
                self.assertEqual(after_second["messages"][0], {"role": "system", "content": final_system})
                self.assertEqual([m["role"] for m in after_second["messages"]],
                    ["system", "user", "assistant", "tool", "assistant", "tool"])
                self.assertEqual(after_second["messages"][1:4], after_first["messages"][1:])
                self.assertEqual(json.loads(after_first["messages"][-1]["content"]), payload)
                self.assertEqual(after_first["messages"][-1]["tool_call_id"], "call_1")
                self.assertEqual(json.loads(after_second["messages"][-1]["content"]), {"status": "NO_DATA"})
                self.assertEqual(after_second["messages"][-1]["tool_call_id"], "call_2")
                self.assertEqual(after_second["tools"], initial["tools"])
                self.assertEqual([b["tool_choice"] for b in bodies], ["auto", "auto", "none"])

    def test_no_initial_system_and_repeated_tool_keeps_one_instruction(self):
        definition = ToolDefinition(ModelToolDefinition("read", "Read by index", {"type": "object"}),
            lambda args: {"status": "OK", **args}, validate_arguments=lambda args: args,
            result_instruction="Preserve the record index.")
        plans = [sdk_tool("read", "call_1", '{"index":1}'),
                 sdk_tool("read", "call_2", '{"index":2}'), sdk_final()]
        result, bodies = self.run_turn([definition], plans, (ModelMessage("user", "Read two records."),))
        self.assertEqual(result.status, Status.COMPLETED, result.error_code)
        self.assertEqual(bodies[0]["messages"], [{"role": "user", "content": "Read two records."}])
        expected = {"role": "system", "content": "Tool result guidance (read):\nPreserve the record index."}
        self.assertEqual(bodies[1]["messages"][0], expected)
        self.assertEqual(bodies[2]["messages"][0], expected)
        self.assertEqual(sum(m["role"] == "system" for m in bodies[2]["messages"]), 1)

    def test_invalid_tool_call_does_not_add_a_followup_request(self):
        definition = ToolDefinition(ModelToolDefinition("read", "Read only", {"type": "object"}),
            lambda: {"status": "OK"}, result_instruction="Read result guidance.")
        result, bodies = self.run_turn([definition], [sdk_tool("read", arguments='{"extra":true}')],
                                       (ModelMessage("user", "Check the source."),))
        self.assertEqual(result.error_code, "INVALID_TOOL_ARGUMENTS")
        self.assertEqual(len(bodies), 1)
        self.assertEqual(bodies[0]["messages"], [{"role": "user", "content": "Check the source."}])
