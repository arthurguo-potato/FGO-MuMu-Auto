from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from .adb import AdbError, MuMuDevice
from .calibration import (
    CalibrationCancelled,
    calibrate_battle_enemy_class,
    calibrate_enemy_class,
    calibrate_rule,
    calibrate_support_candidate,
)
from .class_affinity import ICON_CLASS_NAMES
from .config import ConfigError, ensure_user_config, load_config, resolve_from_config
from .runner import BotRunner, PauseRequested
from .strategy import SupportSelector
from .vision import (
    TemplateMatcher,
    VisionError,
    annotate_match,
    read_image,
    write_image,
)


DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "profiles" / "fgo_cn_1600x900.yaml"
USER_CONFIG = DEFAULT_CONFIG.with_name("user.yaml")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="MuMu 模拟器 FGO 保守型主线自动化",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="YAML 配置文件路径；省略时使用 profiles/user.yaml",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("gui", help="打开图形控制面板")
    commands.add_parser("doctor", help="检查 MuMu、ADB、分辨率和模板")

    snapshot = commands.add_parser("snapshot", help="保存当前模拟器截图")
    snapshot.add_argument("--output", default="current-screen.png")

    rules = commands.add_parser("rules", help="列出规则和标定状态")
    rules.add_argument("--scores", action="store_true", help="同时对当前画面评分")

    calibrate = commands.add_parser("calibrate", help="框选并保存某个识别模板")
    calibrate.add_argument("--rule", required=True, help="规则名称")
    calibrate.add_argument("--input", help="从已有截图标定，而不是实时截图")

    enemy_class = commands.add_parser(
        "calibrate-enemy-class",
        help="标定关卡详情中的敌方职阶图标",
    )
    enemy_class.add_argument(
        "--class",
        dest="class_name",
        choices=ICON_CLASS_NAMES,
        required=True,
    )
    enemy_class.add_argument("--input", help="从已有截图标定")

    battle_enemy_class = commands.add_parser(
        "calibrate-battle-class",
        help="标定战斗界面中的敌方职阶图标",
    )
    battle_enemy_class.add_argument(
        "--class",
        dest="class_name",
        choices=ICON_CLASS_NAMES,
        required=True,
    )
    battle_enemy_class.add_argument("--input", help="从已有战斗截图标定")

    support = commands.add_parser(
        "calibrate-support",
        help="登记一个宝具5全体宝具助战候选",
    )
    support.add_argument("--id", dest="candidate_id", required=True)
    support.add_argument("--name", required=True)
    support.add_argument(
        "--class",
        dest="class_name",
        choices=ICON_CLASS_NAMES,
        required=True,
    )
    support.add_argument(
        "--np-color",
        choices=("buster", "arts", "quick"),
        required=True,
    )
    support.add_argument("--level", type=int, default=120)
    support.add_argument("--priority", type=int, default=0)
    support.add_argument("--party-slot", type=int, choices=(1, 2, 3), default=3)
    support.add_argument("--input", help="从已有助战列表截图标定")

    match = commands.add_parser("match", help="只识别一次并保存标注图")
    match.add_argument("--input", help="已有截图；省略则读取 MuMu")
    match.add_argument("--output", default="match-result.png")

    run = commands.add_parser("run", help="启动状态机")
    mode = run.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="只识别，不点击")
    mode.add_argument("--live", action="store_true", help="允许实际点击")
    return parser


def _build_device(config: dict[str, Any]) -> MuMuDevice:
    device = config["device"]
    return MuMuDevice(
        device.get("manager_path"),
        int(device.get("vm_index", 0)),
    )


def _show_rules(
    config: dict[str, Any],
    config_path: Path,
    matcher: TemplateMatcher,
) -> None:
    print("规则状态（配置顺序即识别优先级）：")
    available = set(matcher.available_rules)
    for rule in config["rules"]:
        path = resolve_from_config(config_path, rule["template"])
        if not rule.get("enabled", True):
            status = "已禁用"
        elif rule["name"] in available:
            status = "可用"
        else:
            status = "缺少模板"
        print(
            f"  {rule['name']:<22} {status:<8} "
            f"{rule['action']:<10} {path}"
        )


