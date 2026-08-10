from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .config import resolve_from_config


class VisionError(RuntimeError):
    pass


@dataclass(frozen=True)
class MatchResult:
    rule: dict[str, Any]
    score: float
    x: int
    y: int
    width: int
    height: int

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.width // 2, self.y + self.height // 2


def read_image(path: Path) -> np.ndarray:
    try:
        encoded = np.fromfile(path, dtype=np.uint8)
    except OSError as exc:
        raise VisionError(f"无法读取图片：{path}") from exc
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None:
        raise VisionError(f"不是有效图片：{path}")
    return image


def write_image(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower() or ".png"
    ok, encoded = cv2.imencode(suffix, image)
    if not ok:
        raise VisionError(f"图片编码失败：{path}")
    try:
        encoded.tofile(path)
    except OSError as exc:
        raise VisionError(f"无法写入图片：{path}") from exc


class TemplateMatcher:
    def __init__(
        self,
        config: dict[str, Any],
        config_path: Path,
    ) -> None:
        self.config = config
        self.config_path = config_path
        self.base_width = int(config["screen"]["base_width"])
        self.base_height = int(config["screen"]["base_height"])
        self._templates: dict[str, np.ndarray] = {}
        self._missing: set[str] = set()

        for rule in config["rules"]:
            if rule.get("enabled", True):
                path = resolve_from_config(config_path, rule["template"])
                if path.is_file():
                    self._templates[rule["name"]] = read_image(path)
                else:
                    self._missing.add(rule["name"])

    @property
    def available_rules(self) -> list[str]:
        return list(self._templates)

    @property
    def missing_rules(self) -> list[str]:
        return sorted(self._missing)

    def _scaled_template(
        self,
        template: np.ndarray,
        screen_width: int,
        screen_height: int,
    ) -> np.ndarray:
        scale_x = screen_width / self.base_width
        scale_y = screen_height / self.base_height
        if abs(scale_x - 1.0) < 0.01 and abs(scale_y - 1.0) < 0.01:
            return template
        width = max(2, round(template.shape[1] * scale_x))
        height = max(2, round(template.shape[0] * scale_y))
        interpolation = cv2.INTER_AREA if scale_x < 1 else cv2.INTER_CUBIC
        return cv2.resize(template, (width, height), interpolation=interpolation)

    def match_rule(
        self,
        screen: np.ndarray,
        rule: dict[str, Any],
    ) -> MatchResult | None:
        template = self._templates.get(rule["name"])
        if template is None:
            return None

        template_crop = rule.get("template_crop")
        if template_crop is not None:
            if not isinstance(template_crop, list) or len(template_crop) != 4:
                raise VisionError(
                    f"规则 {rule['name']} 的 template_crop 必须包含4个数值"
                )
            crop_x1, crop_y1, crop_x2, crop_y2 = (
                int(value) for value in template_crop
            )
            crop_x1 = max(0, min(template.shape[1], crop_x1))
            crop_x2 = max(0, min(template.shape[1], crop_x2))
            crop_y1 = max(0, min(template.shape[0], crop_y1))
            crop_y2 = max(0, min(template.shape[0], crop_y2))
            if crop_x2 <= crop_x1 or crop_y2 <= crop_y1:
                raise VisionError(
                    f"规则 {rule['name']} 的 template_crop 没有有效区域"
                )
            template = template[crop_y1:crop_y2, crop_x1:crop_x2]

        screen_height, screen_width = screen.shape[:2]
        base_scaled = self._scaled_template(
            template,
            screen_width,
            screen_height,
        )

        search_screen = screen
        offset_x = 0
        offset_y = 0
        search_roi = rule.get("search_roi")
        if search_roi:
            if len(search_roi) != 4:
                raise VisionError(
                    f"规则 {rule['name']} 的 search_roi 必须包含4个数值"
                )
            offset_x = max(
                0,
                round(float(search_roi[0]) * screen_width / self.base_width),
            )
            offset_y = max(
                0,
                round(float(search_roi[1]) * screen_height / self.base_height),
            )
            end_x = min(
                screen_width,
                round(float(search_roi[2]) * screen_width / self.base_width),
            )
            end_y = min(
                screen_height,
                round(float(search_roi[3]) * screen_height / self.base_height),
            )
            search_screen = screen[offset_y:end_y, offset_x:end_x]
        if search_screen.size == 0:
            return None

        match_mode = str(rule.get("match_mode", "gray"))
        lower = np.array(rule.get("hsv_lower", [8, 90, 90]), dtype=np.uint8)
        upper = np.array(
            rule.get("hsv_upper", [40, 255, 255]),
            dtype=np.uint8,
        )
        if match_mode in {"yellow_mask", "hsv_mask"}:
            screen_source = cv2.inRange(
                cv2.cvtColor(search_screen, cv2.COLOR_BGR2HSV),
                lower,
                upper,
            )
        elif match_mode == "edge":
            screen_source = cv2.Canny(
                cv2.cvtColor(search_screen, cv2.COLOR_BGR2GRAY),
                int(rule.get("canny_lower", 80)),
                int(rule.get("canny_upper", 180)),
            )
        elif match_mode == "gray":
            screen_source = cv2.cvtColor(search_screen, cv2.COLOR_BGR2GRAY)
        else:
            raise VisionError(f"未知模板匹配模式：{match_mode}")

        raw_scales = rule.get("template_scales", [1.0])
        if not isinstance(raw_scales, list) or not raw_scales:
            raise VisionError(
                f"规则 {rule['name']} 的 template_scales 必须是非空列表"
            )
        best: tuple[float, tuple[int, int], int, int] | None = None
        for raw_scale in raw_scales:
            template_scale = float(raw_scale)
            if template_scale <= 0:
                raise VisionError(
                    f"规则 {rule['name']} 的模板缩放必须大于0"
                )
            if abs(template_scale - 1.0) < 0.001:
                scaled = base_scaled
            else:
                width = max(2, round(base_scaled.shape[1] * template_scale))
                height = max(
                    2,
                    round(base_scaled.shape[0] * template_scale),
                )
                interpolation = (
                    cv2.INTER_AREA
                    if template_scale < 1.0
                    else cv2.INTER_CUBIC
                )
                scaled = cv2.resize(
                    base_scaled,
                    (width, height),
                    interpolation=interpolation,
                )
            height, width = scaled.shape[:2]
            if (
                search_screen.shape[0] < height
                or search_screen.shape[1] < width
            ):
                continue
            if match_mode in {"yellow_mask", "hsv_mask"}:
                template_source = cv2.inRange(
                    cv2.cvtColor(scaled, cv2.COLOR_BGR2HSV),
                    lower,
                    upper,
                )
            elif match_mode == "edge":
                template_source = cv2.Canny(
                    cv2.cvtColor(scaled, cv2.COLOR_BGR2GRAY),
                    int(rule.get("canny_lower", 80)),
                    int(rule.get("canny_upper", 180)),
                )
            else:
                template_source = cv2.cvtColor(
                    scaled,
                    cv2.COLOR_BGR2GRAY,
                )
            result = cv2.matchTemplate(
                screen_source,
                template_source,
                cv2.TM_CCOEFF_NORMED,
            )
            _, score, _, location = cv2.minMaxLoc(result)
            candidate = (float(score), location, width, height)
            if best is None or candidate[0] > best[0]:
                best = candidate
        if best is None:
            return None
        score, location, width, height = best
        threshold = float(rule.get("threshold", 0.88))
        if score < threshold:
            return None
        return MatchResult(
            rule=rule,
            score=float(score),
            x=int(location[0]) + offset_x,
            y=int(location[1]) + offset_y,
            width=width,
            height=height,
        )

    def find_first(self, screen: np.ndarray) -> MatchResult | None:
        # 配置文件中的顺序就是优先级；暂停规则应放在最前面。
        for rule in self.config["rules"]:
            if (
                not rule.get("enabled", True)
                or rule.get("detect_only", False)
            ):
                continue
            match = self.match_rule(screen, rule)
            if match is not None:
                return match
        return None

    def scores(self, screen: np.ndarray) -> list[tuple[str, float]]:
        output: list[tuple[str, float]] = []
        for rule in self.config["rules"]:
            template = self._templates.get(rule["name"])
            if template is None:
                continue
            relaxed = dict(rule)
            relaxed["threshold"] = -1
            match = self.match_rule(screen, relaxed)
            if match is not None:
                output.append((rule["name"], match.score))
        return sorted(output, key=lambda item: item[1], reverse=True)


def annotate_match(screen: np.ndarray, match: MatchResult, text: str = "") -> np.ndarray:
    output = screen.copy()
    start = (match.x, match.y)
    end = (match.x + match.width, match.y + match.height)
    cv2.rectangle(output, start, end, (0, 255, 0), 3)
    label = text or f"{match.rule['name']} {match.score:.3f}"
    cv2.putText(
        output,
        label,
        (match.x, max(24, match.y - 10)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (0, 255, 0),
        2,
        cv2.LINE_AA,
    )
    return output
