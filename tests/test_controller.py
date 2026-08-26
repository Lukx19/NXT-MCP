from __future__ import annotations

from typing import Any
from types import SimpleNamespace

import pytest

from nxt_mcp.controller import NxtController
from nxt_mcp.nxt_python_adapter import NxtPythonHardware


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakeHardware:
    def __init__(self, sensor_values: list[Any] | None = None, ticks_per_read: int = 40) -> None:
        self.tacho = {"A": 0, "B": 0, "C": 0}
        self.power = {"A": 0, "B": 0, "C": 0}
        self.sensor_values = list(sensor_values or [False])
        self.sensor_index = 0
        self.ticks_per_read = ticks_per_read
        self.stop_calls: list[tuple[str, bool]] = []
        self.tones: list[tuple[int, int]] = []
        self.files: dict[str, bytes] = {}
        self.mailboxes: dict[int, bytes] = {}
        self.sync_calls: list[tuple[str, str, int, int]] = []

    def brick_info(self) -> dict[str, Any]:
        return {"name": "TEST", "battery_mv": 7600, "free_flash_bytes": 1234}

    def run_motor(self, port, power, regulated=True) -> None:
        self.power[port] = power

    def stop_motor(self, port, brake=False) -> None:
        self.power[port] = 0
        self.stop_calls.append((port, brake))

    def turn_motor(self, port, power, ticks, brake, timeout_seconds) -> None:
        self.tacho[port] += ticks if power > 0 else -ticks
        self.stop_motor(port, brake)

    def reset_motor_position(self, port) -> None:
        self.tacho[port] = 0

    def run_motors(self, movements, regulated=True) -> None:
        for port, power in movements:
            self.run_motor(port, power, regulated)

    def stop_motors(self, ports, brake=False) -> None:
        for port in ports:
            self.stop_motor(port, brake)

    def turn_motors(self, movements, brake, timeout_seconds) -> None:
        for port, power, ticks in movements:
            self.turn_motor(port, power, ticks, brake, timeout_seconds)

    def motor_state(self, port) -> dict[str, Any]:
        if self.power[port]:
            self.tacho[port] += self.ticks_per_read if self.power[port] > 0 else -self.ticks_per_read
        return {
            "port": port,
            "power": self.power[port],
            "run_state": "running" if self.power[port] else "idle",
            "tacho_count": self.tacho[port],
            "block_tacho_count": self.tacho[port],
            "rotation_count": self.tacho[port],
        }

    def drive_sync(self, left, right, power, turn_ratio) -> None:
        self.sync_calls.append((left, right, power, turn_ratio))
        self.power[left] = self.power[right] = power

    def read_sensor(self, port, sensor_type) -> dict[str, Any]:
        value = self.sensor_values[min(self.sensor_index, len(self.sensor_values) - 1)]
        self.sensor_index += 1
        return {"port": port, "sensor_type": sensor_type, "value": value, "units": "test"}

    def raw_sensor_state(self, port) -> dict[str, Any]:
        return {"port": port, "configured_type": "light", "valid": True, "raw_value": 500, "normalized_value": 500, "scaled_value": self.sensor_values[min(self.sensor_index, len(self.sensor_values) - 1)], "calibrated_value": 0}

    def relative_sensor_value(self, port, sensor_type) -> float:
        return float(self.sensor_values[min(self.sensor_index, len(self.sensor_values) - 1)])

    def snapshot(self) -> dict[str, Any]:
        return {
            "brick": self.brick_info(),
            "motors": [self.motor_state(port) for port in ("A", "B", "C")],
            "sensors": [
                {"port": 1, "configured_type": "touch", "value": False, "units": "boolean"},
                *[
                    {
                        "port": port,
                        "configured_type": None,
                        "firmware_type": "none",
                        "valid": True,
                        "raw_value": 0,
                        "scaled_value": 0,
                    }
                    for port in (2, 3, 4)
                ],
            ],
        }

    def emergency_stop(self) -> None:
        for port in ("A", "B", "C"):
            self.stop_motor(port)

    def start_program(self, name) -> None: pass
    def stop_program(self) -> None: pass
    def current_program(self): return None
    def play_tone(self, frequency_hz, duration_ms):
        self.tones.append((frequency_hz, duration_ms))
    def play_sound_file(self, name, loop): pass
    def stop_sound(self): pass
    def list_files(self, pattern): return [(name, len(data)) for name, data in self.files.items()]
    def read_file(self, name, max_bytes): return self.files[name]
    def write_file(self, name, content): self.files[name] = content
    def delete_file(self, name): self.files.pop(name)
    def mailbox_send(self, inbox, data): self.mailboxes[inbox] = data
    def mailbox_receive(self, inbox, remove): return self.mailboxes.pop(inbox) if remove else self.mailboxes[inbox]
    def i2c_transaction(self, port, write_bytes, read_length, timeout_seconds): return bytes(reversed(write_bytes))[:read_length]
    def set_brick_name(self, name): pass
    def keep_alive(self): return 120000
    def close(self) -> None: pass


