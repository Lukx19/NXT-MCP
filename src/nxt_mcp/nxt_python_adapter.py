"""NXT-Python implementation of the hardware seam."""

from __future__ import annotations

import os
import sys
import threading
import time
from enum import Enum
from pathlib import Path
from typing import Any

from .hardware import MotorPort, SensorPort, SensorType


class NxtPythonHardware:
    def __init__(self, sensor_map: dict[int, SensorType] | None = None) -> None:
        self._brick: Any | None = None
        self._sensors: dict[tuple[int, str], Any] = {}
        self._sensor_types = (
            dict(sensor_map)
            if sensor_map is not None
            else self._parse_sensor_map(os.getenv("NXT_SENSOR_MAP", ""))
        )
        self._lock = threading.RLock()

    @staticmethod
    def _modules() -> tuple[Any, Any, Any, dict[str, Any]]:
        NxtPythonHardware._enable_local_libusb()
        import nxt.locator
        import nxt.motor
        import nxt.sensor
        from nxt.sensor.generic import Color, Light, Sound, Temperature, Touch, Ultrasonic

        classes = {
            "touch": Touch,
            "light": Light,
            "sound": Sound,
            "ultrasonic": Ultrasonic,
            "color": Color,
            "temperature": Temperature,
        }
        return nxt.locator, nxt.motor, nxt.sensor, classes

    @staticmethod
    def _enable_local_libusb() -> None:
        """Make a project-local libusb DLL discoverable without venv activation."""
        if sys.platform != "win32":
            return
        configured = os.getenv("NXT_LIBUSB_PATH")
        candidate = configured or str(Path(sys.executable).parent / "libusb-1.0.dll")
        if os.path.isfile(candidate):
            directory = os.path.dirname(os.path.abspath(candidate))
            path_entries = os.environ.get("PATH", "").split(os.pathsep)
            if directory not in path_entries:
                os.environ["PATH"] = directory + os.pathsep + os.environ.get("PATH", "")

    def _get_brick(self) -> Any:
        if self._brick is None:
            locator, _, _, _ = self._modules()
            self._brick = locator.find(backends=["usb"])
        return self._brick

    def _motor_port(self, port: MotorPort) -> Any:
        _, motor, _, _ = self._modules()
        return {"A": motor.Port.A, "B": motor.Port.B, "C": motor.Port.C}[port]

    def _sensor_port(self, port: SensorPort) -> Any:
        _, _, sensor, _ = self._modules()
        return {1: sensor.Port.S1, 2: sensor.Port.S2, 3: sensor.Port.S3, 4: sensor.Port.S4}[port]

    def _sensor(self, port: SensorPort, sensor_type: SensorType) -> Any:
        key = (port, sensor_type)
        if key not in self._sensors:
            _, _, _, classes = self._modules()
            # A port can only have one active sensor configuration.
            self._sensors = {k: v for k, v in self._sensors.items() if k[0] != port}
            self._sensors[key] = classes[sensor_type](self._get_brick(), self._sensor_port(port))
        self._sensor_types[port] = sensor_type
        return self._sensors[key]

    def brick_info(self) -> dict[str, Any]:
        with self._lock:
            brick = self._get_brick()
            name, bluetooth_address, _signal, free_flash = brick.get_device_info()
            protocol_version, firmware_version = brick.get_firmware_version()
            return {
                "name": name,
                "bluetooth_address": bluetooth_address,
                "free_flash_bytes": free_flash,
                "battery_mv": brick.get_battery_level(),
                "protocol_version": ".".join(map(str, protocol_version)),
                "firmware_version": ".".join(map(str, firmware_version)),
            }

    def run_motor(self, port: MotorPort, power: int, regulated: bool = True) -> None:
        with self._lock:
            self._get_brick().get_motor(self._motor_port(port)).run(power=power, regulated=regulated)

    def stop_motor(self, port: MotorPort, brake: bool = False) -> None:
        with self._lock:
            motor = self._get_brick().get_motor(self._motor_port(port))
            motor.brake() if brake else motor.idle()

    def turn_motor(
        self, port: MotorPort, power: int, ticks: int, brake: bool, timeout_seconds: float
    ) -> None:
        """Turn with a tight USB encoder loop; BaseMotor.turn polls only every 100 ms."""
        with self._lock:
            motor = self._get_brick().get_motor(self._motor_port(port))
            start = motor.get_tacho().tacho_count
            started_at = time.monotonic()
            last_motion_at = started_at
            last_position = start
            motor.run(power=power, regulated=True)
            try:
                while True:
                    current = motor.get_tacho().tacho_count
                    now = time.monotonic()
                    if abs(current - start) >= ticks:
                        break
                    if current != last_position:
                        last_position = current
                        last_motion_at = now
                    elif now - last_motion_at >= timeout_seconds:
                        raise TimeoutError(
                            f"motor {port} did not move for {timeout_seconds:g} seconds"
                        )
                    if now - started_at >= timeout_seconds:
                        raise TimeoutError(
                            f"motor {port} did not reach {ticks} ticks within {timeout_seconds:g} seconds"
                        )
            finally:
                motor.brake() if brake else motor.idle()

    def reset_motor_position(self, port: MotorPort) -> None:
        with self._lock:
            self._get_brick().get_motor(self._motor_port(port)).reset_position(relative=False)

    def run_motors(
        self, movements: list[tuple[MotorPort, int]], regulated: bool = True
    ) -> None:
        with self._lock:
            brick = self._get_brick()
            started: list[Any] = []
            try:
                for port, power in movements:
                    motor = brick.get_motor(self._motor_port(port))
                    motor.run(power=power, regulated=regulated)
                    started.append(motor)
            except Exception:
                for motor in started:
                    try:
                        motor.idle()
                    except Exception:
                        pass
                raise

    def stop_motors(self, ports: list[MotorPort], brake: bool = False) -> None:
        with self._lock:
            brick = self._get_brick()
            first_error: Exception | None = None
            for port in ports:
                try:
                    motor = brick.get_motor(self._motor_port(port))
                    motor.brake() if brake else motor.idle()
                except Exception as exc:
                    first_error = first_error or exc
            if first_error is not None:
                raise first_error

    def turn_motors(
        self,
        movements: list[tuple[MotorPort, int, int]],
        brake: bool,
        timeout_seconds: float,
    ) -> None:
        """Start a motor group, monitor every encoder, and stop each at its target."""
        with self._lock:
            brick = self._get_brick()
            motors = {
                port: brick.get_motor(self._motor_port(port))
                for port, _power, _ticks in movements
            }
            starts = {port: motor.get_tacho().tacho_count for port, motor in motors.items()}
            targets = {port: ticks for port, _power, ticks in movements}
            last_positions = dict(starts)
            started_at = time.monotonic()
            last_motion_at = {port: started_at for port in motors}
            active = set(motors)
            try:
                for port, power, _ticks in movements:
                    motors[port].run(power=power, regulated=True)
                while active:
                    now = time.monotonic()
                    for port in tuple(active):
                        current = motors[port].get_tacho().tacho_count
                        if abs(current - starts[port]) >= targets[port]:
                            motors[port].brake() if brake else motors[port].idle()
                            active.remove(port)
                            continue
                        if current != last_positions[port]:
                            last_positions[port] = current
                            last_motion_at[port] = now
                        elif now - last_motion_at[port] >= timeout_seconds:
                            raise TimeoutError(
                                f"motor {port} did not move for {timeout_seconds:g} seconds"
                            )
                    if now - started_at >= timeout_seconds:
                        pending = ", ".join(sorted(active))
                        raise TimeoutError(
                            f"motors {pending} did not reach their targets within "
                            f"{timeout_seconds:g} seconds"
                        )
            finally:
                for port in active:
                    motors[port].brake() if brake else motors[port].idle()

    def motor_state(self, port: MotorPort) -> dict[str, Any]:
        with self._lock:
            values = self._get_brick().get_output_state(self._motor_port(port))
            return self._motor_values(port, values)

    def read_sensor(self, port: SensorPort, sensor_type: SensorType) -> dict[str, Any]:
        units = {
            "touch": "boolean",
            "light": "raw_0_1023",
            "sound": "raw_0_1023",
            "ultrasonic": "cm",
            "color": "color",
            "temperature": "degC",
        }
        with self._lock:
            value = self._json_value(self._sensor(port, sensor_type).get_sample())
        return {"port": port, "sensor_type": sensor_type, "value": value, "units": units[sensor_type]}

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            brick = self._get_brick()
            info = self.brick_info()
            motors = [
                self._motor_values(port, brick.get_output_state(self._motor_port(port)))
                for port in ("A", "B", "C")
            ]
            sensors = [self._snapshot_sensor(port) for port in (1, 2, 3, 4)]
            return {"brick": info, "motors": motors, "sensors": sensors}

    def _snapshot_sensor(self, port: SensorPort) -> dict[str, Any]:
        configured = self._sensor_types.get(port)
        if configured is not None:
            try:
                reading = self.read_sensor(port, configured)
                reading["configured_type"] = configured
                return reading
            except Exception as exc:
                return {"port": port, "configured_type": configured, "error": str(exc)}

        try:
            values = self._get_brick().get_input_values(self._sensor_port(port))
            return {
                "port": port,
                "configured_type": None,
                "valid": values[1],
                "firmware_type": self._enum_name(values[3]),
                "firmware_mode": self._enum_name(values[4]),
                "raw_value": values[5],
                "normalized_value": values[6],
                "scaled_value": values[7],
            }
        except Exception as exc:
            return {"port": port, "configured_type": None, "error": str(exc)}

    @classmethod
    def _motor_values(cls, port: MotorPort, values: tuple[Any, ...]) -> dict[str, Any]:
        return {
            "port": port,
            "power": values[1],
            "mode": cls._enum_name(values[2]),
            "regulation_mode": cls._enum_name(values[3]),
            "turn_ratio": values[4],
            "run_state": cls._enum_name(values[5]),
            "tacho_limit": values[6],
            "tacho_count": values[7],
            "block_tacho_count": values[8],
            "rotation_count": values[9],
        }

    def emergency_stop(self) -> None:
        with self._lock:
            for port in ("A", "B", "C"):
                try:
                    self.stop_motor(port, brake=False)
                except Exception:
                    pass

    def start_program(self, name: str) -> None:
        with self._lock:
            self._get_brick().start_program(name)
            self._sensors.clear()

    def stop_program(self) -> None:
        with self._lock:
            self._get_brick().stop_program()
            self._sensors.clear()

    def current_program(self) -> str | None:
        with self._lock:
            try:
                return self._get_brick().get_current_program_name()
            except Exception:
                return None

    def play_tone(self, frequency_hz: int, duration_ms: int) -> None:
        with self._lock:
            self._get_brick().play_tone(frequency_hz, duration_ms)

    def close(self) -> None:
        with self._lock:
            if self._brick is not None:
                self._brick.close()
                self._brick = None
                self._sensors.clear()

    @staticmethod
    def _parse_sensor_map(value: str) -> dict[int, SensorType]:
        """Parse a compact map such as ``1:touch,4:ultrasonic``."""
        if not value.strip():
            return {}
        allowed = {"touch", "light", "sound", "ultrasonic", "color", "temperature"}
        result: dict[int, SensorType] = {}
        for entry in value.split(","):
            try:
                port_text, sensor_type = (part.strip().lower() for part in entry.split(":"))
                port = int(port_text)
            except (TypeError, ValueError) as exc:
                raise ValueError("NXT_SENSOR_MAP must look like '1:touch,4:ultrasonic'") from exc
            if port not in (1, 2, 3, 4) or sensor_type not in allowed:
                raise ValueError(f"invalid NXT sensor mapping: {entry!r}")
            result[port] = sensor_type  # type: ignore[assignment]
        return result

    @staticmethod
    def _enum_name(value: Any) -> str:
        return value.name.lower() if isinstance(value, Enum) else str(value)

    @classmethod
    def _json_value(cls, value: Any) -> Any:
        if isinstance(value, Enum):
            return {"value": value.value, "name": value.name}
        if isinstance(value, tuple):
            return [cls._json_value(item) for item in value]
        return value
