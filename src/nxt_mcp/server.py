"""Transport-independent MCP server factory for a locally connected NXT."""
from __future__ import annotations

import argparse
import atexit
import os
from pathlib import Path
from typing import Literal

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from .behaviors import BehaviorRunner
from .controller import NxtController
from .hardware import MotorPort, SensorPort, SensorType
from .nxt_python_adapter import NxtPythonHardware


class NxtTools:
    """Thin MCP adapter; all robot safety remains in ``NxtController``."""
    def __init__(self, controller: NxtController, behaviors: BehaviorRunner) -> None:
        self.controller, self.behaviors = controller, behaviors

    def nxt_info(self) -> dict:
        """Return identity, battery, and free storage for the connected NXT."""; return self.controller.info()
    def run_motor(self, port: MotorPort, power: int, regulated: bool = True) -> dict:
        """Run a motor continuously; it keeps moving until explicitly stopped."""; return self.controller.run_motor(port, power, regulated)
    def stop_motor(self, port: MotorPort, brake: bool = False) -> dict:
        """Stop one motor, optionally actively holding its position."""; return self.controller.stop_motor(port, brake)
    def move_motor_relative(self, port: MotorPort, power: int, degrees: int, brake: bool = True, timeout_seconds: float = 10.0) -> dict:
        """Rotate one motor by bounded relative encoder degrees, then stop."""; return self.controller.run_motor_for_ticks(port, power, degrees, brake, timeout_seconds)
    def motor_position(self, port: MotorPort) -> dict:
        """Read a motor's absolute and raw encoder positions in degrees."""; return self.controller.motor_position(port)
    def zero_motor_position(self, port: MotorPort) -> dict:
        """Stop a motor and reset its absolute encoder reference to zero."""; return self.controller.zero_motor_position(port)
    def move_motor_absolute(self, port: MotorPort, target_degrees: int, power: int = 20, brake: bool = True, timeout_seconds: float = 30.0) -> dict:
        """Move one motor to an absolute position relative to its last zero."""; return self.controller.move_motor_absolute(port, target_degrees, power, brake, timeout_seconds)
    def run_motors(self, ports: list[MotorPort], powers: list[int], regulated: bool = True) -> dict:
        """Start one to three motors together with signed continuous power."""; return self.controller.run_motors(ports, powers, regulated)
    def stop_motors(self, ports: list[MotorPort], brake: bool = False) -> dict:
        """Stop one to three motors together."""; return self.controller.stop_motors(ports, brake)
    def move_motors_relative(self, ports: list[MotorPort], powers: list[int], degrees: list[int], brake: bool = True, timeout_seconds: float = 30.0) -> dict:
        """Move several motors concurrently by independent bounded degrees."""; return self.controller.move_motors_relative(ports, powers, degrees, brake, timeout_seconds)
    def move_motors_absolute(self, ports: list[MotorPort], powers: list[int], target_degrees: list[int], brake: bool = True, timeout_seconds: float = 30.0) -> dict:
        """Move several motors concurrently to independent absolute positions."""; return self.controller.move_motors_absolute(ports, powers, target_degrees, brake, timeout_seconds)
    def run_motor_until_sensor(self, port: MotorPort, power: int, sensor_port: SensorPort, sensor_type: SensorType, condition: Literal["pressed", "released", "lt", "lte", "gt", "gte", "eq"], threshold: float | None = None, brake: bool = True, regulated: bool = True, max_ticks: int = 3600, timeout_seconds: float = 15.0) -> dict:
        """Run a motor until a sensor condition, timeout, or travel limit."""; return self.controller.run_motor_until_sensor(port, power, sensor_port, sensor_type, condition, threshold, brake=brake, regulated=regulated, max_ticks=max_ticks, timeout_seconds=timeout_seconds)
    def run_motors_until_sensor(self, ports: list[MotorPort], powers: list[int], sensor_port: SensorPort, sensor_type: SensorType, condition: Literal["pressed", "released", "lt", "lte", "gt", "gte", "eq"], threshold: float | None = None, brake: bool = True, regulated: bool = True, max_ticks: int = 3600, timeout_seconds: float = 20.0) -> dict:
        """Run a motor group until a sensor condition or safety limit."""; return self.controller.run_motors_until_sensor(ports, powers, sensor_port, sensor_type, condition, threshold, brake=brake, regulated=regulated, max_ticks=max_ticks, timeout_seconds=timeout_seconds)
    def read_sensor(self, port: SensorPort, sensor_type: SensorType) -> dict:
        """Configure and read one sensor port."""; return self.controller.read_sensor(port, sensor_type)
    def query_all_state(self, format: Literal["text", "json"] = "text") -> str | dict:
        """Query the brick and all motor and sensor port states."""; return self.controller.state(text=format == "text")
    def emergency_stop(self) -> dict:
        """Immediately coast all three output ports."""; return self.controller.emergency_stop()
    def play_tone(self, frequency_hz: int = 440, duration_ms: int = 500) -> dict:
        """Play a tone on the NXT brick."""; return self.controller.play_tone(frequency_hz, duration_ms)
    def validate_behavior(self, source: str) -> dict:
        """Validate a restricted PC-side behavior without saving or running it."""; return self.behaviors.validate(source)
    def submit_behavior(self, name: str, source: str) -> dict:
        """Validate and save a trusted PC-side behavior."""; return self.behaviors.submit(name, source)
    def list_behaviors(self) -> dict:
        """List saved PC-side Python behaviors."""; return self.behaviors.list()
    def get_behavior(self, name: str) -> dict:
        """Return the source of a saved behavior."""; return self.behaviors.source(name)
    def run_behavior(self, name: str, timeout_seconds: float = 120.0) -> dict:
        """Run a saved behavior through the monitored robot interface."""; return self.behaviors.run(name, timeout_seconds)
    def cycle_motor_on_touch(self, port: MotorPort, touch_port: SensorPort, forward_power: int = 20, cycles: int = 5, max_ticks_per_phase: int = 3600, timeout_seconds_per_phase: float = 20.0, beep_frequency_hz: int = 440, beep_duration_ms: int = 500) -> dict:
        """Cycle a motor between touch press/release phases, then beep on success."""; return self.controller.cycle_motor_on_touch(port, touch_port, forward_power, cycles, max_ticks_per_phase=max_ticks_per_phase, timeout_seconds_per_phase=timeout_seconds_per_phase, beep_frequency_hz=beep_frequency_hz, beep_duration_ms=beep_duration_ms)
    def start_program(self, name: str) -> dict:
        """Start an .rxe program already stored on the NXT."""; return self.controller.start_program(name)
    def stop_program(self) -> dict:
        """Stop the currently running .rxe program."""; return self.controller.stop_program()
    def current_program(self) -> dict:
        """Report the currently running .rxe program, if any."""; return self.controller.current_program()


