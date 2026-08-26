"""Safe, high-level NXT behaviors independent of MCP and NXT-Python."""

from __future__ import annotations

import threading
import time
import csv
import io
import uuid
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
        self._sensor_zeroes: dict[tuple[int, str], float] = {}
        self._logs: dict[str, dict[str, Any]] = {}
        self._log_lock = threading.RLock()

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

    def motor_state(self, port: MotorPort) -> dict[str, Any]:
        with self._lock:
            state = self._hardware.motor_state(port)
        return {**state, "running": state.get("run_state") != "idle", "brake_mode": "brake" in state.get("mode", "")}

    def drive_sync(self, left_port: MotorPort, right_port: MotorPort, power: int, turn_ratio: int = 0) -> dict[str, Any]:
        self._validate_ports([left_port, right_port])
        self._validate_power(power, allow_zero=False)
        if not -100 <= turn_ratio <= 100:
            raise ValueError("turn_ratio must be between -100 and 100")
        with self._lock:
            self._hardware.drive_sync(left_port, right_port, power, turn_ratio)
        return {"ok": True, "left_port": left_port, "right_port": right_port, "power": power, "turn_ratio": turn_ratio, "regulated": "sync"}

    def wait_motors(self, ports: list[MotorPort], timeout_seconds: float = 10.0, brake: bool = True) -> dict[str, Any]:
        self._validate_ports(ports)
        if not 0.01 <= timeout_seconds <= 300:
            raise ValueError("timeout_seconds must be between 0.01 and 300")
        started = self._clock()
        with self._lock:
            try:
                while any(self._hardware.motor_state(port).get("run_state") != "idle" for port in ports):
                    if self._clock() - started >= timeout_seconds:
                        self._hardware.stop_motors(ports, brake)
                        return {"ok": False, "reason": "timeout", "ports": ports, "elapsed_seconds": round(self._clock() - started, 3)}
                    self._sleep(0.02)
            except Exception:
                self._hardware.stop_motors(ports, brake)
                raise
        return {"ok": True, "reason": "stopped", "ports": ports, "elapsed_seconds": round(self._clock() - started, 3)}

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

    def read_sensor_raw(self, port: SensorPort, sensor_type: SensorType | None = None) -> dict[str, Any]:
        with self._lock:
            if sensor_type is not None:
                self._hardware.read_sensor(port, sensor_type)
            return self._hardware.raw_sensor_state(port)

    def zero_sensor_reference(self, port: SensorPort, sensor_type: SensorType) -> dict[str, Any]:
        if sensor_type not in ("light", "color", "ultrasonic"):
            raise ValueError("relative sensor reference is supported for light, color, and ultrasonic only")
        with self._lock:
            value = self._hardware.relative_sensor_value(port, sensor_type)
        self._sensor_zeroes[(port, sensor_type)] = float(value)
        units = "reflected_raw_0_1023" if sensor_type == "color" else ("cm" if sensor_type == "ultrasonic" else "raw_0_1023")
        return {"ok": True, "port": port, "sensor_type": sensor_type, "zero_value": value, "units": units}

    def read_sensor_relative(self, port: SensorPort, sensor_type: SensorType) -> dict[str, Any]:
        if sensor_type not in ("light", "color", "ultrasonic"):
            raise ValueError("relative sensor mode is supported for light, color, and ultrasonic only")
        with self._lock:
            value = self._hardware.relative_sensor_value(port, sensor_type)
        key = (port, sensor_type)
        if key not in self._sensor_zeroes:
            raise ValueError("sensor reference is not set; call zero_sensor_reference first")
        zero = self._sensor_zeroes[key]
        units = "reflected_raw_0_1023" if sensor_type == "color" else ("cm" if sensor_type == "ultrasonic" else "raw_0_1023")
        return {"port": port, "sensor_type": sensor_type, "value": value - zero, "absolute_value": value, "zero_value": zero, "units": units}

    def wait_sensor(self, port: SensorPort, sensor_type: SensorType, condition: SensorCondition, threshold: float | None = None, debounce_ms: int = 0, timeout_seconds: float = 20.0) -> dict[str, Any]:
        predicate = self._sensor_predicate(sensor_type, condition, threshold)
        if not 0 <= debounce_ms <= 5000 or not 0.01 <= timeout_seconds <= 300:
            raise ValueError("invalid debounce_ms or timeout_seconds")
        started = self._clock()
        matched_at: float | None = None
        last: dict[str, Any] | None = None
        while self._clock() - started < timeout_seconds:
            last = self.read_sensor(port, sensor_type)
            if predicate(last["value"]):
                matched_at = matched_at or self._clock()
                if (self._clock() - matched_at) * 1000 >= debounce_ms:
                    return {"ok": True, "reason": "sensor_reached", "sensor": last, "elapsed_seconds": round(self._clock() - started, 3)}
            else:
                matched_at = None
            self._sleep(0.02)
        return {"ok": False, "reason": "timeout", "sensor": last, "elapsed_seconds": round(self._clock() - started, 3)}

    def play_sound_file(self, name: str, loop: bool = False) -> dict[str, Any]:
        self._validate_brick_filename(name, allowed_extensions={".rso"})
        with self._lock:
            self._hardware.play_sound_file(name, loop)
        return {"ok": True, "name": name, "loop": loop}

    def stop_sound(self) -> dict[str, Any]:
        with self._lock:
            self._hardware.stop_sound()
        return {"ok": True, "state": "stopped"}

    def list_files(self, pattern: str = "*.*") -> dict[str, Any]:
        if pattern not in ("*.*",) and ("/" in pattern or "\\" in pattern or len(pattern) > 20):
            raise ValueError("pattern must be a simple NXT file pattern")
        with self._lock:
            files = self._hardware.list_files(pattern)
        return {"files": [{"name": name, "size_bytes": size} for name, size in files]}

    def read_file(self, name: str, max_bytes: int = 65536) -> dict[str, Any]:
        self._validate_brick_filename(name)
        if not 1 <= max_bytes <= 65536:
            raise ValueError("max_bytes must be between 1 and 65536")
        with self._lock:
            content = self._hardware.read_file(name, max_bytes)
        return {"name": name, "size_bytes": len(content), "content": content.decode("utf-8", errors="replace")}

    def write_file(self, name: str, content: str, overwrite: bool = False) -> dict[str, Any]:
        self._validate_brick_filename(name, allowed_extensions={".txt", ".csv", ".dat", ".rso"})
        data = content.encode("utf-8")
        if len(data) > 65536:
            raise ValueError("content must not exceed 65536 bytes")
        with self._lock:
            if overwrite:
                try:
                    self._hardware.delete_file(name)
                except Exception as exc:
                    if type(exc).__name__ != "FileNotFoundError":
                        raise
            self._hardware.write_file(name, data)
        return {"ok": True, "name": name, "size_bytes": len(data)}

    def delete_file(self, name: str) -> dict[str, Any]:
        self._validate_brick_filename(name)
        with self._lock:
            self._hardware.delete_file(name)
        return {"ok": True, "name": name}

    def mailbox_send(self, inbox: int, data: str) -> dict[str, Any]:
        encoded = data.encode("utf-8")
        if not 0 <= inbox <= 19 or len(encoded) > 58:
            raise ValueError("inbox must be 0..19 and data must be at most 58 UTF-8 bytes")
        with self._lock:
            self._hardware.mailbox_send(inbox, encoded)
        return {"ok": True, "inbox": inbox, "bytes": len(encoded)}

    def mailbox_receive(self, inbox: int, remove: bool = True) -> dict[str, Any]:
        if not 0 <= inbox <= 19:
            raise ValueError("inbox must be 0..19")
        with self._lock:
            data = self._hardware.mailbox_receive(inbox, remove)
        return {"inbox": inbox, "removed": remove, "data": data.decode("utf-8", errors="replace")}

    def i2c_transaction(self, port: SensorPort, write_bytes: list[int], read_length: int, timeout_seconds: float = 1.0) -> dict[str, Any]:
        if not 0 <= len(write_bytes) <= 16 or not 0 <= read_length <= 16 or not 0.01 <= timeout_seconds <= 10:
            raise ValueError("I2C write/read lengths must be 0..16 and timeout_seconds 0.01..10")
        if any(not 0 <= value <= 255 for value in write_bytes):
            raise ValueError("write_bytes must contain bytes from 0 to 255")
        with self._lock:
            data = self._hardware.i2c_transaction(port, bytes(write_bytes), read_length, timeout_seconds)
        return {"port": port, "read_bytes": list(data)}

    def set_brick_name(self, name: str) -> dict[str, Any]:
        if not 1 <= len(name) <= 15 or not name.isascii() or "\0" in name:
            raise ValueError("name must contain 1..15 ASCII characters")
        with self._lock:
            self._hardware.set_brick_name(name)
        return {"ok": True, "name": name}

    def keep_alive(self) -> dict[str, Any]:
        with self._lock:
            timeout_ms = self._hardware.keep_alive()
        return {"ok": True, "sleep_timeout_ms": timeout_ms}

    def sensor_stream(self, port: SensorPort, sensor_type: SensorType, sample_interval_ms: int = 100, duration_seconds: float = 5.0, max_samples: int = 100) -> dict[str, Any]:
        if not 10 <= sample_interval_ms <= 1000 or not 0.01 <= duration_seconds <= 300 or not 1 <= max_samples <= 10000:
            raise ValueError("invalid stream interval, duration, or sample limit")
        started = self._clock(); samples: list[dict[str, Any]] = []
        while len(samples) < max_samples and self._clock() - started < duration_seconds:
            samples.append({"elapsed_ms": round((self._clock() - started) * 1000), "reading": self.read_sensor(port, sensor_type)})
            self._sleep(sample_interval_ms / 1000)
        return {"ok": True, "port": port, "sensor_type": sensor_type, "samples": samples, "truncated": len(samples) == max_samples}

    def log_start(self, channels: list[str], interval_ms: int = 100, duration_seconds: float = 10.0) -> dict[str, Any]:
        if not channels or len(channels) > 12 or not 10 <= interval_ms <= 1000 or not 0.1 <= duration_seconds <= 300:
            raise ValueError("invalid channels, interval_ms, or duration_seconds")
        for channel in channels:
            self._validate_log_channel(channel)
        job_id = uuid.uuid4().hex[:12]
        job = {"id": job_id, "channels": channels, "interval_ms": interval_ms, "duration_seconds": duration_seconds, "started": time.monotonic(), "samples": [], "state": "running", "stop": threading.Event()}
        def collect() -> None:
            deadline = time.monotonic() + duration_seconds
            try:
                while not job["stop"].is_set() and time.monotonic() < deadline:
                    row = {"elapsed_ms": round((time.monotonic() - job["started"]) * 1000)}
                    for channel in channels:
                        row[channel] = self._log_value(channel)
                    with self._log_lock:
                        job["samples"].append(row)
                    job["stop"].wait(interval_ms / 1000)
                job["state"] = "stopped" if job["stop"].is_set() else "completed"
            except Exception as exc:
                job["state"] = "failed"; job["error"] = str(exc)
        with self._log_lock:
            self._logs[job_id] = job
        threading.Thread(target=collect, name=f"nxt-log-{job_id}", daemon=True).start()
        return {"ok": True, "job_id": job_id, "channels": channels, "state": "running"}

    def log_status(self, job_id: str) -> dict[str, Any]:
        with self._log_lock:
            job = self._get_log(job_id)
            return {"job_id": job_id, "state": job["state"], "sample_count": len(job["samples"]), "error": job.get("error")}

    def log_stop(self, job_id: str) -> dict[str, Any]:
        with self._log_lock:
            job = self._get_log(job_id); job["stop"].set()
        return self.log_status(job_id)

    def log_export(self, job_id: str, format: str = "csv") -> dict[str, Any]:
        if format != "csv":
            raise ValueError("only csv export is supported")
        with self._log_lock:
            job = self._get_log(job_id); rows = list(job["samples"]); channels = list(job["channels"])
        buffer = io.StringIO(); writer = csv.DictWriter(buffer, fieldnames=["elapsed_ms", *channels]); writer.writeheader(); writer.writerows(rows)
        return {"job_id": job_id, "format": "csv", "content": buffer.getvalue(), "sample_count": len(rows)}

    def _log_value(self, channel: str) -> Any:
        if channel == "battery_mv":
            return self.info()["battery_mv"]
        kind, port, *tail = channel.split(":")
        if kind == "motor":
            return self.motor_position(port)["position_degrees"]
        return self.read_sensor(int(port), tail[0])["value"]

    @staticmethod
    def _validate_log_channel(channel: str) -> None:
        if channel == "battery_mv":
            return
        parts = channel.split(":")
        if len(parts) == 2 and parts[0] == "motor" and parts[1] in ("A", "B", "C"):
            return
        if len(parts) == 3 and parts[0] == "sensor" and parts[1] in ("1", "2", "3", "4") and parts[2] in ("touch", "light", "sound", "ultrasonic", "color", "temperature"):
            return
        raise ValueError("channels must be battery_mv, motor:A|B|C, or sensor:1..4:<type>")

    def _get_log(self, job_id: str) -> dict[str, Any]:
        if job_id not in self._logs:
            raise ValueError("unknown log job")
        return self._logs[job_id]

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
    def _validate_brick_filename(name: str, allowed_extensions: set[str] | None = None) -> None:
        from pathlib import PurePosixPath
        path = PurePosixPath(name)
        if name != path.name or not 1 <= len(name) <= 19 or not name.isascii() or "\\" in name:
            raise ValueError("name must be a 1..19 character ASCII brick filename without a path")
        if allowed_extensions is not None and path.suffix.lower() not in allowed_extensions:
            allowed = ", ".join(sorted(allowed_extensions))
            raise ValueError(f"filename extension must be one of: {allowed}")

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
