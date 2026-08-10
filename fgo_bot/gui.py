from __future__ import annotations

import ctypes
import queue
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import filedialog, ttk
from tkinter.scrolledtext import ScrolledText

from .adb import AdbError, MuMuDevice
from .config import ConfigError, load_config, save_config
from .runner import BotRunner, PauseRequested
from .strategy import SupportSelector
from .vision import TemplateMatcher, VisionError


BATTLE_RULE_GROUPS: list[
    tuple[str, list[tuple[str, str, str]]]
] = [
    (
        "目标选择",
        [
            (
                "prefer_class_advantage",
                "优先攻击克制职阶",
                "识别敌方职阶后，优先选择当前输出从者能够克制的敌人。",
            ),
            (
                "single_np_high_hp",
                "单体宝具优先高血量",
                "准备释放单体宝具时，在同等职阶关系下优先打血量最高者。",
            ),
            (
                "prefer_imminent_charge",
                "优先攻击即将满充能",
                "普通攻击优先压制充能接近满格的敌人。",
            ),
        ],
    ),
    (
        "宝具策略",
        [
            (
                "use_ready_np",
                "任意从者宝具满100%时使用",
                "检测所有前排位置，包括主力、辅助和替补上场后的从者。",
            ),
            (
                "use_support_nps",
                "释放辅助与弱化型宝具",
                "允许使用增益、防御、控制或对敌方施加负面效果的非输出宝具。",
            ),
            (
                "prefer_support_np_first",
                "辅助宝具优先于输出宝具",
                "同回合多个宝具就绪时，先施加增益或弱化，再释放输出宝具。",
            ),
            (
                "prefer_aoe_for_multiple",
                "多敌人优先群体宝具",
                "敌人不少于两名时，把群体攻击宝具排在单体宝具之前。",
            ),
            (
                "use_multiple_ready_nps",
                "同回合释放多个已满宝具",
                "多个宝具同时就绪时，允许在同一回合连续释放。",
            ),
        ],
    ),
    (
        "技能策略",
        [
            (
                "use_skills",
                "每回合自动判断技能",
                "在点击攻击前检查战况与技能按钮状态。",
            ),
            (
                "use_all_frontline_skills",
                "检查每位前排从者的三个技能",
                "每回合检查九个技能位置；替补上场后也按当前位置继续判断。",
            ),
            (
                "reuse_skills_after_cooldown",
                "冷却结束后再次释放",
                "技能重新亮起且条件仍满足时，允许再次使用。",
            ),
            (
                "confirm_skill_use",
                "自动确认技能使用",
                "出现“技能使用”确认框时自动点击“决定”，再继续选人或下一个技能。",
            ),
            (
                "accelerate_skill_animations",
                "单击加速技能动画",
                "无选人时短暂检查弹窗后立即单击；需要选人时点中目标后立即在左侧安全空白处单击一次。",
            ),
              (
                  "use_charge_skills",
                  "使用宝具充能技能",
                  "主力宝具显示数值未满100%时使用群充和定向充能。",
              ),
              (
                  "prioritize_charge_for_main",
                  "主力未满100%时充能技能优先",
                  "数值识别未满100%时，把已登记的群充和定向充能排在普通增益之前。",
              ),
            (
                "use_attack_buffs",
                "使用攻击强化技能",
                "宝具或主要输出前使用已配置的攻击强化。",
            ),
            (
                "use_evasion_skills",
                "危险时使用回避技能",
                "低血量、前排减员或敌方充能危险时使用回避或无敌技能。",
            ),
            (
                "use_guts_skills",
                "危险时使用毅力技能",
                "替补低血量、前排减员或敌方充能危险时使用毅力提高生存能力。",
            ),
            (
                "use_support_skills",
                "使用关卡限定助战技能",
                "固定助战的技能冷却结束后自动释放。",
            ),
            (
                "use_replacement_skills",
                "使用替补输出技能",
                "固定主力退场后，逐个使用替补输出的可用技能。",
            ),
        ],
    ),
    (
        "指令卡策略",
        [
            (
                "prefer_primary_output_cards",
                "优先选择主力输出手指令卡",
                "识别主力助战卡牌；有多张主力卡时优先用于普通攻击与宝具后的补卡。",
            ),
            (
                "prefer_damage_role_over_class",
                "主力输出权重高于普通职阶克制",
                "已识别主力输出卡时，优先使用高攻击输出手；普通克制只作为加分项，避免辅助术阶包办攻击。",
            ),
            (
                "prefer_card_class_advantage",
                "优先克制并避开抵抗指令卡",
                "读取卡面“克制/抵抗”标记，提高克制卡权重并降低抵抗卡权重。",
            ),
            (
                "prefer_same_servant_chain",
                "优先同一从者三连",
                "三张同一从者指令卡获得额外选卡权重。",
            ),
            (
                "prefer_same_color_chain",
                "优先同色链",
                "同色指令卡或宝具同色链获得额外权重。",
            ),
            (
                "prefer_arts_chain",
                "优先三蓝 Arts Chain",
                "三张均为Arts时给予额外高权重；默认关闭，关闭后仍按伤害、职阶、同人物、同色和三色综合判断。",
            ),
            (
                "prefer_high_critical_cards",
                "优先高暴击概率指令卡",
                "同角色、同色等连携收益相同时，优先选择卡面暴击概率更高的组合。",
            ),
            (
                "prefer_mighty_chain",
                "优先三色 Mighty Chain",
                "Buster、Arts、Quick 三色组合获得额外权重。",
            ),
            (
                "prefer_np_charge_cards",
                "主力宝具未满时优先充能卡",
                "先检查充能技能；技能不可用时，额外提高位置3主力的Arts/Quick卡权重并优先Arts。",
            ),
        ],
    ),
    (
        "队伍",
        [
            (
                "continue_with_replacement",
                "主力退场后继续战斗",
                "选择仍存活的替补输出，继续技能、宝具和攻击卡流程。",
            ),
        ],
    ),
]

