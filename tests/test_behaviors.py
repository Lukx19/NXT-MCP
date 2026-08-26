from __future__ import annotations

import asyncio
import json

import pytest
from mcp import Client

from nxt_mcp.behaviors import BehaviorRunner, BehaviorTimeoutError, BehaviorValidationError


class RecordingController:
    def __init__(self) -> None:
        self.calls = []
        self.stopped = False

    def read_sensor(self, port, sensor_type):
        result = {"port": port, "sensor_type": sensor_type, "value": False}
        self.calls.append(("sensor", port, sensor_type))
        return result

    def run_motor_until_sensor(self, port, power, sensor_port, sensor_type, condition, threshold, **kwargs):
        self.calls.append(("until", port, power, sensor_port, sensor_type, condition))
        return {"ok": True, "reason": "sensor_reached", "travelled_ticks": 10}

    def run_motor_for_ticks(self, port, power, ticks, brake, timeout_seconds):
        self.calls.append(("ticks", port, power, ticks))
        return {"ok": True, "travelled_ticks": ticks}

    def run_motor(self, port, power, regulated):
        self.calls.append(("run", port, power))
        return {"ok": True}

    def stop_motor(self, port, brake):
        self.calls.append(("stop", port, brake))
        return {"ok": True}

    def state(self, text=True):
        return "state" if text else {"state": "ok"}

    def play_tone(self, frequency_hz, duration_ms):
        self.calls.append(("tone", frequency_hz, duration_ms))
        return {"ok": True}

    def emergency_stop(self):
        self.stopped = True
        return {"ok": True}


FIVE_CYCLES = '''def run(robot):
    robot.configure_sensor(1, "touch")
    for _ in range(5):
        robot.motor_until("C", 20, 1, "pressed")
        robot.motor_until("C", -20, 1, "released")
    robot.play_tone(440, 500)
    return "complete"
'''


def test_submit_and_run_composed_behavior(tmp_path) -> None:
    controller = RecordingController()
    runner = BehaviorRunner(tmp_path, controller)

    submitted = runner.submit("touch_cycle", FIVE_CYCLES)
    result = runner.run("touch_cycle")

    assert submitted["valid"] is True
    assert runner.list() == {"behaviors": ["touch_cycle"]}
    assert result["result"] == "complete"
    assert len([call for call in controller.calls if call[0] == "until"]) == 10
    assert controller.calls[-1] == ("tone", 440, 500)
    assert controller.stopped is True


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("import os\ndef run(robot): pass", "Import is not allowed"),
        ("def run(robot):\n    robot.__class__", "only documented robot methods"),
        ("def nope(robot): pass", "must define run"),
    ],
)
def test_validation_rejects_unsafe_or_invalid_source(source, message) -> None:
    runner = BehaviorRunner.__new__(BehaviorRunner)
    with pytest.raises(BehaviorValidationError, match=message):
        runner.validate(source)


def test_timeout_stops_motors(tmp_path) -> None:
    controller = RecordingController()
    runner = BehaviorRunner(tmp_path, controller)
    runner.submit("forever", "def run(robot):\n    while True:\n        pass\n")

    with pytest.raises(BehaviorTimeoutError):
        runner.run("forever", timeout_seconds=1)

    assert controller.stopped is True


def test_validation_is_callable_over_mcp_protocol() -> None:
    from nxt_mcp.server import create_server

    mcp = create_server(behavior_dir=None)

    async def call() -> None:
        async with Client(mcp) as client:
            result = await client.call_tool("validate_behavior", {"source": FIVE_CYCLES})
            assert result.is_error is False
            assert json.loads(result.content[0].text)["valid"] is True

    asyncio.run(call())
