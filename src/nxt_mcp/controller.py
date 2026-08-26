"""Safe, high-level NXT behaviors independent of MCP and NXT-Python."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any, Literal

from .hardware import MotorPort, NxtHardware, SensorPort, SensorType

SensorCondition = Literal["pressed", "released", "lt", "lte", "gt", "gte", "eq"]


class NxtController:
    """Deep module that serializes brick access and owns motion safety rules."""

    def __init__(
        self,
        hardware: NxtHardware,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._hardware = hardware
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.RLock()

    def info(self) -> dict[str, Any]:
        with self._lock:
            return self._hardware.brick_info()

    def run_motor(self, port: MotorPort, power: int, regulated: bool = True) -> dict[str, Any]:
        self._validate_power(power, allow_zero=False)
        with self._lock:
            self._hardware.run_motor(port, power, regulated)
        return {"ok": True, "port": port, "power": power, "regulated": regulated}

    def stop_motor(self, port: MotorPort, brake: bool = False) -> dict[str, Any]:
        with self._lock:
            self._hardware.stop_motor(port, brake)
        return {"ok": True, "port": port, "brake": brake}

    def motor_position(self, port: MotorPort) -> dict[str, Any]:
        with self._lock:
            state = self._hardware.motor_state(port)
        return {
            "port": port,
            "position_degrees": state["rotation_count"],
            "tacho_count": state["tacho_count"],
            "block_tacho_count": state["block_tacho_count"],
        }

    def zero_motor_position(self, port: MotorPort) -> dict[str, Any]:
        """Set the firmware program-relative encoder count to zero."""
        with self._lock:
            self._hardware.stop_motor(port, brake=True)
            self._hardware.reset_motor_position(port)
            state = self._hardware.motor_state(port)
        return {"ok": True, "port": port, "position_degrees": state["rotation_count"]}

    def run_motor_for_ticks(
        self,
        port: MotorPort,
        power: int,
        ticks: int,
        brake: bool = True,
        timeout_seconds: float = 10.0,
    ) -> dict[str, Any]:
        """Rotate a motor by a relative encoder amount using NXT-Python's turn logic."""
        self._validate_power(power, allow_zero=False)
        if ticks <= 0:
            raise ValueError("ticks must be greater than zero")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")

        with self._lock:
            before = self._hardware.motor_state(port)
            self._hardware.turn_motor(port, power, ticks, brake, timeout_seconds)
            after = self._hardware.motor_state(port)

        return {
            "ok": True,
            "port": port,
            "power": power,
            "requested_ticks": ticks,
            "travelled_ticks": abs(after["tacho_count"] - before["tacho_count"]),
            "overshoot_ticks": max(
                0, abs(after["tacho_count"] - before["tacho_count"]) - ticks
            ),
            "start_tacho": before["tacho_count"],
            "end_tacho": after["tacho_count"],
            "brake": brake,
        }

    def move_motor_absolute(
        self,
        port: MotorPort,
        target_degrees: int,
        power: int = 20,
        brake: bool = True,
        timeout_seconds: float = 30.0,
    ) -> dict[str, Any]:
        """Move to an absolute firmware encoder position set by zero_motor_position."""
        if not 1 <= power <= 100:
            raise ValueError("power must be a positive magnitude between 1 and 100")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        with self._lock:
            before = self._hardware.motor_state(port)
            start = before["rotation_count"]
            delta = target_degrees - start
            if delta:
                signed_power = power if delta > 0 else -power
                self._hardware.turn_motor(port, signed_power, abs(delta), brake, timeout_seconds)
            after = self._hardware.motor_state(port)
        actual = after["rotation_count"]
        return {
            "ok": True,
            "port": port,
            "start_degrees": start,
            "target_degrees": target_degrees,
            "actual_degrees": actual,
            "error_degrees": actual - target_degrees,
            "power": power,
            "brake": brake,
        }

    def run_motors(
        self,
        ports: list[MotorPort],
        powers: list[int],
        regulated: bool = True,
    ) -> dict[str, Any]:
        movements = self._validate_motor_group(ports, powers)
        with self._lock:
            self._hardware.run_motors(movements, regulated)
        return {
            "ok": True,
            "motors": [{"port": port, "power": power} for port, power in movements],
            "regulated": regulated,
        }

    def stop_motors(self, ports: list[MotorPort], brake: bool = False) -> dict[str, Any]:
        self._validate_ports(ports)
        with self._lock:
            self._hardware.stop_motors(ports, brake)
        return {"ok": True, "ports": ports, "brake": brake}

    def move_motors_relative(
        self,
        ports: list[MotorPort],
        powers: list[int],
        degrees: list[int],
        brake: bool = True,
        timeout_seconds: float = 30.0,
    ) -> dict[str, Any]:
        movements = self._validate_motor_group(ports, powers, degrees)
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        with self._lock:
            before = {port: self._hardware.motor_state(port) for port in ports}
            self._hardware.turn_motors(
                [(port, power, ticks) for (port, power), ticks in zip(movements, degrees)],
                brake,
                timeout_seconds,
            )
            after = {port: self._hardware.motor_state(port) for port in ports}
        return {
            "ok": True,
            "motors": [
                {
                    "port": port,
                    "power": power,
                    "requested_degrees": ticks,
                    "travelled_degrees": abs(
                        after[port]["tacho_count"] - before[port]["tacho_count"]
                    ),
                }
                for (port, power), ticks in zip(movements, degrees)
            ],
            "brake": brake,
        }

    def move_motors_absolute(
        self,
        ports: list[MotorPort],
        powers: list[int],
        target_degrees: list[int],
        brake: bool = True,
        timeout_seconds: float = 30.0,
    ) -> dict[str, Any]:
        self._validate_ports(ports)
        if len(ports) != len(powers) or len(ports) != len(target_degrees):
            raise ValueError("ports, powers, and target_degrees must have equal lengths")
        if any(not 1 <= power <= 100 for power in powers):
            raise ValueError("absolute-move powers must be positive magnitudes from 1 to 100")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        with self._lock:
            before = {port: self._hardware.motor_state(port) for port in ports}
            pending: list[tuple[MotorPort, int, int]] = []
            for port, power, target in zip(ports, powers, target_degrees):
                delta = target - before[port]["rotation_count"]
                if delta:
                    pending.append((port, power if delta > 0 else -power, abs(delta)))
            if pending:
                self._hardware.turn_motors(pending, brake, timeout_seconds)
            after = {port: self._hardware.motor_state(port) for port in ports}
        return {
            "ok": True,
            "motors": [
                {
                    "port": port,
                    "target_degrees": target,
                    "actual_degrees": after[port]["rotation_count"],
                    "error_degrees": after[port]["rotation_count"] - target,
                }
                for port, target in zip(ports, target_degrees)
            ],
            "brake": brake,
        }

    def run_motor_until_sensor(
        self,
        port: MotorPort,
        power: int,
        sensor_port: SensorPort,
        sensor_type: SensorType,
        condition: SensorCondition,
        threshold: float | None = None,
        *,
        brake: bool = True,
        regulated: bool = True,
        max_ticks: int = 3600,
        timeout_seconds: float = 15.0,
        poll_interval_seconds: float = 0.05,
    ) -> dict[str, Any]:
        """Run until a sensor matches, bounded by time and relative encoder travel."""
        self._validate_power(power, allow_zero=False)
        predicate = self._sensor_predicate(sensor_type, condition, threshold)
        if max_ticks <= 0:
            raise ValueError("max_ticks must be greater than zero")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if not 0.01 <= poll_interval_seconds <= 1.0:
            raise ValueError("poll_interval_seconds must be between 0.01 and 1.0")

        with self._lock:
            initial_sensor = self._hardware.read_sensor(sensor_port, sensor_type)
            start_tacho = self._hardware.motor_state(port)["tacho_count"]
            started_at = self._clock()
            final_sensor = initial_sensor
            reason = "sensor_reached" if predicate(initial_sensor["value"]) else "unknown"
            started_motor = reason != "sensor_reached"

            try:
                if started_motor:
                    self._hardware.run_motor(port, power, regulated)
                    while True:
                        final_sensor = self._hardware.read_sensor(sensor_port, sensor_type)
                        state = self._hardware.motor_state(port)
                        travelled = abs(state["tacho_count"] - start_tacho)
                        elapsed = self._clock() - started_at

                        if predicate(final_sensor["value"]):
                            reason = "sensor_reached"
                            break
                        if travelled >= max_ticks:
                            reason = "max_ticks_reached"
                            break
                        if elapsed >= timeout_seconds:
                            reason = "timeout"
                            break
                        self._sleep(poll_interval_seconds)
            finally:
                if started_motor:
                    self._hardware.stop_motor(port, brake)

            end_tacho = self._hardware.motor_state(port)["tacho_count"]
            elapsed = self._clock() - started_at

        return {
            "ok": reason == "sensor_reached",
            "reason": reason,
            "port": port,
            "power": power,
            "travelled_ticks": abs(end_tacho - start_tacho),
            "elapsed_seconds": round(elapsed, 3),
            "sensor": final_sensor,
            "brake": brake,
        }

    def run_motors_until_sensor(
        self,
        ports: list[MotorPort],
        powers: list[int],
        sensor_port: SensorPort,
        sensor_type: SensorType,
        condition: SensorCondition,
        threshold: float | None = None,
        *,
        brake: bool = True,
        regulated: bool = True,
        max_ticks: int = 3600,
        timeout_seconds: float = 20.0,
        poll_interval_seconds: float = 0.02,
    ) -> dict[str, Any]:
        """Run a motor group until one shared sensor condition or a safety limit."""
        movements = self._validate_motor_group(ports, powers)
        predicate = self._sensor_predicate(sensor_type, condition, threshold)
        if max_ticks <= 0:
            raise ValueError("max_ticks must be greater than zero")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if not 0.01 <= poll_interval_seconds <= 1.0:
            raise ValueError("poll_interval_seconds must be between 0.01 and 1.0")

        with self._lock:
            initial_sensor = self._hardware.read_sensor(sensor_port, sensor_type)
            starts = {
                port: self._hardware.motor_state(port)["tacho_count"] for port in ports
            }
            started_at = self._clock()
            final_sensor = initial_sensor
            reason = "sensor_reached" if predicate(initial_sensor["value"]) else "unknown"
            started_motors = reason != "sensor_reached"
            try:
                if started_motors:
                    self._hardware.run_motors(movements, regulated)
                    while True:
                        final_sensor = self._hardware.read_sensor(sensor_port, sensor_type)
                        states = {
                            port: self._hardware.motor_state(port) for port in ports
                        }
                        travelled = {
                            port: abs(states[port]["tacho_count"] - starts[port])
                            for port in ports
                        }
                        elapsed = self._clock() - started_at
                        if predicate(final_sensor["value"]):
                            reason = "sensor_reached"
                            break
                        if any(value >= max_ticks for value in travelled.values()):
                            reason = "max_ticks_reached"
                            break
                        if elapsed >= timeout_seconds:
                            reason = "timeout"
                            break
                        self._sleep(poll_interval_seconds)
            finally:
                if started_motors:
                    self._hardware.stop_motors(ports, brake)
            final_states = {
                port: self._hardware.motor_state(port) for port in ports
            }

        return {
            "ok": reason == "sensor_reached",
            "reason": reason,
            "motors": [
                {
                    "port": port,
                    "power": power,
                    "travelled_ticks": abs(
                        final_states[port]["tacho_count"] - starts[port]
                    ),
                }
                for port, power in movements
            ],
            "elapsed_seconds": round(self._clock() - started_at, 3),
            "sensor": final_sensor,
            "brake": brake,
        }

    def read_sensor(self, port: SensorPort, sensor_type: SensorType) -> dict[str, Any]:
        with self._lock:
            return self._hardware.read_sensor(port, sensor_type)

    def state(self, text: bool = True) -> str | dict[str, Any]:
        """Read the brick, all output ports, and all input ports in one MCP operation."""
        with self._lock:
            snapshot = self._hardware.snapshot()
        return self._format_snapshot(snapshot) if text else snapshot

    def emergency_stop(self) -> dict[str, Any]:
        with self._lock:
            self._hardware.emergency_stop()
        return {"ok": True, "motors": ["A", "B", "C"], "state": "stopped"}

    def play_tone(self, frequency_hz: int = 440, duration_ms: int = 500) -> dict[str, Any]:
        if not 200 <= frequency_hz <= 14000:
            raise ValueError("frequency_hz must be between 200 and 14000")
        if not 1 <= duration_ms <= 5000:
            raise ValueError("duration_ms must be between 1 and 5000")
        with self._lock:
            self._hardware.play_tone(frequency_hz, duration_ms)
        return {"ok": True, "frequency_hz": frequency_hz, "duration_ms": duration_ms}

    def cycle_motor_on_touch(
        self,
        port: MotorPort,
        touch_port: SensorPort,
        forward_power: int = 20,
        cycles: int = 5,
        *,
        max_ticks_per_phase: int = 3600,
        timeout_seconds_per_phase: float = 20.0,
        beep_frequency_hz: int = 440,
        beep_duration_ms: int = 500,
    ) -> dict[str, Any]:
        """Alternate until touch press/release for N cycles, then beep on success."""
        self._validate_power(forward_power, allow_zero=False)
        if not 1 <= cycles <= 20:
            raise ValueError("cycles must be between 1 and 20")
        if not 200 <= beep_frequency_hz <= 14000:
            raise ValueError("beep_frequency_hz must be between 200 and 14000")
        if not 1 <= beep_duration_ms <= 5000:
            raise ValueError("beep_duration_ms must be between 1 and 5000")

        results: list[dict[str, Any]] = []
        with self._lock:
            for cycle in range(1, cycles + 1):
                pressed = self.run_motor_until_sensor(
                    port,
                    forward_power,
                    touch_port,
                    "touch",
                    "pressed",
                    brake=True,
                    max_ticks=max_ticks_per_phase,
                    timeout_seconds=timeout_seconds_per_phase,
                    poll_interval_seconds=0.02,
                )
                results.append({"cycle": cycle, "phase": "press", **pressed})
                if not pressed["ok"]:
                    return {
                        "ok": False,
                        "reason": f"press phase failed: {pressed['reason']}",
                        "completed_cycles": cycle - 1,
                        "phases": results,
                        "beeped": False,
                    }

                released = self.run_motor_until_sensor(
                    port,
                    -forward_power,
                    touch_port,
                    "touch",
                    "released",
                    brake=True,
                    max_ticks=max_ticks_per_phase,
                    timeout_seconds=timeout_seconds_per_phase,
                    poll_interval_seconds=0.02,
                )
                results.append({"cycle": cycle, "phase": "release", **released})
                if not released["ok"]:
                    return {
                        "ok": False,
                        "reason": f"release phase failed: {released['reason']}",
                        "completed_cycles": cycle - 1,
                        "phases": results,
                        "beeped": False,
                    }

            try:
                self._hardware.play_tone(beep_frequency_hz, beep_duration_ms)
            finally:
                self._hardware.stop_motor(port, brake=False)

        return {
            "ok": True,
            "completed_cycles": cycles,
            "phases": results,
            "beeped": True,
            "beep_frequency_hz": beep_frequency_hz,
            "beep_duration_ms": beep_duration_ms,
        }

    def start_program(self, name: str) -> dict[str, Any]:
        if not name.lower().endswith(".rxe"):
            raise ValueError("program name must end with .rxe")
        with self._lock:
            self._hardware.start_program(name)
        return {"ok": True, "program": name, "state": "started"}

    def stop_program(self) -> dict[str, Any]:
        with self._lock:
            self._hardware.stop_program()
        return {"ok": True, "state": "stopped"}

    def current_program(self) -> dict[str, Any]:
        with self._lock:
            name = self._hardware.current_program()
        return {"running": name is not None, "program": name}

    def close(self) -> None:
        with self._lock:
            self._hardware.close()

    @staticmethod
    def _validate_power(power: int, *, allow_zero: bool) -> None:
        if not -100 <= power <= 100:
            raise ValueError("power must be between -100 and 100")
        if not allow_zero and power == 0:
            raise ValueError("power must not be zero")

    @staticmethod
    def _validate_ports(ports: list[MotorPort]) -> None:
        if not 1 <= len(ports) <= 3:
            raise ValueError("ports must contain between one and three motors")
        if len(set(ports)) != len(ports):
            raise ValueError("motor ports must be unique")
        if any(port not in ("A", "B", "C") for port in ports):
            raise ValueError("motor ports must be A, B, or C")

    @classmethod
    def _validate_motor_group(
        cls,
        ports: list[MotorPort],
        powers: list[int],
        degrees: list[int] | None = None,
    ) -> list[tuple[MotorPort, int]]:
        cls._validate_ports(ports)
        if len(ports) != len(powers):
            raise ValueError("ports and powers must have equal lengths")
        for power in powers:
            cls._validate_power(power, allow_zero=False)
        if degrees is not None:
            if len(ports) != len(degrees):
                raise ValueError("ports, powers, and degrees must have equal lengths")
            if any(value <= 0 for value in degrees):
                raise ValueError("all degree values must be greater than zero")
        return list(zip(ports, powers))

    @staticmethod
    def _sensor_predicate(
        sensor_type: SensorType, condition: SensorCondition, threshold: float | None
    ) -> Callable[[Any], bool]:
        if condition in ("pressed", "released"):
            if sensor_type != "touch":
                raise ValueError(f"condition '{condition}' is only valid for touch sensors")
            if threshold is not None:
                raise ValueError("threshold must be omitted for pressed/released conditions")
            return (lambda value: bool(value)) if condition == "pressed" else (lambda value: not bool(value))

        if threshold is None:
            raise ValueError(f"threshold is required for condition '{condition}'")
        comparisons: dict[str, Callable[[float], bool]] = {
            "lt": lambda value: value < threshold,
            "lte": lambda value: value <= threshold,
            "gt": lambda value: value > threshold,
            "gte": lambda value: value >= threshold,
            "eq": lambda value: value == threshold,
        }
        return comparisons[condition]

    @staticmethod
    def _format_snapshot(snapshot: dict[str, Any]) -> str:
        brick = snapshot["brick"]
        lines = [
            f"NXT {brick.get('name', 'unknown')} | battery={brick.get('battery_mv', '?')}mV "
            f"| free_flash={brick.get('free_flash_bytes', '?')}B",
            "Motors:",
        ]
        for motor in snapshot["motors"]:
            lines.append(
                f"  {motor['port']}: power={motor['power']} state={motor['run_state']} "
                f"tacho={motor['tacho_count']} block={motor['block_tacho_count']} "
                f"rotation={motor['rotation_count']}"
            )
        lines.append("Sensors:")
        for sensor in snapshot["sensors"]:
            if sensor.get("error"):
                detail = f"error={sensor['error']}"
            elif sensor.get("configured_type"):
                detail = f"{sensor['configured_type']} value={sensor.get('value')} {sensor.get('units', '')}".rstrip()
            else:
                detail = (
                    f"firmware_type={sensor.get('firmware_type')} valid={sensor.get('valid')} "
                    f"raw={sensor.get('raw_value')} scaled={sensor.get('scaled_value')}"
                )
            lines.append(f"  S{sensor['port']}: {detail}")
        lines.append(
            "Note: NXT cannot safely detect whether an idle motor is physically attached; "
            "motor rows report firmware port state."
        )
        return "\n".join(lines)