def _doctor(
    device: MuMuDevice,
    config: dict[str, Any],
    config_path: Path,
    matcher: TemplateMatcher,
) -> int:
    info = device.connect()
    print(f"MuMu：{info.name}（实例 {info.vm_index}）")
    print(f"Android：{info.android_version}；状态：{info.player_state}")
    print(f"ADB：{info.serial}")
    screen = device.capture()
    height, width = screen.shape[:2]
    expected = (
        int(config["screen"]["base_width"]),
        int(config["screen"]["base_height"]),
    )
    print(f"截图：{width}x{height}；配置基准：{expected[0]}x{expected[1]}")
    package = device.foreground_package()
    wanted = config["device"].get("package")
    print(f"前台包名：{package or '未知'}")
    if wanted and package != wanted:
        print(f"警告：预期包名为 {wanted}")
    scores = matcher.scores(screen)[:5]
    if scores:
        print("当前画面匹配：")
        for name, score in scores:
            print(f"  {name:<22} {score:.3f}")
    selector = SupportSelector(config, config_path)
    print(
        f"敌方职阶模板：{len(selector.enemy_templates)}；"
        f"合格助战候选：{selector.qualified_candidate_count}"
    )
    _show_rules(config, config_path, matcher)
    if (width, height) != expected:
        print("提示：分辨率不一致时会自动缩放模板，但重新标定更可靠。")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        selected_config = (
            Path(args.config).expanduser().resolve()
            if args.config
            else ensure_user_config(DEFAULT_CONFIG, USER_CONFIG)
        )
        config, config_path = load_config(selected_config)
        device = _build_device(config)
        matcher = TemplateMatcher(config, config_path)

        if args.command == "gui":
            from .gui import launch_gui

            launch_gui(config, config_path, device)
            return 0

        if args.command == "doctor":
            return _doctor(device, config, config_path, matcher)

        if args.command == "snapshot":
            output = Path(args.output).expanduser().resolve()
            write_image(output, device.capture())
            print(f"已保存：{output}")
            return 0

        if args.command == "rules":
            _show_rules(config, config_path, matcher)
            if args.scores:
                for name, score in matcher.scores(device.capture()):
                    print(f"  score {name:<22} {score:.3f}")
            return 0

        if args.command == "calibrate":
            input_path = Path(args.input).resolve() if args.input else None
            target = calibrate_rule(
                device,
                config,
                config_path,
                args.rule,
                input_path=input_path,
            )
            print(f"标定完成：{target}")
            return 0

        if args.command == "calibrate-enemy-class":
            input_path = Path(args.input).resolve() if args.input else None
            target = calibrate_enemy_class(
                device,
                config,
                config_path,
                args.class_name,
                input_path=input_path,
            )
            print(f"敌方职阶标定完成：{target}")
            return 0

        if args.command == "calibrate-battle-class":
            input_path = Path(args.input).resolve() if args.input else None
            target = calibrate_battle_enemy_class(
                device,
                config,
                config_path,
                args.class_name,
                input_path=input_path,
            )
            print(f"战斗敌方职阶标定完成：{target}")
            return 0

        if args.command == "calibrate-support":
            input_path = Path(args.input).resolve() if args.input else None
            target = calibrate_support_candidate(
                device,
                config,
                config_path,
                candidate_id=args.candidate_id,
                name=args.name,
                class_name=args.class_name,
                np_color=args.np_color,
                servant_level=args.level,
                priority=args.priority,
                party_slot=args.party_slot,
                input_path=input_path,
            )
            print(f"助战候选登记完成：{target}")
            return 0

        if args.command == "match":
            screen = read_image(Path(args.input).resolve()) if args.input else device.capture()
            result = matcher.find_first(screen)
            output = Path(args.output).expanduser().resolve()
            if result is None:
                write_image(output, screen)
                print(f"未命中任何规则；原图保存为：{output}")
                return 2
            write_image(output, annotate_match(screen, result))
            print(
                f"命中 {result.rule['name']}，置信度 {result.score:.3f}；"
                f"标注图：{output}"
            )
            return 0

        if args.command == "run":
            runner = BotRunner(
                device,
                matcher,
                config,
                config_path,
                dry_run=bool(args.dry_run),
            )
            try:
                runner.run()
            except KeyboardInterrupt:
                runner.stop()
                print("\n收到 Ctrl+C，已停止。")
            return 0

        raise ConfigError(f"未知命令：{args.command}")
    except CalibrationCancelled as exc:
        print(f"标定已取消：{exc}", file=sys.stderr)
        return 2
    except PauseRequested as exc:
        print(f"已安全暂停：{exc.reason}", file=sys.stderr)
        if exc.snapshot:
            print(f"现场截图：{exc.snapshot}", file=sys.stderr)
        return 2
    except (AdbError, ConfigError, VisionError, OSError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
