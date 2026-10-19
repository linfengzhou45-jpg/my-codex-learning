"""文字入口：直接观察与网页相同的世界更新。"""

import argparse
from town import load_world, step


def main():
    parser = argparse.ArgumentParser(description="运行规则驱动的晨光小镇，不调用模型。")
    parser.add_argument("--steps", type=int, default=6, help="推进轮数，默认 6，最多为配置中的 max_ticks")
    args = parser.parse_args()
    if args.steps < 0:
        parser.error("--steps 不能为负数")
    try:
        world = load_world()
    except (OSError, ValueError) as error:
        parser.exit(1, f"小镇配置读取失败：{error}\n")
    print(f"{world['name']} | 规则演示 | {world['time_label']}")
    for _ in range(min(args.steps, world["max_ticks"])):
        step(world)
        print(f"\n第 {world['tick']} 轮 · {world['time_label']}")
        for event in world["events"]:
            if event["tick"] == world["tick"]:
                print(f"  {event['npc_name']}：{event['text']}（{event['reason']}）")


if __name__ == "__main__":
    main()