def test_run_motor_for_ticks_reports_relative_encoder_travel() -> None:
    hardware = FakeHardware()
    controller = NxtController(hardware)

    result = controller.run_motor_for_ticks("A", 60, 360)

    assert result["travelled_ticks"] == 360
    assert result["end_tacho"] == 360
    assert hardware.stop_calls == [("A", True)]


def test_zero_then_move_to_absolute_position() -> None:
    hardware = FakeHardware()
    hardware.tacho["C"] = 300
    controller = NxtController(hardware)

    zeroed = controller.zero_motor_position("C")
    result = controller.move_motor_absolute("C", -40, power=20)

    assert zeroed["position_degrees"] == 0
    assert result["actual_degrees"] == -40
    assert result["error_degrees"] == 0


def test_move_multiple_motors_relative_with_independent_directions() -> None:
    hardware = FakeHardware()
    controller = NxtController(hardware)

    result = controller.move_motors_relative(
        ["A", "C"], [30, -40], [2000, 500]
    )

    assert hardware.tacho["A"] == 2000
    assert hardware.tacho["C"] == -500
    assert [motor["travelled_degrees"] for motor in result["motors"]] == [2000, 500]


def test_run_multiple_motors_until_touch_stops_entire_group() -> None:
    hardware = FakeHardware([False, False, True], ticks_per_read=25)
    clock = FakeClock()
    controller = NxtController(hardware, clock=clock, sleep=clock.sleep)

    result = controller.run_motors_until_sensor(
        ["A", "C"], [30, -30], 1, "touch", "pressed"
    )

    assert result["ok"] is True
    assert result["reason"] == "sensor_reached"
    assert hardware.power["A"] == hardware.power["C"] == 0
    assert ("A", True) in hardware.stop_calls
    assert ("C", True) in hardware.stop_calls


def test_motor_group_rejects_duplicate_ports() -> None:
    with pytest.raises(ValueError, match="unique"):
        NxtController(FakeHardware()).run_motors(["C", "C"], [20, 20])


def test_run_until_touch_stops_when_pressed() -> None:
    hardware = FakeHardware([False, False, True])
    clock = FakeClock()
    controller = NxtController(hardware, clock=clock, sleep=clock.sleep)

    result = controller.run_motor_until_sensor("B", 50, 1, "touch", "pressed")

    assert result["ok"] is True
    assert result["reason"] == "sensor_reached"
    assert result["sensor"]["value"] is True
    assert hardware.stop_calls == [("B", True)]


def test_run_until_distance_stops_at_tick_safety_limit() -> None:
    hardware = FakeHardware([100], ticks_per_read=60)
    clock = FakeClock()
    controller = NxtController(hardware, clock=clock, sleep=clock.sleep)

    result = controller.run_motor_until_sensor(
        "C", 40, 4, "ultrasonic", "lte", 20, max_ticks=100
    )

    assert result["ok"] is False
    assert result["reason"] == "max_ticks_reached"
    assert result["travelled_ticks"] >= 100
    assert hardware.stop_calls == [("C", True)]


