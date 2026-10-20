"""第一阶段：用明确的 Python 规则观察 NPC 的状态变化，没有模型调用。"""

from copy import deepcopy
import json
from pathlib import Path


CONFIG_PATH = Path(__file__).with_name("world.json")
MEMORY_LIMIT = 12
EVENT_LIMIT = 72


def time_label(world):
    minutes = world["start_hour"] * 60 + world["tick"] * 30
    return f"{minutes // 60 % 24:02d}:{minutes % 60:02d}"


def load_world(path=CONFIG_PATH):
    """每次启动或重置时读取配置；错误配置不会默默变成默认值。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("world.json 最外层必须是一个对象。")
    if not isinstance(data.get("name"), str) or not data["name"].strip():
        raise ValueError("小镇需要一个非空 name。")
    for key, low, high in (("start_hour", 0, 23), ("max_ticks", 1, 96)):
        if type(data.get(key)) is not int or not low <= data[key] <= high:
            raise ValueError(f"{key} 必须是 {low} 到 {high} 之间的整数。")
    locations = data.get("locations")
    npcs = data.get("npcs")
    if not isinstance(locations, list) or not locations:
        raise ValueError("locations 必须是非空列表。")
    if not isinstance(npcs, list) or not 1 <= len(npcs) <= 12:
        raise ValueError("npcs 必须包含 1 到 12 位居民。")
    location_ids = set()
    for place in locations:
        if not isinstance(place, dict):
            raise ValueError("每个地点必须是对象。")
        for key in ("id", "name", "description"):
            if not isinstance(place.get(key), str) or not place[key].strip():
                raise ValueError(f"地点需要非空的 {key}。")
        if place["id"] in location_ids:
            raise ValueError("地点 id 不能重复。")
        location_ids.add(place["id"])
        for axis in ("x", "y"):
            if type(place.get(axis)) not in (int, float) or not 0 <= place[axis] <= 100:
                raise ValueError("地点 x/y 必须是 0 到 100 之间的数字。")
    if "square" not in location_ids:
        raise ValueError("当前规则需要一个 id 为 square 的广场。")
    npc_ids = set()
    for npc in npcs:
        if not isinstance(npc, dict):
            raise ValueError("每位居民必须是对象。")
        for key in ("id", "name", "role", "goal", "color", "work_text"):
            if not isinstance(npc.get(key), str) or not npc[key].strip():
                raise ValueError(f"居民需要非空的 {key}。")
        if npc["id"] in npc_ids:
            raise ValueError("居民 id 不能重复。")
        npc_ids.add(npc["id"])
        for key in ("location", "home", "workplace"):
            if npc.get(key) not in location_ids:
                raise ValueError(f"{npc['name']} 的 {key} 必须指向已有地点。")
        if type(npc.get("energy")) is not int or not 0 <= npc["energy"] <= 100:
            raise ValueError(f"{npc['name']} 的 energy 必须是 0 到 100 的整数。")
        npc.update(status="刚来到小镇", memory=[], last_chat_ticks={},
                   last_action=None, last_observation=None)
    data.update(tick=0, mode="rules", finished=False, events=[])
    data["time_label"] = time_label(data)
    for npc in npcs:
        npc["last_observation"] = observe(data, npc["id"])
    return data


def get_npc(world, npc_id):
    for npc in world["npcs"]:
        if npc["id"] == npc_id:
            return npc
    raise ValueError(f"未知居民：{npc_id}")


def observe(world, npc_id):
    """居民只能观察同地点的人，以及自己的状态和短期记忆。"""
    npc = get_npc(world, npc_id)
    nearby = [other for other in world["npcs"]
              if other["id"] != npc_id and other["location"] == npc["location"]]
    place = next(p for p in world["locations"] if p["id"] == npc["location"])
    return {
        "time": time_label(world), "tick": world["tick"],
        "location": place["name"], "location_id": place["id"],
        "energy": npc["energy"],
        "nearby": [other["name"] for other in nearby],
        "nearby_ids": [other["id"] for other in nearby],
        "memory": deepcopy(npc["memory"][-MEMORY_LIMIT:]),
        "last_chat_ticks": deepcopy(npc["last_chat_ticks"]),
    }


def choose_action(npc, observation):
    """规则决策器。以后接入模型时替换这里，仍保留执行端的校验。"""
    if npc["energy"] <= 30 or (npc["location"] == npc["home"] and npc["energy"] < 75):
        if npc["location"] != npc["home"]:
            return {"type": "move", "target": npc["home"], "reason": "精力不足，先回家休息。"}
        return {"type": "rest", "reason": "在家恢复精力，休息好了再出发。"}
    for person_id in observation["nearby_ids"]:
        last_chat_tick = observation["last_chat_ticks"].get(person_id)
        if last_chat_tick is not None and observation["tick"] - last_chat_tick < 4:
            continue  # 只跳过这个人，继续检查下一位附近居民。
        return {"type": "talk", "target": person_id,
                "reason": "附近有居民，且最近四轮内没有与对方交谈，打个招呼。"}
    if npc["location"] != npc["workplace"]:
        return {"type": "move", "target": npc["workplace"], "reason": "精力充足，前往自己的工作地点。"}
    if observation["tick"] % 4 == 0 and npc["energy"] > 45:
        return {"type": "move", "target": "square", "reason": "工作间歇，去广场看看有没有邻居。"}
    return {"type": "work", "reason": "已经到工作地点，完成手头的一件小事。"}


def remember(npc, tick, text, action, partner_id=None):
    entry = {"tick": tick, "text": text, "action": action}
    if partner_id is not None:
        entry["partner_id"] = partner_id
    npc["memory"].append(entry)
    del npc["memory"][:-MEMORY_LIMIT]


def apply_action(world, npc_id, action):
    """程序先检查合法性，再改变世界；无效动作不得修改任何状态。"""
    npc = get_npc(world, npc_id)
    if not isinstance(action, dict):
        raise ValueError("行动必须是对象。")
    kind = action.get("type")
    if kind not in ("move", "rest", "work", "talk"):
        raise ValueError("未知行动，只允许 move、rest、work、talk。")
    if not isinstance(action.get("reason"), str) or not action["reason"].strip():
        raise ValueError("行动需要简短说明。")
    target = action.get("target")
    places = {place["id"]: place for place in world["locations"]}
    listener = None
    if kind == "move":
        if not isinstance(target, str) or target not in places:
            raise ValueError("只能移动到地图上的已有地点。")
        text, cost = f"前往{places[target]['name']}", -5
    elif kind == "rest":
        if npc["location"] != npc["home"]:
            raise ValueError("需要先回家才能休息。")
        text, cost = "在家休息，恢复了精力", 35
    elif kind == "work":
        if npc["location"] != npc["workplace"]:
            raise ValueError("需要到达自己的工作地点才能工作。")
        text, cost = npc["work_text"], -18
    else:
        if not isinstance(target, str) or target == npc_id:
            raise ValueError("需要指定同地点的另一位居民。")
        listener = get_npc(world, target)
        if listener["location"] != npc["location"]:
            raise ValueError("只能与同一地点的居民打招呼。")
        text, cost = f"对{listener['name']}说：今天过得怎么样？忙完也记得休息！", -4
    if kind == "move":
        npc["location"] = target
    npc["energy"] = max(0, min(100, npc["energy"] + cost))
    npc["status"] = text
    npc["last_action"] = deepcopy(action)
    remember(npc, world["tick"], text, kind,
             partner_id=listener["id"] if listener is not None else None)
    if listener is not None:
        # 最近交谈轮次单独保留，不随 12 条近期事件的裁剪而遗忘。
        npc["last_chat_ticks"][listener["id"]] = world["tick"]
        listener["last_chat_ticks"][npc_id] = world["tick"]
        remember(listener, world["tick"], f"{npc['name']}向我打了招呼。", "talk",
                 partner_id=npc_id)
    world["events"].append({"tick": world["tick"], "time": time_label(world),
                            "npc_id": npc_id, "npc_name": npc["name"],
                            "action": kind, "text": text, "reason": action["reason"]})
    del world["events"][:-EVENT_LIMIT]


def step(world):
    """一轮等于小镇 30 分钟；居民依次观察和行动，不是同时行动。"""
    if world["finished"]:
        return world
    world["tick"] += 1
    for npc in world["npcs"]:
        observation = observe(world, npc["id"])
        action = choose_action(npc, observation)
        npc["last_observation"] = observation
        apply_action(world, npc["id"], action)
    world["time_label"] = time_label(world)
    world["finished"] = world["tick"] >= world["max_ticks"]
    return world


def snapshot(world):
    return deepcopy(world)
