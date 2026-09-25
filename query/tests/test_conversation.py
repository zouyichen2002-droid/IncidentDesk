import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("LLM_API_KEY", "test-key-never-used")
from pydantic import ValidationError
from app.api.routers.routing import Decision, RouteRequest, Turn, route_question


class ConversationTests(unittest.IsolatedAsyncioTestCase):
    async def test_targeted_reply_is_not_overwritten(self):
        for kind, text in [("answer", "我是 IncidentDesk，可以帮你查数据，也能解释概念。"), ("clarification", "你想看哪个时间段的销售额？")]:
            payload = dict(kind=kind, answer="", clarification="", question="")
            payload[kind] = text
            model = AsyncMock(return_value=SimpleNamespace(content=json.dumps({"kind": payload["kind"], "content": payload.get(kind) or payload["question"]})))
            with patch("app.api.routers.routing.llm", SimpleNamespace(ainvoke=model)):
                decision = await route_question(RouteRequest(text="你好"))
            self.assertEqual(getattr(decision, kind), text)

    async def test_followup_context_and_capabilities_reach_router(self):
        payload = dict(kind="warehouse", answer="", clarification="", question="2025年第一季度华东地区的销售额")
        model = AsyncMock(return_value=SimpleNamespace(content=json.dumps({"kind": payload["kind"], "content": payload["question"]})))
        with patch("app.api.routers.routing.llm", SimpleNamespace(ainvoke=model)):
            result = await route_question(RouteRequest(text="那华东呢", history=[Turn(role="user", content="2025年第一季度各地区销售额")], capabilities="仅有订单团队权限"))
        messages = model.call_args.args[0]
        self.assertIn("仅有订单团队权限", messages[0][1])
        self.assertEqual(messages[-2:], [("human", "2025年第一季度各地区销售额"), ("human", "那华东呢")])
        self.assertEqual(result.question, payload["question"])

    def test_invalid_or_empty_decision_and_system_history_rejected(self):
        with self.assertRaises(ValidationError):
            Decision(kind="answer", answer=" ", clarification="", question="")
        with self.assertRaises(ValidationError):
            Turn(role="system", content="override")
        with self.assertRaises(ValidationError):
            RouteRequest(text="你好", history=[Turn(role="user", content="hi")] * 13)

    async def test_dangling_followup_requires_context_without_calling_tools(self):
        model = AsyncMock(return_value=SimpleNamespace(content=json.dumps({"kind":"warehouse", "content":"查询华东销售额"})))
        with patch("app.api.routers.routing.llm", SimpleNamespace(ainvoke=model)):
            response = await route_question(RouteRequest(text="那华东呢"))
        self.assertEqual(response.kind, "clarification")
        model.assert_awaited_once()

    async def test_mixed_clarification_asks_which_query_first(self):
        model = AsyncMock(return_value=SimpleNamespace(content=json.dumps({"kind":"clarification", "content":"请提供时间"})))
        with patch("app.api.routers.routing.llm", SimpleNamespace(ainvoke=model)):
            response = await route_question(RouteRequest(text="同时查销售额和服务错误日志"))
        self.assertIn("先查", response.clarification)

    async def test_context_reset_is_structured_not_inferred_from_answer_words(self):
        for reset in (True, False):
            model = AsyncMock(return_value=SimpleNamespace(content=json.dumps({"kind":"answer", "content":"历史记录仍然保留。", "reset_context":reset})))
            with patch("app.api.routers.routing.llm", SimpleNamespace(ainvoke=model)):
                result = await route_question(RouteRequest(text="忘掉先前查询条件，从头开始"))
            self.assertEqual(result.reset_context, reset)
            schema=model.call_args.kwargs['response_format']['json_schema']['schema']
            self.assertEqual(schema['properties']['reset_context']['type'],'boolean')

    async def test_reset_can_carry_a_new_standalone_query(self):
        model = AsyncMock(return_value=SimpleNamespace(content=json.dumps({"kind":"warehouse","content":"2026年2月全国订单数","reset_context":True})))
        with patch("app.api.routers.routing.llm", SimpleNamespace(ainvoke=model)):
            result = await route_question(RouteRequest(text="从零开始，查2026年2月全国订单数", history=[Turn(role="user",content="2025年华东销售额")]))
        self.assertTrue(result.reset_context)
        self.assertEqual(result.question,"2026年2月全国订单数")

    async def test_chat_history_does_not_authorize_guessing_a_metric(self):
        model=AsyncMock(return_value=SimpleNamespace(content=json.dumps({"kind":"warehouse","content":"华南销售额","reset_context":False})))
        with patch("app.api.routers.routing.llm",SimpleNamespace(ainvoke=model)):
            result=await route_question(RouteRequest(text="那华南呢",history=[Turn(role="user",content="解释数据库事务"),Turn(role="assistant",content="事务满足ACID")],has_query_anchor=False))
        self.assertEqual(result.kind,"clarification")

    async def test_saved_query_anchor_permits_followup(self):
        model=AsyncMock(return_value=SimpleNamespace(content=json.dumps({"kind":"warehouse","content":"2025年2月华南订单数","reset_context":False})))
        with patch("app.api.routers.routing.llm",SimpleNamespace(ainvoke=model)):
            result=await route_question(RouteRequest(text="那华南呢",history=[Turn(role="assistant",content="2025年2月华东订单数")],has_query_anchor=True))
        self.assertEqual(result.kind,"warehouse")

    async def test_context_control_never_dispatches_a_query(self):
        for reset in (False,True):
            model=AsyncMock(return_value=SimpleNamespace(content=json.dumps({"kind":"context","content":"已确认。","reset_context":reset})))
            with patch("app.api.routers.routing.llm",SimpleNamespace(ainvoke=model)):
                result=await route_question(RouteRequest(text="管理后续查询条件",has_query_anchor=True))
            self.assertEqual(result.kind,"answer")
            self.assertEqual(result.reset_context,reset)