SUPPORT_RULE_GROUPS: list[
    tuple[str, list[tuple[str, str, str]]]
] = [
    (
        "第1步｜限定客将处理",
        [
            (
                "use_forced_support",
                "仅有客将时自动选择",
                "默认/狂阶审计列表完整翻到底且全程没有普通玩家助战时，选择当前页最合适的客将。",
            ),
            (
                "exclude_guest_support",
                "普通搜索排除客将从者",
                "普通助战列表跳过系统客将/NPC；只有完整扫描确认无普通助战后才会例外。",
            ),
        ],
    ),
    (
        "第2步｜搜索列表来源",
        [
            (
                "use_system_recommended_list",
                "使用系统默认列表",
                "默认关闭：直接切到狂阶搜索；开启后按“游戏当前默认列表 → 狂阶”搜索。",
            ),
            (
                "use_berserker_fallback",
                "搜索狂阶列表",
                "默认搜索入口；开启系统默认列表时，作为每个等级档的第二搜索列表。",
            ),
            (
                "prefer_class_advantage",
                "记录关卡职阶克制信息",
                "识别关卡主要敌人并记录完整职阶相性，供助战与后续战斗判断使用。",
            ),
        ],
    ),
    (
        "第3步｜等级档与列表顺序（每项可独立跳过）",
        [
            (
                "search_recommended_level_120",
                "系统默认列表：120级",
                "仅在开启“使用系统默认列表”时执行。",
            ),
            (
                "search_berserker_level_120",
                "狂阶列表：120级",
                "默认从此阶段开始；若启用系统默认列表，则在其120级阶段之后执行。",
            ),
            (
                "search_recommended_level_110",
                "系统默认列表：110～119级",
                "仅在开启“使用系统默认列表”时执行。",
            ),
            (
                "search_berserker_level_110",
                "狂阶列表：110～119级",
                "狂阶120级没有候选后执行。",
            ),
            (
                "search_recommended_level_100",
                "系统默认列表：100～109级",
                "仅在开启“使用系统默认列表”时执行。",
            ),
            (
                "search_berserker_level_100",
                "狂阶列表：100～109级",
                "最后在狂阶列表搜索100～109级候选。",
            ),
        ],
    ),
    (
        "第4步｜每个等级档的质量条件",
        [
            (
                "require_np5",
                "要求宝具等级为5",
                "每个等级档都只选择画面中确认宝具等级为5的助战。",
            ),
            (
                "prefer_aoe_np",
                "优先群体攻击宝具",
                "先完整搜索本地已登记的群体宝具；当前列表和等级档没有时，再回到顶部选择同等级的宝具5候选。",
            ),
            (
                "require_aoe_np",
                "只允许群体攻击宝具",
                "硬性限制，只选择本地已登记并确认是群体攻击宝具的从者；默认关闭，开启后不再回退到单体、辅助或未登记宝具。",
            ),
            (
                "prefer_registered_candidates",
                "优先已登记助战模板",
                "用本地登记模板确认从者身份、职阶和宝具类型；放宽阶段仍优先选择已登记的优质候选。",
            ),
        ],
    ),
    (
        "第5步｜扩大列表搜索范围",
        [
            (
                "scroll_support_list",
                "当前列表向下滚动查找",
                "当前可见区域没有合格助战时，继续向下检查后续条目。",
            ),
            (
                "refresh_support_list",
                "全部阶段均未找到时刷新",
                "所有已启用且已勾选的阶段完成仍无结果时，按配置次数刷新并从第一阶段重来。",
            ),
        ],
    ),
    (
        "第6步｜战后好友处理",
        [
            (
                "auto_send_friend_request",
                "战后自动申请好友",
                "默认开启；战后出现好友申请页时点击“申请好友”。取消后改点“结束”，仍会继续主线流程。",
            ),
        ],
    ),
]


