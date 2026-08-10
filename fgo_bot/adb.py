from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np


class AdbError(RuntimeError):
    pass


@dataclass(frozen=True)
class DeviceInfo:
    vm_index: int
    name: str
    serial: str
    android_version: str
    player_state: str


def _no_window_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def find_mumu_manager(configured: str | None = None) -> Path:
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(os.path.expandvars(configured)).expanduser())

    env_path = os.environ.get("MUMU_MANAGER")
    if env_path:
        candidates.append(Path(os.path.expandvars(env_path)).expanduser())

    for drive in ("C:", "D:", "E:", "F:", "G:"):
        candidates.extend(
            [
                Path(drive) / "MuMu" / "nx_main" / "MuMuManager.exe",
                Path(drive)
                / "Program Files"
                / "Netease"
                / "MuMuPlayerGlobal-12.0"
                / "shell"
                / "MuMuManager.exe",
                Path(drive)
                / "Program Files"
                / "Netease"
                / "MuMu Player 12"
                / "shell"
                / "MuMuManager.exe",
            ]
        )

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    rendered = "\n".join(f"  - {item}" for item in candidates)
    raise AdbError(
        "没有找到 MuMuManager.exe。请在配置的 device.manager_path 填入实际路径，"
        f"或设置 MUMU_MANAGER 环境变量。\n已检查：\n{rendered}"
    )


class MuMuDevice:
    def __init__(self, manager_path: str | None, vm_index: int = 0) -> None:
        # Resolve MuMu lazily so the control panel can still open on a new
        # computer where MuMu is installed in an uncommon directory.  The GUI
        # can then ask the user to select MuMuManager.exe when connecting.
        self.configured_manager_path = manager_path
        self.manager_path: Path | None = None
        self.adb_path: Path | None = None
        self.vm_index = int(vm_index)
        self._info: DeviceInfo | None = None
        self._connected_at = 0.0

    def _ensure_manager(self) -> tuple[Path, Path]:
        if self.manager_path is None:
            manager_path = find_mumu_manager(self.configured_manager_path)
            adb_path = manager_path.with_name("adb.exe")
            if not adb_path.is_file():
                raise AdbError(f"MuMu 自带 adb.exe 不存在：{adb_path}")
            self.manager_path = manager_path
            self.adb_path = adb_path
        assert self.adb_path is not None
        return self.manager_path, self.adb_path

    def set_manager_path(self, manager_path: str | Path) -> None:
        candidate = Path(manager_path).expanduser().resolve()
        if not candidate.is_file() or candidate.name.lower() != "mumumanager.exe":
            raise AdbError(f"选择的文件不是 MuMuManager.exe：{candidate}")
        adb_path = candidate.with_name("adb.exe")
        if not adb_path.is_file():
            raise AdbError(f"MuMu 自带 adb.exe 不存在：{adb_path}")
        self.configured_manager_path = str(candidate)
        self.manager_path = candidate
        self.adb_path = adb_path
        self._info = None
        self._connected_at = 0.0

    def _run(
        self,
        args: list[str],
        *,
        timeout: float = 15,
        binary: bool = False,
        check: bool = True,
    ) -> subprocess.CompletedProcess[Any]:
        try:
            result = subprocess.run(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=not binary,
                encoding=None if binary else "utf-8",
                errors=None if binary else "replace",
                timeout=timeout,
                check=False,
                creationflags=_no_window_flags(),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AdbError(f"命令执行失败：{args[0]}：{exc}") from exc

        if check and result.returncode != 0:
            stderr = (
                result.stderr.decode("utf-8", errors="replace")
                if binary
                else result.stderr
            )
            stdout = (
                result.stdout.decode("utf-8", errors="replace")
                if binary
                else result.stdout
            )
            detail = (stderr or stdout or "").strip()
            raise AdbError(f"命令返回 {result.returncode}：{detail}")
        return result

    def info(self, refresh: bool = False) -> DeviceInfo:
        if self._info is not None and not refresh:
            return self._info
        manager_path, _ = self._ensure_manager()
        result = self._run(
            [
                str(manager_path),
                "info",
                "--vmindex",
                str(self.vm_index),
            ]
        )
        output = result.stdout.strip()
        first_brace = output.find("{")
        if first_brace < 0:
            raise AdbError(f"无法解析 MuMu 实例信息：{output}")
        try:
            payload = json.loads(output[first_brace:])
            raw = (
                payload
                if "adb_port" in payload
                else payload[str(self.vm_index)]
            )
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise AdbError(f"无法解析 MuMu 实例信息：{output}") from exc

        host = raw.get("adb_host_ip", "127.0.0.1")
        port = raw.get("adb_port")
        if not port:
            raise AdbError("MuMu 没有返回 ADB 端口；请确认模拟器已经完全启动")
        self._info = DeviceInfo(
            vm_index=self.vm_index,
            name=str(raw.get("name", f"MuMu {self.vm_index}")),
            serial=f"{host}:{port}",
            android_version=str(raw.get("android_version", "")),
            player_state=str(raw.get("player_state", "")),
        )
        return self._info

    def connect(self, force: bool = False) -> DeviceInfo:
        if (
            not force
            and self._info is not None
            and time.monotonic() - self._connected_at < 30
        ):
            return self._info
        manager_path, _ = self._ensure_manager()
        info = self.info(refresh=True)
        if info.player_state not in {"start_finished", "running"}:
            raise AdbError(f"MuMu 尚未就绪，当前状态：{info.player_state}")
        self._run(
            [
                str(manager_path),
                "adb",
                "--vmindex",
                str(self.vm_index),
                "--cmd",
                "connect",
            ],
            timeout=20,
        )
        self._connected_at = time.monotonic()
        return info

    def _adb(self, tail: list[str], *, timeout: float = 15, binary: bool = False):
        _, adb_path = self._ensure_manager()
        info = self.connect()
        args = [str(adb_path), "-s", info.serial, *tail]
        try:
            return self._run(args, timeout=timeout, binary=binary)
        except AdbError:
            # MuMu/Android SDK 的 ADB 服务偶尔会互相重启；重新连接一次即可。
            info = self.connect(force=True)
            _, adb_path = self._ensure_manager()
            args = [str(adb_path), "-s", info.serial, *tail]
            return self._run(args, timeout=timeout, binary=binary)

    def capture(self) -> np.ndarray:
        result = self._adb(
            ["exec-out", "screencap", "-p"],
            timeout=20,
            binary=True,
        )
        data = np.frombuffer(result.stdout, dtype=np.uint8)
        image = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if image is None or image.size == 0:
            raise AdbError("ADB 截图解码失败")
        return image

    def tap(self, x: int, y: int) -> None:
        self._adb(["shell", "input", "tap", str(int(x)), str(int(y))])

    def swipe(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration_ms: int = 600,
    ) -> None:
        self._adb(
            [
                "shell",
                "input",
                "swipe",
                str(int(start_x)),
                str(int(start_y)),
                str(int(end_x)),
                str(int(end_y)),
                str(int(duration_ms)),
            ]
        )

    def long_press(
        self,
        x: int,
        y: int,
        duration_ms: int = 1000,
    ) -> None:
        """Hold one screen coordinate through Android's input command."""
        self.swipe(x, y, x, y, duration_ms)

    def keyevent(self, keycode: int) -> None:
        self._adb(["shell", "input", "keyevent", str(int(keycode))])

    def foreground_package(self) -> str | None:
        result = self._adb(["shell", "dumpsys", "window"], timeout=20)
        match = re.search(r"mCurrentFocus=.*?\s([\w.]+)/", result.stdout)
        return match.group(1) if match else None
