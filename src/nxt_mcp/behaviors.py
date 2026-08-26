"""Validated, locally stored Python behaviors composed from safe robot primitives."""

from __future__ import annotations

import ast
import json
import re
import sys
import threading
import time
from pathlib import Path
from types import FrameType
from typing import Any

from .controller import NxtController

_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_MAX_SOURCE_BYTES = 64 * 1024
_SAFE_BUILTINS: dict[str, Any] = {
    "abs": abs,
    "bool": bool,
    "enumerate": enumerate,
    "float": float,
    "int": int,
    "len": len,
    "max": max,
    "min": min,
    "range": range,
    "round": round,
    "str": str,
    "sum": sum,
}
_ROBOT_METHODS = {
    "configure_sensor",
    "read_sensor",
    "motor_until",
    "motor_for_ticks",
    "motor_position",
    "zero_motor_position",
    "motor_to",
    "run_motors",
    "stop_motors",
    "motors_relative",
    "motors_absolute",
    "motors_until",
    "run_motor",
    "stop_motor",
    "state",
    "play_tone",
    "sleep",
}
_FORBIDDEN_NODES = (
    ast.AsyncFunctionDef,
    ast.Await,
    ast.ClassDef,
    ast.Delete,
    ast.Global,
    ast.Import,
    ast.ImportFrom,
    ast.Lambda,
    ast.Nonlocal,
    ast.Raise,
    ast.Try,
    ast.With,
    ast.Yield,
    ast.YieldFrom,
)


class BehaviorValidationError(ValueError):
    pass


class BehaviorTimeoutError(TimeoutError):
    pass


class _BehaviorValidator(ast.NodeVisitor):
    def __init__(self) -> None:
        self.functions: set[str] = set()
        self.errors: list[str] = []

    def validate(self, tree: ast.Module) -> None:
        self.functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
        run = next((node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "run"), None)
        if run is None:
            self.errors.append("script must define run(robot)")
        elif (
            len(run.args.args) != 1
            or run.args.args[0].arg != "robot"
            or run.args.vararg
            or run.args.kwarg
            or run.decorator_list
        ):
            self.errors.append("entry point must be exactly def run(robot): with no decorator")
        self.visit(tree)

    def generic_visit(self, node: ast.AST) -> None:
        if isinstance(node, _FORBIDDEN_NODES):
            self.errors.append(f"{type(node).__name__} is not allowed (line {getattr(node, 'lineno', '?')})")
            return
        super().generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if (
            not isinstance(node.value, ast.Name)
            or node.value.id != "robot"
            or node.attr not in _ROBOT_METHODS
        ):
            self.errors.append(
                f"only documented robot methods may be accessed (line {getattr(node, 'lineno', '?')})"
            )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        valid = False
        if isinstance(node.func, ast.Name):
            valid = node.func.id in _SAFE_BUILTINS or node.func.id in self.functions
        elif isinstance(node.func, ast.Attribute):
            valid = (
                isinstance(node.func.value, ast.Name)
                and node.func.value.id == "robot"
                and node.func.attr in _ROBOT_METHODS
            )
        if not valid:
            self.errors.append(f"call is not allowed (line {getattr(node, 'lineno', '?')})")
        self.generic_visit(node)


def validate_behavior_source(source: str) -> dict[str, Any]:
    encoded = source.encode("utf-8")
    if len(encoded) > _MAX_SOURCE_BYTES:
        raise BehaviorValidationError(f"script exceeds {_MAX_SOURCE_BYTES} bytes")
    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError as exc:
        raise BehaviorValidationError(f"syntax error on line {exc.lineno}: {exc.msg}") from exc
    validator = _BehaviorValidator()
    validator.validate(tree)
    if validator.errors:
        raise BehaviorValidationError("; ".join(dict.fromkeys(validator.errors)))
    return {
        "valid": True,
        "entry_point": "run(robot)",
        "source_bytes": len(encoded),
        "robot_methods": sorted(_ROBOT_METHODS),
    }