SUPPORT_RULE_DEFAULTS: dict[str, bool] = {
    "use_system_recommended_list": False,
    "require_aoe_np": False,
}

BATTLE_RULE_DEFAULTS: dict[str, bool] = {
    "prefer_arts_chain": False,
}


class FgoControlPanel:
    def __init__(
        self,
        root: tk.Tk,
        config: dict[str, Any],
        config_path: Path,
        device: MuMuDevice,
    ) -> None:
        self.root = root
        self.config = config
        self.config_path = config_path
        self.device = device
        self.connected = False
        self.running = False
        self.runner: BotRunner | None = None
        self.worker: threading.Thread | None = None
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()

        self.status_text = tk.StringVar(value="未连接 MuMu")
        self.status_color = tk.StringVar(value="#8a8f98")
        self.device_text = tk.StringVar(value="请先手动连接模拟器")
        self.template_text = tk.StringVar(value="")
        self.rule_summary_text = tk.StringVar(value="")
        self.battle_rule_vars: dict[str, tk.BooleanVar] = {}
        self.support_rule_summary_text = tk.StringVar(value="")
        self.support_rule_vars: dict[str, tk.BooleanVar] = {}

        self._configure_window()
        self._build_layout()
        self._refresh_template_status()
        self._set_controls()
        self.root.after(100, self._drain_events)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _configure_window(self) -> None:
        self.root.title("FGO 主线自动推进")
        self.root.geometry("920x720")
        self.root.minsize(780, 600)
        self.root.configure(background="#f3f5f7")

        style = ttk.Style(self.root)
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 18, "bold"))
        style.configure("Sub.TLabel", font=("Microsoft YaHei UI", 10))
        style.configure("Status.TLabel", font=("Microsoft YaHei UI", 12, "bold"))
        style.configure(
            "Main.TButton",
            font=("Microsoft YaHei UI", 11),
            padding=(16, 10),
        )

    def _build_layout(self) -> None:
        container = ttk.Frame(self.root, padding=20)
        container.pack(fill=tk.BOTH, expand=True)

        ttk.Label(container, text="FGO 主线自动推进", style="Title.TLabel").pack(
            anchor=tk.W
        )
        ttk.Label(
            container,
            text="MuMu 模拟器 · 截图识别 · 未知界面自动暂停",
            style="Sub.TLabel",
        ).pack(anchor=tk.W, pady=(2, 10))

        notebook = ttk.Notebook(container)
        notebook.pack(fill=tk.BOTH, expand=True)
        control_tab = ttk.Frame(notebook, padding=(12, 14))
        support_tab = ttk.Frame(notebook, padding=(12, 14))
        rules_tab = ttk.Frame(notebook, padding=(12, 14))
        notebook.add(control_tab, text="运行控制")
        notebook.add(support_tab, text="助战策略")
        notebook.add(rules_tab, text="战斗规则")

        status_card = ttk.LabelFrame(control_tab, text="当前状态", padding=14)
        status_card.pack(fill=tk.X)

        status_row = ttk.Frame(status_card)
        status_row.pack(fill=tk.X)
        self.status_dot = tk.Label(
            status_row,
            text="●",
            font=("Segoe UI Symbol", 17),
            foreground=self.status_color.get(),
            background="#f3f5f7",
        )
        self.status_dot.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(
            status_row,
            textvariable=self.status_text,
            style="Status.TLabel",
        ).pack(side=tk.LEFT)

        ttk.Label(
            status_card,
            textvariable=self.device_text,
            style="Sub.TLabel",
            wraplength=680,
        ).pack(anchor=tk.W, pady=(8, 0))
        ttk.Label(
            status_card,
            textvariable=self.template_text,
            style="Sub.TLabel",
            wraplength=680,
        ).pack(anchor=tk.W, pady=(4, 0))

        buttons = ttk.Frame(control_tab)
        buttons.pack(fill=tk.X, pady=16)

        self.connect_button = ttk.Button(
            buttons,
            text="连接 MuMu",
            style="Main.TButton",
            command=self.connect_mumu,
        )
        self.connect_button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        self.toggle_button = ttk.Button(
            buttons,
            text="开启自动推进主线",
            style="Main.TButton",
            command=self.toggle_automation,
        )
        self.toggle_button.pack(
            side=tk.LEFT,
            fill=tk.X,
            expand=True,
            padx=(8, 0),
        )

        log_card = ttk.LabelFrame(control_tab, text="运行日志", padding=8)
        log_card.pack(fill=tk.BOTH, expand=True)
        self.log_view = ScrolledText(
            log_card,
            wrap=tk.WORD,
            height=14,
            font=("Microsoft YaHei UI", 9),
            state=tk.DISABLED,
            background="#111827",
            foreground="#dbeafe",
            insertbackground="#ffffff",
            relief=tk.FLAT,
            padx=10,
            pady=8,
        )
        self.log_view.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            control_tab,
            text="提示：关闭自动推进只停止脚本，不会关闭 MuMu 或游戏。",
            style="Sub.TLabel",
        ).pack(anchor=tk.W, pady=(10, 0))

        self._build_support_rules(support_tab)
        self._build_battle_rules(rules_tab)

    def _build_support_rules(self, parent: ttk.Frame) -> None:
        ttk.Label(
            parent,
            text=(
                "规则按编号组成通用助战流程；每一项都可独立关闭。"
                "默认优先群体宝具，但不把它设为硬条件；"
                "狂阶完整翻到底且全程只有客将时，才自动选择客将。"
            ),
            style="Sub.TLabel",
            wraplength=780,
        ).pack(anchor=tk.W)

        toolbar = ttk.Frame(parent)
        toolbar.pack(fill=tk.X, pady=(8, 8))
        ttk.Label(
            toolbar,
            textvariable=self.support_rule_summary_text,
            style="Status.TLabel",
        ).pack(side=tk.LEFT)
        ttk.Button(
            toolbar,
            text="全部启用",
            command=lambda: self._set_all_support_rules(True),
        ).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(
            toolbar,
            text="全部取消",
            command=lambda: self._set_all_support_rules(False),
        ).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(
            toolbar,
            text="恢复默认",
            command=self._restore_support_rule_defaults,
        ).pack(side=tk.RIGHT)

        scroll_host = ttk.Frame(parent)
        scroll_host.pack(fill=tk.BOTH, expand=True)
        canvas = tk.Canvas(
            scroll_host,
            background="#f3f5f7",
            highlightthickness=0,
        )
        scrollbar = ttk.Scrollbar(
            scroll_host,
            orient=tk.VERTICAL,
            command=canvas.yview,
        )
        rule_list = ttk.Frame(canvas)
        rule_window = canvas.create_window((0, 0), window=rule_list, anchor=tk.NW)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        rule_list.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(rule_window, width=event.width),
        )

        configured = self.config.get("support", {}).get(
            "strategy_options",
            {},
        )
        for group_name, options in SUPPORT_RULE_GROUPS:
            group = ttk.LabelFrame(rule_list, text=group_name, padding=(12, 8))
            group.pack(fill=tk.X, pady=(0, 8), padx=(0, 4))
            for key, label, description in options:
                row = ttk.Frame(group)
                row.pack(fill=tk.X, pady=3)
                default_value = SUPPORT_RULE_DEFAULTS.get(key, True)
                variable = tk.BooleanVar(
                    value=bool(configured.get(key, default_value))
                )
                self.support_rule_vars[key] = variable
                ttk.Checkbutton(
                    row,
                    text=label,
                    variable=variable,
                    command=self._update_support_rule_summary,
                ).pack(anchor=tk.W)
                ttk.Label(
                    row,
                    text=description,
                    style="Sub.TLabel",
                    wraplength=720,
                ).pack(anchor=tk.W, padx=(24, 0))

        affinity_card = ttk.LabelFrame(
            rule_list,
            text="职阶克制速查（攻击方 → 被克制方）",
            padding=(12, 8),
        )
        affinity_card.pack(fill=tk.X, pady=(0, 8), padx=(0, 4))
        ttk.Label(
            affinity_card,
            text=(
                "剑 → 枪 → 弓 → 剑　｜　骑 → 术 → 杀 → 骑\n"
                "裁 → 月癌 → 仇 → 裁　｜　Alter Ego → Foreigner "
                "→ Pretender → Alter Ego\n"
                "狂阶克制多数职阶但被多数职阶克制；盾阶等倍。"
                "Beast 的相性随具体灵基变化，不能只凭 Beast 图标统一判断。"
            ),
            style="Sub.TLabel",
            wraplength=720,
            justify=tk.LEFT,
        ).pack(anchor=tk.W)

        save_bar = ttk.Frame(parent)
        save_bar.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(
            save_bar,
            text="保存后，下次启动自动推进时生效。",
            style="Sub.TLabel",
        ).pack(side=tk.LEFT)
        ttk.Button(
            save_bar,
            text="保存助战策略",
            style="Main.TButton",
            command=self.save_support_rules,
        ).pack(side=tk.RIGHT)
        self._update_support_rule_summary()

    def _update_support_rule_summary(self) -> None:
        total = len(self.support_rule_vars)
        enabled = sum(variable.get() for variable in self.support_rule_vars.values())
        self.support_rule_summary_text.set(f"已启用 {enabled}/{total} 项")

    def _set_all_support_rules(self, enabled: bool) -> None:
        for variable in self.support_rule_vars.values():
            variable.set(enabled)
        self._update_support_rule_summary()

    def _restore_support_rule_defaults(self) -> None:
        for key, variable in self.support_rule_vars.items():
            variable.set(SUPPORT_RULE_DEFAULTS.get(key, True))
        self._update_support_rule_summary()

    def save_support_rules(self) -> None:
        try:
            config, config_path = load_config(self.config_path)
            strategy_options = config.setdefault("support", {}).setdefault(
                "strategy_options",
                {},
            )
            for key, variable in self.support_rule_vars.items():
                strategy_options[key] = bool(variable.get())
            save_config(config, config_path)
            self.config = config
        except (ConfigError, OSError) as exc:
            self._append_log(f"保存助战策略失败：{exc}")
            self._set_status("助战策略保存失败", "#dc2626")
            return

        self._update_support_rule_summary()
        enabled = sum(variable.get() for variable in self.support_rule_vars.values())
        self._append_log(f"助战策略已保存：启用 {enabled} 项")
        if self.running:
            self._append_log("当前流程仍使用启动时策略；停止并重新开启后应用新设置")

    def _build_battle_rules(self, parent: ttk.Frame) -> None:
        ttk.Label(
            parent,
            text="按需组合战斗规则；“优先三蓝”默认关闭，其余规则默认开启。",
            style="Sub.TLabel",
        ).pack(anchor=tk.W)

        toolbar = ttk.Frame(parent)
        toolbar.pack(fill=tk.X, pady=(8, 8))
        ttk.Label(
            toolbar,
            textvariable=self.rule_summary_text,
            style="Status.TLabel",
        ).pack(side=tk.LEFT)
        ttk.Button(
            toolbar,
            text="全部启用",
            command=lambda: self._set_all_battle_rules(True),
        ).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(
            toolbar,
            text="全部取消",
            command=lambda: self._set_all_battle_rules(False),
        ).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(
            toolbar,
            text="恢复默认",
            command=self._restore_battle_rule_defaults,
        ).pack(side=tk.RIGHT)

        scroll_host = ttk.Frame(parent)
        scroll_host.pack(fill=tk.BOTH, expand=True)
        canvas = tk.Canvas(
            scroll_host,
            background="#f3f5f7",
            highlightthickness=0,
        )
        scrollbar = ttk.Scrollbar(
            scroll_host,
            orient=tk.VERTICAL,
            command=canvas.yview,
        )
        rule_list = ttk.Frame(canvas)
        rule_window = canvas.create_window((0, 0), window=rule_list, anchor=tk.NW)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        def resize_rule_list(_event: tk.Event[Any]) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def resize_rule_window(event: tk.Event[Any]) -> None:
            canvas.itemconfigure(rule_window, width=event.width)

        rule_list.bind("<Configure>", resize_rule_list)
        canvas.bind("<Configure>", resize_rule_window)

        configured = self.config.get("battle", {}).get("rule_options", {})
        for group_name, options in BATTLE_RULE_GROUPS:
            group = ttk.LabelFrame(rule_list, text=group_name, padding=(12, 8))
            group.pack(fill=tk.X, pady=(0, 8), padx=(0, 4))
            for key, label, description in options:
                row = ttk.Frame(group)
                row.pack(fill=tk.X, pady=3)
                default_value = BATTLE_RULE_DEFAULTS.get(key, True)
                variable = tk.BooleanVar(
                    value=bool(configured.get(key, default_value))
                )
                self.battle_rule_vars[key] = variable
                ttk.Checkbutton(
                    row,
                    text=label,
                    variable=variable,
                    command=self._update_rule_summary,
                ).pack(anchor=tk.W)
                ttk.Label(
                    row,
                    text=description,
                    style="Sub.TLabel",
                    wraplength=720,
                ).pack(anchor=tk.W, padx=(24, 0))

        save_bar = ttk.Frame(parent)
        save_bar.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(
            save_bar,
            text="保存后，下次启动自动推进时生效。",
            style="Sub.TLabel",
        ).pack(side=tk.LEFT)
        ttk.Button(
            save_bar,
            text="保存战斗规则",
            style="Main.TButton",
            command=self.save_battle_rules,
        ).pack(side=tk.RIGHT)
        self._update_rule_summary()

    def _update_rule_summary(self) -> None:
        total = len(self.battle_rule_vars)
        enabled = sum(variable.get() for variable in self.battle_rule_vars.values())
        self.rule_summary_text.set(f"已启用 {enabled}/{total} 项")

    def _set_all_battle_rules(self, enabled: bool) -> None:
        for variable in self.battle_rule_vars.values():
            variable.set(enabled)
        self._update_rule_summary()

    def _restore_battle_rule_defaults(self) -> None:
        for key, variable in self.battle_rule_vars.items():
            variable.set(BATTLE_RULE_DEFAULTS.get(key, True))
        self._update_rule_summary()

    def save_battle_rules(self) -> None:
        try:
            config, config_path = load_config(self.config_path)
            rule_options = config.setdefault("battle", {}).setdefault(
                "rule_options", {}
            )
            for key, variable in self.battle_rule_vars.items():
                rule_options[key] = bool(variable.get())
            save_config(config, config_path)
            self.config = config
        except (ConfigError, OSError) as exc:
            self._append_log(f"保存战斗规则失败：{exc}")
            self._set_status("战斗规则保存失败", "#dc2626")
            return

        self._update_rule_summary()
        enabled = sum(variable.get() for variable in self.battle_rule_vars.values())
        self._append_log(f"战斗规则已保存：启用 {enabled} 项")
        if self.running:
            self._append_log("当前战斗仍使用启动时规则；停止并重新开启后应用新规则")

    def _set_status(self, text: str, color: str) -> None:
        self.status_text.set(text)
        self.status_color.set(color)
        self.status_dot.configure(foreground=color)

    def _set_controls(self, connecting: bool = False) -> None:
        if connecting:
            self.connect_button.configure(state=tk.DISABLED, text="正在连接…")
            self.toggle_button.configure(state=tk.DISABLED)
            return

        self.connect_button.configure(
            state=tk.DISABLED if self.running else tk.NORMAL,
            text="重新连接 MuMu" if self.connected else "连接 MuMu",
        )
        self.toggle_button.configure(
            state=tk.NORMAL if self.connected else tk.DISABLED,
            text="关闭自动推进主线" if self.running else "开启自动推进主线",
        )

    def _append_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_view.configure(state=tk.NORMAL)
        self.log_view.insert(tk.END, f"[{timestamp}] {message}\n")
        line_count = int(self.log_view.index("end-1c").split(".")[0])
        if line_count > 800:
            self.log_view.delete("1.0", "101.0")
        self.log_view.see(tk.END)
        self.log_view.configure(state=tk.DISABLED)

    def _refresh_template_status(self) -> TemplateMatcher:
        config, config_path = load_config(self.config_path)
        matcher = TemplateMatcher(config, config_path)
        support_selector = SupportSelector(config, config_path)
        self.config = config
        total = sum(1 for rule in config["rules"] if rule.get("enabled", True))
        ready = len(matcher.available_rules)
        self.template_text.set(
            f"识别模板：{ready}/{total}；合格助战候选："
            f"{support_selector.qualified_candidate_count}；"
            "缺少数据时会自动暂停"
        )
        return matcher

    def toggle_automation(self) -> None:
        if self.running:
            self.stop_automation()
        else:
            self.start_automation()

    def connect_mumu(self) -> None:
        if self.running or (self.worker and self.worker.is_alive()):
            return
        self._set_status("正在连接 MuMu…", "#d97706")
        self._set_controls(connecting=True)
        self._append_log("开始连接 MuMu 模拟器")

        def work() -> None:
            try:
                info = self.device.connect(force=True)
                screen = self.device.capture()
                package = self.device.foreground_package()
                height, width = screen.shape[:2]
                self.events.put(
                    (
                        "connected",
                        {
                            "info": info,
                            "package": package,
                            "size": (width, height),
                        },
                    )
                )
            except Exception as exc:  # 转交主线程显示，不在线程中操作 Tk。
                self.events.put(("connect_error", exc))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def _select_mumu_manager(self) -> bool:
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="选择 MuMuManager.exe",
            filetypes=(("MuMu 管理器", "MuMuManager.exe"), ("可执行文件", "*.exe")),
        )
        if not selected:
            return False
        try:
            self.device.set_manager_path(selected)
            config, config_path = load_config(self.config_path)
            config.setdefault("device", {})["manager_path"] = str(
                Path(selected).resolve()
            )
            save_config(config, config_path)
            self.config = config
        except (AdbError, ConfigError, OSError) as exc:
            self._set_status("MuMu 路径保存失败", "#dc2626")
            self._append_log(f"MuMu 路径无效：{exc}")
            return False
        self._append_log(f"已保存 MuMu 路径：{Path(selected).resolve()}")
        return True

    def start_automation(self) -> None:
        if not self.connected or self.running:
            return
        try:
            matcher = self._refresh_template_status()
        except (ConfigError, VisionError, OSError) as exc:
            self._append_log(f"无法加载配置：{exc}")
            self._set_status("配置加载失败", "#dc2626")
            return
        if not matcher.available_rules:
            self._append_log("没有任何已标定模板，不能启动")
            self._set_status("缺少识别模板", "#dc2626")
            return

        self.runner = BotRunner(
            self.device,
            matcher,
            self.config,
            self.config_path,
            dry_run=False,
            log=lambda message: self.events.put(("log", message)),
        )
        self.running = True
        self._set_status("自动推进运行中", "#2563eb")
        self._set_controls()
        self._append_log("已开启自动推进主线")

        def work() -> None:
            outcome: tuple[str, Any]
            try:
                assert self.runner is not None
                self.runner.run()
                outcome = ("automation_stopped", "自动推进已停止")
            except PauseRequested as exc:
                outcome = ("automation_paused", exc)
            except Exception as exc:
                outcome = ("automation_error", exc)
            self.events.put(outcome)

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def stop_automation(self) -> None:
        if not self.running or self.runner is None:
            return
        self._set_status("正在停止自动推进…", "#d97706")
        self.toggle_button.configure(state=tk.DISABLED, text="正在关闭…")
        self._append_log("正在停止；等待当前截图或 ADB 操作结束")
        self.runner.stop()

    def _drain_events(self) -> None:
        # Never drain an unbounded log backlog in one Tk callback.  Doing so
        # starves native move/resize messages and makes the window visibly
        # trail behind the mouse while automation is producing many logs.
        max_events_per_tick = 40
        processed = 0
        try:
            while processed < max_events_per_tick:
                event, payload = self.events.get_nowait()
                processed += 1
                if event == "log":
                    self._append_log(str(payload))
                elif event == "connected":
                    self.connected = True
                    info = payload["info"]
                    width, height = payload["size"]
                    package = payload["package"] or "未知"
                    self.device_text.set(
                        f"{info.name} · 实例 {info.vm_index} · ADB {info.serial} · "
                        f"{width}×{height} · 前台 {package}"
                    )
                    expected = self.config["device"].get("package")
                    if expected and package != expected:
                        self._set_status("已连接，但 FGO 不在前台", "#d97706")
                        self._append_log(
                            f"连接成功，但当前前台应用是 {package}；启动后会安全暂停"
                        )
                    else:
                        self._set_status("MuMu 已连接", "#16a34a")
                        self._append_log("MuMu 与 FGO 连接成功")
                    try:
                        self._refresh_template_status()
                    except Exception as exc:
                        self._append_log(f"模板状态读取失败：{exc}")
                    self._set_controls()
                elif event == "connect_error":
                    self.connected = False
                    missing_manager = (
                        isinstance(payload, AdbError)
                        and "没有找到 MuMuManager.exe" in str(payload)
                    )
                    if missing_manager and self._select_mumu_manager():
                        self._set_status("已选择 MuMu，正在重新连接", "#d97706")
                        self.device_text.set("已保存本机 MuMu 路径")
                        self._set_controls()
                        self.root.after(100, self.connect_mumu)
                    else:
                        self._set_status("MuMu 连接失败", "#dc2626")
                        self.device_text.set("请确认 MuMu 已启动并进入 Android 桌面")
                        self._append_log(f"连接失败：{payload}")
                        self._set_controls()
                elif event == "automation_stopped":
                    self.running = False
                    self.runner = None
                    self._set_status("自动推进已停止", "#16a34a")
                    self._append_log(str(payload))
                    self._set_controls()
                elif event == "automation_paused":
                    self.running = False
                    self.runner = None
                    self._set_status("已安全暂停，等待人工处理", "#d97706")
                    self._append_log(f"安全暂停：{payload.reason}")
                    if payload.snapshot:
                        self._append_log(f"现场截图：{payload.snapshot}")
                    self._set_controls()
                elif event == "automation_error":
                    self.running = False
                    self.runner = None
                    if isinstance(payload, AdbError):
                        self.connected = False
                    self._set_status("自动推进发生错误", "#dc2626")
                    self._append_log(f"运行错误：{payload}")
                    self._set_controls()
        except queue.Empty:
            pass
        # Continue a backlog soon, but yield to Tk/Windows between batches.
        delay_ms = 20 if not self.events.empty() else 100
        self.root.after(delay_ms, self._drain_events)

    def _on_close(self) -> None:
        if self.runner is not None:
            self.runner.stop()
        self.root.destroy()


def launch_gui(
    config: dict[str, Any],
    config_path: Path,
    device: MuMuDevice,
) -> None:
    if sys.platform == "win32":
        try:
            # Set before creating Tk's first native window.  This prevents
            # Windows from virtualizing mouse/window coordinates.
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    FgoControlPanel(root, config, config_path, device)
    root.mainloop()
