"""规则小镇的行为检查。

仓库根目录运行：python -m unittest discover -s projects/ai-town -v
"""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from town import CONFIG_PATH, MEMORY_LIMIT, apply_action, load_world, observe, snapshot, step


class TownBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.world = load_world()

    def test_tired_resident_goes_home_then_recovers(self):
        """精力低时先回家，下一轮在家休息，而不是继续工作或聊天。"""
        resident = self.world["npcs"][0]
        resident.update(location="square", energy=20)

        step(self.world)
        self.assertEqual(resident["location"], resident["home"])
        self.assertEqual(resident["last_action"]["type"], "move")
        energy_after_travel = resident["energy"]

        step(self.world)
        self.assertEqual(resident["location"], resident["home"])
        self.assertEqual(resident["last_action"]["type"], "rest")
        self.assertGreater(resident["energy"], energy_after_travel)

    def test_rejected_actions_leave_the_whole_world_unchanged(self):
        """错误参数及不满足地点条件的动作不能留下半完成的状态。"""
        resident, other = self.world["npcs"][:2]
        resident["location"] = "square"
        other["location"] = "park"
        actions = [
            {"type": "teleport", "reason": "未知工具"},
            {"type": "move", "target": "missing-place", "reason": "未知地点"},
            {"type": "move", "target": [], "reason": "地点类型错误"},
            {"type": "talk", "target": other["id"], "reason": "跨地点聊天"},
            {"type": "talk", "target": "missing-resident", "reason": "未知居民"},
            {"type": "rest", "reason": "不在家休息"},
            {"type": "work", "reason": "不在工作地点工作"},
            {"type": "move", "target": "park", "reason": ""},
            "不是行动对象",
        ]
        for action in actions:
            with self.subTest(action=action):
                before = deepcopy(self.world)
                with self.assertRaises(ValueError):
                    apply_action(self.world, resident["id"], action)
                self.assertEqual(self.world, before)

    def test_observation_contains_only_local_people_and_own_memory(self):
        """同场居民可见，但他人的私有记忆和远处居民不会进入观察。"""
        resident, neighbor, remote = self.world["npcs"]
        resident["location"] = neighbor["location"] = "square"
        remote["location"] = "park"
        for npc, text in ((resident, "自己的经历"),
                          (neighbor, "邻居的私有记忆"),
                          (remote, "远处居民的私有记忆")):
            npc["memory"].append({"tick": 0, "text": text, "action": "work"})

        observation = observe(self.world, resident["id"])
        self.assertEqual(observation["nearby_ids"], [neighbor["id"]])
        self.assertEqual(observation["nearby"], [neighbor["name"]])
        self.assertEqual(observation["memory"], resident["memory"])
        visible_text = json.dumps(observation, ensure_ascii=False)
        for hidden_text in (remote["name"], "邻居的私有记忆", "远处居民的私有记忆"):
            self.assertNotIn(hidden_text, visible_text)

        observation["memory"][0]["text"] = "修改观察副本"
        self.assertEqual(resident["memory"][0]["text"], "自己的经历")

    def test_day_stops_at_its_limit_and_energy_stays_in_range(self):
        """短日、默认日和最长日都在约定轮数停止；停止后重复推进无效。"""
        for max_ticks in (1, 24, 96):
            with self.subTest(max_ticks=max_ticks):
                world = load_world()
                world["max_ticks"] = max_ticks
                world["npcs"][0]["energy"] = 0
                world["npcs"][1]["energy"] = 100
                for expected_tick in range(1, max_ticks + 1):
                    step(world)
                    self.assertEqual(world["tick"], expected_tick)
                    self.assertEqual(world["finished"], expected_tick == max_ticks)
                    for npc in world["npcs"]:
                        self.assertGreaterEqual(npc["energy"], 0)
                        self.assertLessEqual(npc["energy"], 100)
                finished_state = deepcopy(world)
                for _ in range(3):
                    step(world)
                    self.assertEqual(world, finished_state)

    def test_memories_are_bounded_and_belong_to_individual_residents(self):
        """长时间互动会淘汰旧记忆，旁观不到对话的人没有该段经历。"""
        speaker, listener, remote = self.world["npcs"]
        speaker["location"] = listener["location"] = "square"
        remote["location"] = "park"
        self.assertIsNot(speaker["memory"], listener["memory"])
        self.assertIsNot(speaker["memory"], remote["memory"])

        for tick in range(MEMORY_LIMIT + 5):
            self.world["tick"] = tick
            apply_action(self.world, speaker["id"],
                         {"type": "talk", "target": listener["id"], "reason": "同场打招呼"})

        for npc in (speaker, listener):
            self.assertEqual(len(npc["memory"]), MEMORY_LIMIT)
            self.assertGreater(npc["memory"][0]["tick"], 0)
            self.assertEqual(npc["memory"][-1]["tick"], MEMORY_LIMIT + 4)
        self.assertEqual(remote["memory"], [])
        listener_memory = deepcopy(listener["memory"])
        speaker["memory"][-1]["text"] = "仅修改说话者的记忆"
        self.assertEqual(listener["memory"], listener_memory)

    def test_reloading_reads_changed_energy_and_changes_behavior(self):
        """文件中的改动在重新加载后生效，不会偷偷改写已经运行的世界。"""
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        config["npcs"][0]["location"] = "square"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "world.json"
            config["npcs"][0]["energy"] = 20
            path.write_text(json.dumps(config), encoding="utf-8")
            tired_world = load_world(path)
            config["npcs"][0]["energy"] = 90
            path.write_text(json.dumps(config), encoding="utf-8")
            energetic_world = load_world(path)

        self.assertEqual(tired_world["npcs"][0]["energy"], 20)
        self.assertEqual(energetic_world["npcs"][0]["energy"], 90)
        step(tired_world)
        step(energetic_world)
        tired = tired_world["npcs"][0]
        energetic = energetic_world["npcs"][0]
        self.assertEqual(tired["location"], tired["home"])
        self.assertNotEqual(energetic["location"], energetic["home"])

    def test_invalid_config_energy_is_reported(self):
        """越界数值、非整数和布尔值都必须报告配置错误。"""
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "world.json"
            for energy in (-1, 101, 20.5, "20", True, None):
                with self.subTest(energy=energy):
                    config["npcs"][0]["energy"] = energy
                    path.write_text(json.dumps(config), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "energy"):
                        load_world(path)

    def test_snapshot_changes_cannot_mutate_the_running_world(self):
        """网页或调用者修改返回副本时，嵌套列表和字典也与世界隔离。"""
        step(self.world)
        before = deepcopy(self.world)
        state = snapshot(self.world)
        state["tick"] = 999
        state["locations"][0]["name"] = "改名后的地点"
        state["npcs"][0]["memory"][0]["text"] = "修改副本记忆"
        state["npcs"][0]["last_observation"]["energy"] = -1
        state["events"][0]["reason"] = "修改副本日志"
        self.assertEqual(self.world, before)


if __name__ == "__main__":
    unittest.main()
