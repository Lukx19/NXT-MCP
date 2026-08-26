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
    def motor_state(self, port: MotorPort) -> dict:
        """Read detailed observable state for one motor."""; return self.controller.motor_state(port)
    def drive_sync(self, left_port: MotorPort, right_port: MotorPort, power: int, turn_ratio: int = 0) -> dict:
        """Start a firmware-synchronised two-motor drive pair."""; return self.controller.drive_sync(left_port, right_port, power, turn_ratio)
    def wait_motors(self, ports: list[MotorPort], timeout_seconds: float = 10.0, brake: bool = True) -> dict:
        """Wait for motor ports to stop; stop them safely when the deadline expires."""; return self.controller.wait_motors(ports, timeout_seconds, brake)
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
    def read_sensor_raw(self, port: SensorPort, sensor_type: SensorType | None = None) -> dict:
        """Return raw, normalized, scaled, and firmware sensor values."""; return self.controller.read_sensor_raw(port, sensor_type)
    def zero_sensor_reference(self, port: SensorPort, sensor_type: Literal["light", "color", "ultrasonic"]) -> dict:
        """Capture the current light, color-intensity, or ultrasonic value as relative zero."""; return self.controller.zero_sensor_reference(port, sensor_type)
    def read_sensor_relative(self, port: SensorPort, sensor_type: Literal["light", "color", "ultrasonic"]) -> dict:
        """Read change from a previously captured sensor zero reference."""; return self.controller.read_sensor_relative(port, sensor_type)
    def wait_sensor(self, port: SensorPort, sensor_type: SensorType, condition: Literal["pressed", "released", "lt", "lte", "gt", "gte", "eq"], threshold: float | None = None, debounce_ms: int = 0, timeout_seconds: float = 20.0) -> dict:
        """Wait for a debounced sensor condition without moving a motor."""; return self.controller.wait_sensor(port, sensor_type, condition, threshold, debounce_ms, timeout_seconds)
    def sensor_stream(self, port: SensorPort, sensor_type: SensorType, sample_interval_ms: int = 100, duration_seconds: float = 5.0, max_samples: int = 100) -> dict:
        """Collect a bounded series of sensor readings."""; return self.controller.sensor_stream(port, sensor_type, sample_interval_ms, duration_seconds, max_samples)
    def query_all_state(self, format: Literal["text", "json"] = "text") -> str | dict:
        """Query the brick and all motor and sensor port states."""; return self.controller.state(text=format == "text")
    def emergency_stop(self) -> dict:
        """Immediately coast all three output ports."""; return self.controller.emergency_stop()
    def play_tone(self, frequency_hz: int = 440, duration_ms: int = 500) -> dict:
        """Play a tone on the NXT brick."""; return self.controller.play_tone(frequency_hz, duration_ms)
    def play_sound_file(self, name: str, loop: bool = False) -> dict:
        """Play an existing .rso sound file stored on the NXT."""; return self.controller.play_sound_file(name, loop)
    def stop_sound(self) -> dict:
        """Stop active brick sound playback."""; return self.controller.stop_sound()
    def list_files(self, pattern: str = "*.*") -> dict:
        """List files stored in NXT user flash."""; return self.controller.list_files(pattern)
    def read_file(self, name: str, max_bytes: int = 65536) -> dict:
        """Read a bounded UTF-8-compatible file from NXT user flash."""; return self.controller.read_file(name, max_bytes)
    def write_file(self, name: str, content: str, overwrite: bool = False) -> dict:
        """Write bounded data or sound files to NXT user flash."""; return self.controller.write_file(name, content, overwrite)
    def delete_file(self, name: str) -> dict:
        """Delete one NXT user-flash file."""; return self.controller.delete_file(name)
    def mailbox_send(self, inbox: int, data: str) -> dict:
        """Send a bounded UTF-8 NXT mailbox message."""; return self.controller.mailbox_send(inbox, data)
    def mailbox_receive(self, inbox: int, remove: bool = True) -> dict:
        """Receive one NXT mailbox message."""; return self.controller.mailbox_receive(inbox, remove)
    def i2c_transaction(self, port: SensorPort, write_bytes: list[int], read_length: int, timeout_seconds: float = 1.0) -> dict:
        """Perform one bounded opt-in NXT low-speed/I2C transaction."""; return self.controller.i2c_transaction(port, write_bytes, read_length, timeout_seconds)
    def log_start(self, channels: list[str], interval_ms: int = 100, duration_seconds: float = 10.0) -> dict:
        """Start a bounded host-side telemetry log job."""; return self.controller.log_start(channels, interval_ms, duration_seconds)
    def log_status(self, job_id: str) -> dict:
        """Read the state and sample count of a telemetry job."""; return self.controller.log_status(job_id)
    def log_stop(self, job_id: str) -> dict:
        """Request a telemetry job to stop."""; return self.controller.log_stop(job_id)
    def log_export(self, job_id: str, format: Literal["csv"] = "csv") -> dict:
        """Export completed or active telemetry samples as CSV."""; return self.controller.log_export(job_id, format)
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
    def set_brick_name(self, name: str) -> dict:
        """Set the NXT's short ASCII display name."""; return self.controller.set_brick_name(name)
    def keep_alive(self) -> dict:
        """Reset the stock firmware standby timer and report its configured timeout."""; return self.controller.keep_alive()


READ_ONLY = {"nxt_info", "motor_position", "motor_state", "read_sensor", "read_sensor_raw", "read_sensor_relative", "query_all_state", "validate_behavior", "list_behaviors", "get_behavior", "current_program", "list_files", "read_file", "mailbox_receive", "log_status", "log_export"}
IDEMPOTENT = {"stop_motor", "stop_motors", "emergency_stop", "zero_motor_position", "validate_behavior"}


def create_server(*, controller: NxtController | None = None, behavior_dir: Path | None = None) -> MCPServer:
    """Create an isolated server instance usable by STDIO, HTTP, and tests."""
    controller = controller or NxtController(NxtPythonHardware())
    behavior_dir = behavior_dir or Path(os.getenv("NXT_BEHAVIOR_DIR", Path.cwd() / "behaviors"))
    tools = NxtTools(controller, BehaviorRunner(behavior_dir, controller))
    server = MCPServer("robot-nxt-control", version="0.1.0", instructions="Control one compatible programmable brick over USB. Prefer bounded motion tools. Use emergency_stop if motion is unexpected. Do not mix direct motor control with a running .rxe program.")
    for name in dir(tools):
        if name.startswith("_"):
            continue
        handler = getattr(tools, name)
        if callable(handler):
            server.tool(name=name, annotations=ToolAnnotations(readOnlyHint=name in READ_ONLY, destructiveHint=False, idempotentHint=name in IDEMPOTENT, openWorldHint=False))(handler)
    atexit.register(controller.close)
    return server


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Programmable-brick MCP server")
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
