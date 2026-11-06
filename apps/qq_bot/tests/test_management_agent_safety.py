"""Four-tool channel boundaries, with new SQLite and memory-only SDK/QQ I/O."""
import asyncio
from dataclasses import replace
import hashlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx
from openai import AsyncOpenAI

from apps.qq_bot.tests import test_management_agent as fixture


class ManagementAgentSafetyTests(unittest.TestCase):
    compose = fixture.ManagementAgentTests.compose
    receive = fixture.ManagementAgentTests.receive
    ask = fixture.ManagementAgentTests.ask

    def setUp(self):
        fixture.ManagementAgentTests.setUp(self)

    def factory(self, runtime, remaining):
        if self.mode != 'blocked':
            return fixture.ManagementAgentTests.factory(self, runtime, remaining)

        async def blocked(request):
            self.http.append(json.loads(request.content))
            self.started.set()
            await asyncio.Event().wait()

        return AsyncOpenAI(api_key='fictional', base_url=runtime.base_url, max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(blocked),
                                         trust_env=False, follow_redirects=False))

    def test_unapproved_channel_cannot_read_or_request_model(self):
        self.compose(approve=False)
        with self.assertRaises(Exception):
            self.host.check()
        self.assertEqual(self.http, [])
        self.host.approve(self.host.plan(), confirmed=True)
        # A separate composition is unnecessary: the run has not attached a
        # Gateway or scheduler, and must not create a Provider at approval.
        self.assertEqual(self.http, [])
        self.assertEqual(self.host.ledger.report()['consumed_turns'], 0)

    def test_unknown_member_and_duplicate_do_not_consume_or_repeat_four_tool_work(self):
        self.compose()
        self.plan = (('get_current_water_quality', {}),)
        self.assertNotEqual(self.receive(member='outsider')[0], 'AI_ADMITTED')
        self.assertEqual(self.http, [])
        self.assertEqual(self.host.ledger.report()['consumed_turns'], 0)
        code, task = self.receive('查询本轮资料', message_id='unique-message')
        self.assertEqual(code, 'AI_ADMITTED')
        done = self.scheduler.wait(task, 95)
        self.assertEqual(done.get('history_code'), 'HISTORY_COMMITTED', done)
        self.assertNotEqual(self.receive('查询本轮资料', message_id='unique-message')[0], 'AI_ADMITTED')
        self.assertEqual((len(self.http), len(self.posts)), (2, 1))
        report = self.host.ledger.report()
        self.assertEqual(report['consumed_turns'], 1)
        self.assertEqual(report['reserved_model_requests'], 3)

    def test_busy_and_queued_duplicate_do_not_execute_or_reserve_again(self):
        self.compose()
        self.mode = 'blocked'
        code, first = self.receive('第一条独立问题', member='member-a')
        self.assertEqual(code, 'AI_ADMITTED')
        self.assertTrue(self.started.wait(10), 'memory SDK request was not started')
        self.assertEqual(self.receive('同一成员第二条', member='member-a')[0], 'QQ_REPLY_API_ACCEPTED')
        self.assertIn('AI_SESSION_BUSY', self.posts[-1]['content'])
        code, second = self.receive('另一成员排队', member='member-b')
        self.assertEqual(code, 'AI_ADMITTED')
        self.assertEqual(self.receive('同一排队成员再次请求', member='member-b')[0], 'QQ_REPLY_API_ACCEPTED')
        self.assertIn('AI_SESSION_BUSY', self.posts[-1]['content'])
        self.assertEqual(self.host.ledger.report()['consumed_turns'], 2)
        self.assertEqual(len(self.http), 1)
        self.scheduler.cancel_all()
        for task in (first, second):
            self.assertNotEqual(self.scheduler.wait(task, 15)['state'], 'DELIVERED')
        self.assertEqual((len(self.http), len(self.posts)), (1, 2))
        self.scheduler.close()
        self.assertTrue(all(not thread.is_alive() for thread in self.scheduler._threads))

    def test_permission_revoked_while_sdk_running_cancels_and_closes_without_delivery(self):
        self.compose()
        self.mode = 'blocked'
        code, task = self.receive('查询授权资料')
        self.assertEqual(code, 'AI_ADMITTED')
        self.assertTrue(self.started.wait(10))
        self.coordinator.reconfigure(replace(self.coordinator.config, enabled=False))
        done = self.scheduler.wait(task, 15)
        self.assertNotEqual(done['state'], 'DELIVERED', done)
        self.assertEqual(self.posts, [])
        self.assertEqual(self.host.store.counts()['turns'], 0)
        self.assertEqual(done['sdk_resources']['state'], 'CLOSED')
        self.assertTrue(done['sdk_resources']['thread_exited'])
        self.assertNotEqual(self.receive()[0], 'AI_ADMITTED')
        self.assertEqual(len(self.http), 1)

    def test_policy_change_during_io_cancels_without_tool_or_history(self):
        self.compose()
        self.mode = 'blocked'
        code, task = self.receive('查询项目知识')
        self.assertEqual(code, 'AI_ADMITTED')
        self.assertTrue(self.started.wait(10))
        path = self.path.parent/'policy/management_assistant_policy.json'
        policy = json.loads(path.read_text(encoding='utf8'))
        policy.update(generation=policy['generation']+1, selected_tools=[])
        path.write_text(json.dumps(policy), encoding='utf8')
        done = self.scheduler.wait(task, 15)
        self.assertNotEqual(done['state'], 'DELIVERED', done)
        self.assertEqual((len(self.http), len(self.posts)), (1, 0))
        self.assertEqual(self.host.store.counts()['turns'], 0)
        self.assertEqual(done['sdk_resources']['state'], 'CLOSED')
        self.assertTrue(done['sdk_resources']['thread_exited'])
        self.assertNotEqual(self.receive()[0], 'AI_ADMITTED')

    def test_scope_record_change_refuses_before_any_model_request(self):
        self.compose()
        path = self.path.parent/'scope.json'
        value = json.loads(path.read_text(encoding='utf8'))
        value['scope_sha256'] = '0'*64
        path.write_text(json.dumps(value), encoding='utf8')
        self.assertNotEqual(self.receive('一般问题')[0], 'AI_ADMITTED')
        self.assertEqual((self.http, self.posts), ([], []))
        self.assertEqual(self.host.ledger.report()['consumed_turns'], 0)

    def test_unknown_tool_delivery_never_retries_or_commits_history(self):
        self.compose()
        for name, arguments in (
            ('get_current_water_quality', {}),
            ('get_water_quality_history', {'lookback_minutes': 10}),
            ('search_fishery_knowledge', {'query': '溶解氧'}),
            ('score_current_water_quality', {}),
        ):
            with self.subTest(tool=name):
                self.plan = ((name, arguments),)
                self.outcomes[0] = 'UNKNOWN'
                before = len(self.http), len(self.posts)
                done = self.ask('请查询本轮授权资料')
                self.assertEqual(done['state'], 'DELIVERY_UNKNOWN', done)
                self.assertFalse(done['api_accepted'])
                self.assertEqual((len(self.http)-before[0], len(self.posts)-before[1]), (2, 1))
                self.assertEqual(self.host.store.counts()['turns'], 0)
                self.assertEqual(done['sdk_resources']['state'], 'CLOSED')
                self.assertTrue(done['sdk_resources']['thread_exited'])
        report = self.host.ledger.report()
        self.assertEqual(report['consumed_turns'], 4)
        self.assertEqual(report['reserved_model_requests'], 12)

    def test_clear_after_api_acceptance_prevents_old_history_cas_without_resend(self):
        self.compose()
        accept = self.coordinator.accept_delivery

        def clear_then_accept(plan, result, text, receipt, cancelled):
            snapshot = plan.prepared.channel_history
            key = self.host.store._issued[snapshot.ticket][1]
            self.host.store.clear(key)
            return accept(plan, result, text, receipt, cancelled)

        with patch.object(self.coordinator, 'accept_delivery', side_effect=clear_then_accept):
            done = self.ask('一般概念解释')
        self.assertEqual(done['state'], 'DELIVERED', done)
        self.assertTrue(done['api_accepted'])
        self.assertEqual(done['history_code'], 'HISTORY_NOT_COMMITTED')
        self.assertEqual((len(self.http), len(self.posts)), (1, 1))
        self.assertEqual(self.host.store.counts()['turns'], 0)
        accepted = self.scheduler.take_acceptances()
        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0]['text_sha256'], hashlib.sha256(self.posts[0]['content'].encode()).hexdigest())

    def test_same_instance_sources_are_readonly_and_history_cannot_rebind(self):
        self.compose()
        monitoring = self.host.monitoring
        knowledge = self.host.knowledge
        self.assertEqual(knowledge.repository.path, self.root/'instance/knowledge.sqlite3')
        self.assertTrue(knowledge.repository.read_only)
        self.assertTrue(monitoring._service.repository.read_only)
        before = {p: p.read_bytes() for p in (knowledge.repository.path, monitoring.path)}
        with self.assertRaisesRegex(Exception, 'KNOWLEDGE_READ_ONLY'):
            with knowledge.repository.connection(write=True):
                self.fail('write must be rejected before connection')
        with self.assertRaises(Exception):
            with monitoring._service.repository.connection(write=True):
                self.fail('write must be rejected before connection')
        for query in (monitoring.capture_water,
                      lambda device: monitoring.query_water_history(device, lookback_minutes=10)):
            with self.assertRaisesRegex(Exception, 'MONITORING_DEVICE_NOT_APPROVED'):
                query('other-device')
        message = SimpleNamespace(group_id='group-a', member_id='member-a')
        key, _ = self.coordinator.conversation_context(message)
        for changes in ({'instance_id': 'other-instance'}, {'device_id': 'other-device'}):
            snapshot = self.host.store.snapshot(key.replace(**changes), focus='说明概念')
            try:
                with self.assertRaisesRegex(Exception, 'RUN_HISTORY_BINDING_CHANGED'):
                    self.host.begin(snapshot, message=message)
            finally:
                self.host.store.release(snapshot)
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertEqual(self.http, [])
        self.assertEqual(self.host.ledger.report()['consumed_turns'], 0)
