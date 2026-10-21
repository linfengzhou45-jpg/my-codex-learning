"""模型接线与失败边界测试；全部使用伪响应，不会调用真实付费接口。"""

from copy import deepcopy
from http.client import HTTPException
import io
import json
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen as local_urlopen

from model import DeepSeekDecider, ModelError, NoRedirect, build_context
from server import TownServer
from town import choose_action, load_world, observe, step


TEST_KEY = "sk-local-test-secret-do-not-use"
TEST_MODEL = "test-model"


def response_bytes(action=None, *, content=None, finish_reason="stop"):
    """模仿服务响应外壳；动作仍交给真实解析与执行代码检查。"""
    if content is None:
        content = json.dumps(action or {"type": "move", "target": "cafe",
                                      "reason": "去准备咖啡。"}, ensure_ascii=False)
    return json.dumps({
        "model": TEST_MODEL,
        "choices": [{"finish_reason": finish_reason,
                     "message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130},
    }).encode("utf-8")


class FakeDecider:
    """只替代外部模型，保留整轮调度和执行器的真实逻辑。"""

    model = TEST_MODEL
    max_calls = 5

    def __init__(self, action=None, error=None):
        self.action = action
        self.error = error
        self.calls_used = 0
        self.residents = []

    def decide(self, world, npc, observation):
        self.calls_used += 1
        self.residents.append(npc["id"])
        if self.error:
            raise self.error
        return deepcopy(self.action), {
            "source": "model", "model": self.model,
            "input": {"context": build_context(world, npc, observation)},
            "action": deepcopy(self.action), "usage": {},
        }

    def public_status(self):
        return {"provider": "DeepSeek", "model": self.model, "npc_id": "lin",
                "calls_used": self.calls_used, "max_calls": self.max_calls}


class ModelBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.world = load_world()
        self.npc = self.world["npcs"][0]

    def test_request_uses_selected_model_json_and_only_header_credentials(self):
        decider = DeepSeekDecider(TEST_KEY, TEST_MODEL, timeout=7, max_calls=2)
        with patch("model.urlopen", return_value=io.BytesIO(response_bytes())) as opened:
            action, trace = decider.decide(self.world, self.npc,
                                           observe(self.world, self.npc["id"]))
        opened.assert_called_once()
        request = opened.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(request.full_url, "https://api.deepseek.com/chat/completions")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer " + TEST_KEY)
        self.assertEqual(opened.call_args.kwargs["timeout"], 7)
        self.assertEqual(body["model"], TEST_MODEL)
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertIs(body["stream"], False)
        self.assertEqual(body["max_tokens"], 800)
        self.assertEqual(action["target"], "cafe")
        self.assertEqual(trace["action"], action)
        self.assertEqual(trace["usage"]["total_tokens"], 130)
        for public in (body, trace, decider.public_status()):
            self.assertNotIn(TEST_KEY, json.dumps(public))

    def test_model_context_contains_only_own_history_and_visible_people(self):
        first, neighbor, remote = self.world["npcs"]
        first["memory"].append({"tick": 0, "action": "work", "text": "我的亲历事件"})
        neighbor["memory"].append({"tick": 0, "action": "work", "text": "邻居的私密记忆"})
        remote["location"] = "park"
        remote["name"] = "远处名字不应可见"
        remote["memory"].append({"tick": 0, "action": "work", "text": "远处居民的私密记忆"})
        self.world["events"].append({"text": "全知日志不应直接发给模型"})
        context = build_context(self.world, first, observe(self.world, first["id"]))
        serialized = json.dumps(context, ensure_ascii=False)
        for visible in (first["name"], first["goal"], neighbor["name"], "我的亲历事件"):
            self.assertIn(visible, serialized)
        for hidden in ("邻居的私密记忆", remote["name"], "远处居民的私密记忆",
                       "全知日志不应直接发给模型"):
            self.assertNotIn(hidden, serialized)
        context["observation"]["memory"][0]["text"] = "修改请求副本"
        self.assertEqual(first["memory"][0]["text"], "我的亲历事件")

    def test_provider_errors_are_redacted_and_do_not_retry(self):
        failures = [
            HTTPError("https://api.deepseek.com/chat/completions", code, "secret " + TEST_KEY,
                      {}, io.BytesIO(("provider body " + TEST_KEY).encode()))
            for code in (401, 429, 500)
        ] + [TimeoutError(TEST_KEY), URLError(TEST_KEY), HTTPException(TEST_KEY)]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__, status=getattr(failure, "code", None)):
                decider = DeepSeekDecider(TEST_KEY, TEST_MODEL)
                before = deepcopy(self.world)
                with patch("model.urlopen", side_effect=failure) as opened:
                    with self.assertRaises(ModelError) as raised:
                        step(self.world, model_decider=decider)
                self.assertNotIn(TEST_KEY, str(raised.exception))
                self.assertNotIn("provider body", str(raised.exception))
                self.assertEqual(self.world, before)
                self.assertEqual(decider.calls_used, 1)
                opened.assert_called_once()

    def test_invalid_and_truncated_responses_leave_world_unchanged(self):
        invalid_actions = [
            [],
            {"type": "teleport", "reason": "不支持的动作"},
            {"type": "move", "target": "unknown-place", "reason": "未知地点"},
            {"type": "move", "target": [], "reason": "错误类型"},
            {"type": "move", "target": "cafe", "reason": " "},
            {"type": "move", "target": "cafe", "reason": "长" * 301},
            {"type": "move", "target": "cafe", "reason": "带未知字段", "energy": 100},
            {"type": "rest", "reason": "广场上不能休息"},
            {"type": "talk", "target": "lan", "reason": "缺少实际对白"},
            {"type": "talk", "target": "lan", "reason": "空对白", "speech": " "},
            {"type": "talk", "target": "lan", "reason": "过长对白", "speech": "长" * 501},
        ]
        payloads = [json.dumps({"choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps(action, ensure_ascii=False)}}]}).encode()
                    for action in invalid_actions]
        payloads += [b"not-json", b"{}", b'{"choices": []}',
                     response_bytes(content="not-json"), response_bytes(content=" "),
                     response_bytes(finish_reason="length")]
        for index, payload in enumerate(payloads):
            with self.subTest(case=index):
                world = load_world()
                before = deepcopy(world)
                decider = DeepSeekDecider(TEST_KEY, TEST_MODEL)
                with patch("model.urlopen", return_value=io.BytesIO(payload)) as opened:
                    with self.assertRaises((ModelError, ValueError)):
                        step(world, model_decider=decider)
                self.assertEqual(world, before)
                self.assertEqual(decider.calls_used, 1)
                opened.assert_called_once()

    def test_failed_attempt_consumes_budget_and_exhaustion_makes_no_request(self):
        decider = DeepSeekDecider(TEST_KEY, TEST_MODEL, max_calls=1)
        with patch("model.urlopen", side_effect=TimeoutError("test timeout")) as opened:
            for _ in range(2):
                with self.assertRaises(ModelError):
                    decider.decide(self.world, self.npc, observe(self.world, self.npc["id"]))
            opened.assert_called_once()
        self.assertEqual(decider.calls_used, 1)

    def test_missing_or_invalid_credentials_fail_before_any_network_request(self):
        invalid = [("", TEST_MODEL), (TEST_KEY, "")]
        invalid += [(key, TEST_MODEL) for key in (
            "假测试密钥", "fake key", "fake\tkey", "fake\nkey", "fake\x00key", "fake\x7fkey",
        )]
        with patch("model.urlopen") as opened:
            for index, (key, model_name) in enumerate(invalid):
                with self.subTest(case=index):
                    with self.assertRaises(ModelError) as raised:
                        DeepSeekDecider(key, model_name)
                    if key:
                        self.assertNotIn(key, str(raised.exception))
            opened.assert_not_called()

    def test_redirect_does_not_forward_credentials_or_expose_destination(self):
        request = Request("https://api.deepseek.com/chat/completions", data=b"{}",
                          headers={"Authorization": "Bearer " + TEST_KEY})
        handler = NoRedirect()
        for status in (301, 302, 303, 307, 308):
            with self.subTest(status=status):
                with self.assertRaises(ModelError) as raised:
                    handler.redirect_request(request, None, status, "redirect", {},
                                             "https://redirect.invalid/" + TEST_KEY)
                self.assertNotIn(TEST_KEY, str(raised.exception))
                self.assertNotIn("redirect.invalid", str(raised.exception))

    def test_only_lin_uses_model_and_speech_reaches_both_memories(self):
        first, neighbor, _ = self.world["npcs"]
        first["energy"] = 20
        first["last_chat_ticks"][neighbor["id"]] = 0
        speech = "阿岚，明天要不要一起来试试新咖啡？"
        decider = FakeDecider({"type": "talk", "target": neighbor["id"],
                               "reason": "先邀请朋友，之后再安排休息。", "speech": speech})
        with patch("town.choose_action", wraps=choose_action) as rules:
            result = step(self.world, model_decider=decider)
        self.assertEqual(decider.residents, ["lin"])
        self.assertEqual([call.args[0]["id"] for call in rules.call_args_list], ["lan", "qiao"])
        first, neighbor, _ = result["npcs"]
        self.assertEqual(result["tick"], 1)
        self.assertEqual(first["last_action"]["type"], "talk")
        self.assertEqual(first["location"], "square")
        self.assertEqual(first["energy"], 16)
        for npc in (first, neighbor):
            self.assertTrue(any(speech in item["text"] for item in npc["memory"]))
        self.assertTrue(any(speech in event["text"] for event in result["events"]))

    def test_late_model_failure_rolls_back_earlier_residents_too(self):
        # 故意让一位规则居民先行动，确保回滚覆盖整轮而不只是小林。
        self.world["npcs"] = [self.world["npcs"][1], self.world["npcs"][0], self.world["npcs"][2]]
        before = deepcopy(self.world)
        decider = FakeDecider(error=ModelError("模拟模型失败"))
        with self.assertRaises(ModelError):
            step(self.world, model_decider=decider)
        self.assertEqual(self.world, before)
        self.assertEqual(decider.residents, ["lin"])

    def test_finished_world_does_not_call_model(self):
        self.world["finished"] = True
        before = deepcopy(self.world)
        decider = FakeDecider(error=AssertionError("停止后不该调用模型"))
        result = step(self.world, model_decider=decider)
        self.assertEqual(result, before)
        self.assertEqual(decider.calls_used, 0)

    def test_reset_keeps_budget_and_public_state_never_contains_key(self):
        decider = DeepSeekDecider(TEST_KEY, TEST_MODEL, max_calls=2)
        with patch("model.urlopen", return_value=io.BytesIO(response_bytes())):
            decider.decide(self.world, self.npc, observe(self.world, self.npc["id"]))
        server = TownServer(("127.0.0.1", 0), model_decider=decider)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            initial = server.state()
            self.assertEqual(initial["mode"], "mixed")
            self.assertEqual(initial["model_runtime"]["calls_used"], 1)
            lin = next(npc for npc in initial["npcs"] if npc["id"] == "lin")
            self.assertEqual(lin["controller"], "model")
            request = Request(f"http://127.0.0.1:{server.server_address[1]}/api/reset",
                              data=b"{}", headers={"Content-Type": "application/json"})
            with local_urlopen(request, timeout=5) as response:
                reset = json.load(response)
            self.assertEqual(reset["tick"], 0)
            self.assertEqual(reset["mode"], "mixed")
            self.assertEqual(reset["model_runtime"]["calls_used"], 1)
            self.assertEqual(decider.calls_used, 1)
            self.assertNotIn(TEST_KEY, json.dumps(reset))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