READ_ONLY = {"nxt_info", "motor_position", "read_sensor", "query_all_state", "validate_behavior", "list_behaviors", "get_behavior", "current_program"}
IDEMPOTENT = {"stop_motor", "stop_motors", "emergency_stop", "zero_motor_position", "validate_behavior"}


def create_server(*, controller: NxtController | None = None, behavior_dir: Path | None = None) -> MCPServer:
    """Create an isolated server instance usable by STDIO, HTTP, and tests."""
    controller = controller or NxtController(NxtPythonHardware())
    behavior_dir = behavior_dir or Path(os.getenv("NXT_BEHAVIOR_DIR", Path.cwd() / "behaviors"))
    tools = NxtTools(controller, BehaviorRunner(behavior_dir, controller))
    server = MCPServer("lego-nxt", version="0.1.0", instructions="Control one original LEGO Mindstorms NXT over USB. Prefer bounded motion tools. Use emergency_stop if motion is unexpected. Do not mix direct motor control with a running .rxe program.")
    for name in dir(tools):
        if name.startswith("_"):
            continue
        handler = getattr(tools, name)
        if callable(handler):
            server.tool(name=name, annotations=ToolAnnotations(readOnlyHint=name in READ_ONLY, destructiveHint=False, idempotentHint=name in IDEMPOTENT, openWorldHint=False))(handler)
    atexit.register(controller.close)
    return server


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LEGO Mindstorms NXT MCP server")
    parser.add_argument("--transport", choices=("stdio", "streamable-http"), default=os.getenv("NXT_MCP_TRANSPORT", "stdio"))
    parser.add_argument("--host", default=os.getenv("NXT_MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("NXT_MCP_PORT", "8000")))
    parser.add_argument("--path", default=os.getenv("NXT_MCP_PATH", "/mcp"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.transport == "streamable-http" and args.host not in {"127.0.0.1", "localhost", "::1"} and os.getenv("NXT_MCP_ALLOW_REMOTE") != "true":
        raise SystemExit("Refusing non-loopback HTTP. Set NXT_MCP_ALLOW_REMOTE=true only behind HTTPS authentication.")
    server = create_server()
    if args.transport == "stdio":
        server.run("stdio")
    else:
        server.run("streamable-http", host=args.host, port=args.port, streamable_http_path=args.path)


if __name__ == "__main__":
    main()