class ScriptRobot:
    """The only brick interface visible to a behavior script."""

    def __init__(self, controller: NxtController) -> None:
        self._controller = controller
        self.events: list[dict[str, Any]] = []

    def _record(self, operation: str, result: Any) -> Any:
        self.events.append({"operation": operation, "result": result})
        return result

    def configure_sensor(self, port: int, sensor_type: str) -> dict[str, Any]:
        return self._record("configure_sensor", self._controller.read_sensor(port, sensor_type))

    def read_sensor(self, port: int, sensor_type: str) -> dict[str, Any]:
        return self._record("read_sensor", self._controller.read_sensor(port, sensor_type))

    def motor_until(
        self,
        port: str,
        power: int,
        sensor_port: int,
        condition: str,
        sensor_type: str = "touch",
        threshold: float | None = None,
        max_ticks: int = 3600,
        timeout_seconds: float = 20.0,
    ) -> dict[str, Any]:
        result = self._controller.run_motor_until_sensor(
            port,
            power,
            sensor_port,
            sensor_type,
            condition,
            threshold,
            max_ticks=max_ticks,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=0.02,
        )
        if not result["ok"]:
            raise RuntimeError(f"motor_until stopped: {result['reason']}")
        return self._record("motor_until", result)

    def motor_for_ticks(
        self, port: str, power: int, ticks: int, brake: bool = True, timeout_seconds: float = 10.0
    ) -> dict[str, Any]:
        return self._record(
            "motor_for_ticks",
            self._controller.run_motor_for_ticks(port, power, ticks, brake, timeout_seconds),
        )

    def motor_position(self, port: str) -> dict[str, Any]:
        return self._record("motor_position", self._controller.motor_position(port))

    def zero_motor_position(self, port: str) -> dict[str, Any]:
        return self._record(
            "zero_motor_position", self._controller.zero_motor_position(port)
        )

    def motor_to(
        self,
        port: str,
        target_degrees: int,
        power: int = 20,
        brake: bool = True,
        timeout_seconds: float = 30.0,
    ) -> dict[str, Any]:
        return self._record(
            "motor_to",
            self._controller.move_motor_absolute(
                port, target_degrees, power, brake, timeout_seconds
            ),
        )

    def run_motors(
        self, ports: list[str], powers: list[int], regulated: bool = True
    ) -> dict[str, Any]:
        return self._record(
            "run_motors", self._controller.run_motors(ports, powers, regulated)
        )

    def stop_motors(self, ports: list[str], brake: bool = False) -> dict[str, Any]:
        return self._record(
            "stop_motors", self._controller.stop_motors(ports, brake)
        )

    def motors_relative(
        self,
        ports: list[str],
        powers: list[int],
        degrees: list[int],
        brake: bool = True,
        timeout_seconds: float = 30.0,
    ) -> dict[str, Any]:
        return self._record(
            "motors_relative",
            self._controller.move_motors_relative(
                ports, powers, degrees, brake, timeout_seconds
            ),
        )

    def motors_absolute(
        self,
        ports: list[str],
        powers: list[int],
        target_degrees: list[int],
        brake: bool = True,
        timeout_seconds: float = 30.0,
    ) -> dict[str, Any]:
        return self._record(
            "motors_absolute",
            self._controller.move_motors_absolute(
                ports, powers, target_degrees, brake, timeout_seconds
            ),
        )

    def motors_until(
        self,
        ports: list[str],
        powers: list[int],
        sensor_port: int,
        condition: str,
        sensor_type: str = "touch",
        threshold: float | None = None,
        max_ticks: int = 3600,
        timeout_seconds: float = 20.0,
    ) -> dict[str, Any]:
        result = self._controller.run_motors_until_sensor(
            ports,
            powers,
            sensor_port,
            sensor_type,
            condition,
            threshold,
            max_ticks=max_ticks,
            timeout_seconds=timeout_seconds,
        )
        if not result["ok"]:
            raise RuntimeError(f"motors_until stopped: {result['reason']}")
        return self._record("motors_until", result)

    def run_motor(self, port: str, power: int, regulated: bool = True) -> dict[str, Any]:
        return self._record("run_motor", self._controller.run_motor(port, power, regulated))

    def stop_motor(self, port: str, brake: bool = False) -> dict[str, Any]:
        return self._record("stop_motor", self._controller.stop_motor(port, brake))

    def state(self, format: str = "text") -> str | dict[str, Any]:
        if format not in ("text", "json"):
            raise ValueError("format must be 'text' or 'json'")
        return self._record("state", self._controller.state(text=format == "text"))

    def play_tone(self, frequency_hz: int = 440, duration_ms: int = 500) -> dict[str, Any]:
        return self._record("play_tone", self._controller.play_tone(frequency_hz, duration_ms))

    def sleep(self, seconds: float) -> dict[str, Any]:
        if not 0 <= seconds <= 30:
            raise ValueError("sleep seconds must be between 0 and 30")
        time.sleep(seconds)
        return self._record("sleep", {"seconds": seconds})


class BehaviorRunner:
    def __init__(self, directory: Path, controller: NxtController) -> None:
        self._directory = directory.resolve()
        self._controller = controller
        self._run_lock = threading.Lock()

    def validate(self, source: str) -> dict[str, Any]:
        return validate_behavior_source(source)

    def submit(self, name: str, source: str) -> dict[str, Any]:
        path = self._path(name)
        validation = self.validate(source)
        self._directory.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8", newline="\n")
        return {"ok": True, "name": name, **validation}

    def list(self) -> dict[str, Any]:
        if not self._directory.exists():
            return {"behaviors": []}
        return {"behaviors": sorted(path.stem for path in self._directory.glob("*.py"))}

    def source(self, name: str) -> dict[str, Any]:
        return {"name": name, "source": self._path(name).read_text(encoding="utf-8")}

    def run(self, name: str, timeout_seconds: float = 120.0) -> dict[str, Any]:
        if not 1 <= timeout_seconds <= 300:
            raise ValueError("timeout_seconds must be between 1 and 300")
        if not self._run_lock.acquire(blocking=False):
            raise RuntimeError("another behavior is already running")

        robot = ScriptRobot(self._controller)
        started = time.monotonic()
        entrypoint_started = False
        try:
            source = self._path(name).read_text(encoding="utf-8")
            self.validate(source)
            namespace: dict[str, Any] = {"__builtins__": _SAFE_BUILTINS}
            deadline = started + timeout_seconds

            def trace(_frame: FrameType, event: str, _arg: Any) -> Any:
                if event == "line" and time.monotonic() >= deadline:
                    raise BehaviorTimeoutError(f"behavior exceeded {timeout_seconds:g} seconds")
                return trace

            previous_trace = sys.gettrace()
            try:
                sys.settrace(trace)
                exec(compile(source, f"behavior:{name}", "exec"), namespace, namespace)
                entrypoint_started = True
                result = namespace["run"](robot)
            finally:
                sys.settrace(previous_trace)
            return {
                "ok": True,
                "name": name,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "result": self._json_value(result),
                "events": robot.events,
            }
        finally:
            if entrypoint_started:
                self._controller.emergency_stop()
            self._run_lock.release()

    def _path(self, name: str) -> Path:
        if not _NAME.fullmatch(name):
            raise ValueError("name must start with a letter and contain only letters, digits, _ or -")
        return self._directory / f"{name}.py"

    @staticmethod
    def _json_value(value: Any) -> Any:
        try:
            json.dumps(value)
            return value
        except (TypeError, ValueError):
            return repr(value)