def test_motor_is_stopped_when_sensor_read_raises() -> None:
    class BrokenSensorHardware(FakeHardware):
        def read_sensor(self, port, sensor_type):
            if self.sensor_index:
                raise RuntimeError("sensor disconnected")
            self.sensor_index += 1
            return {"port": port, "sensor_type": sensor_type, "value": False, "units": "boolean"}

    hardware = BrokenSensorHardware()
    controller = NxtController(hardware)

    with pytest.raises(RuntimeError, match="sensor disconnected"):
        controller.run_motor_until_sensor("A", 40, 1, "touch", "pressed")

    assert hardware.stop_calls == [("A", True)]


def test_state_text_contains_every_port_and_detection_limit() -> None:
    text = NxtController(FakeHardware()).state()

    assert all(f"  {port}:" in text for port in ("A", "B", "C"))
    assert all(f"  S{port}:" in text for port in (1, 2, 3, 4))
    assert "cannot safely detect" in text


@pytest.mark.parametrize(
    ("sensor_type", "condition", "threshold"),
    [("ultrasonic", "pressed", None), ("touch", "gte", None), ("touch", "pressed", 1)],
)
def test_invalid_sensor_conditions_are_rejected(sensor_type, condition, threshold) -> None:
    controller = NxtController(FakeHardware())

    with pytest.raises(ValueError):
        controller.run_motor_until_sensor("A", 40, 1, sensor_type, condition, threshold)


def test_sensor_map_parser() -> None:
    assert NxtPythonHardware._parse_sensor_map("1:touch, 4:ULTRASONIC") == {
        1: "touch",
        4: "ultrasonic",
    }

    with pytest.raises(ValueError, match="invalid NXT sensor mapping"):
        NxtPythonHardware._parse_sensor_map("5:touch")


def test_adapter_turn_uses_encoder_feedback_and_stops(monkeypatch) -> None:
    class FakeMotor:
        def __init__(self) -> None:
            self.position = 0
            self.running = False
            self.braked = False

        def get_tacho(self):
            if self.running:
                self.position += 10
            return SimpleNamespace(tacho_count=self.position)

        def run(self, power, regulated):
            self.running = True

        def brake(self):
            self.running = False
            self.braked = True

        def idle(self):
            self.running = False

    motor = FakeMotor()
    brick = SimpleNamespace(get_motor=lambda _port: motor)
    adapter = NxtPythonHardware(sensor_map={})
    monkeypatch.setattr(adapter, "_get_brick", lambda: brick)
    monkeypatch.setattr(adapter, "_motor_port", lambda port: port)

    adapter.turn_motor("C", power=20, ticks=45, brake=True, timeout_seconds=1)

    assert motor.position == 50
    assert motor.braked is True


def test_touch_cycle_alternates_directions_and_beeps() -> None:
    hardware = FakeHardware([False, False, True, True, True, False])
    clock = FakeClock()
    controller = NxtController(hardware, clock=clock, sleep=clock.sleep)

    result = controller.cycle_motor_on_touch("C", 1, cycles=1)

    assert result["ok"] is True
    assert result["completed_cycles"] == 1
    assert [phase["phase"] for phase in result["phases"]] == ["press", "release"]
    assert hardware.tones == [(440, 500)]
    assert hardware.power["C"] == 0


def test_sensor_relative_reference_returns_difference_from_captured_zero() -> None:
    hardware = FakeHardware([42])
    controller = NxtController(hardware)

    zero = controller.zero_sensor_reference(1, "light")
    hardware.sensor_values = [57]
    reading = controller.read_sensor_relative(1, "light")

    assert zero["zero_value"] == 42
    assert reading["value"] == 15
    assert reading["absolute_value"] == 57


def test_sync_drive_and_i2c_and_file_mailbox_are_bounded_controller_operations() -> None:
    hardware = FakeHardware()
    controller = NxtController(hardware)

    assert controller.drive_sync("B", "C", 40, -20)["regulated"] == "sync"
    assert hardware.sync_calls == [("B", "C", 40, -20)]
    assert controller.i2c_transaction(1, [1, 2], 2)["read_bytes"] == [2, 1]
    assert controller.write_file("log.csv", "x,y", overwrite=False)["size_bytes"] == 3
    assert controller.read_file("log.csv")["content"] == "x,y"
    controller.mailbox_send(0, "ok")
    assert controller.mailbox_receive(0)["data"] == "ok"
