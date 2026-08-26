# Robot NXT Control MCP

Local MCP server for compatible programmable-brick hardware connected to Windows 11 by USB/WinUSB.

## Compatibility and trademarks

This independent project is not affiliated with, sponsored by, or endorsed by the LEGO Group. LEGO, MINDSTORMS, and NXT are trademarks of the LEGO Group. They are used in this documentation only to identify compatible hardware, software, protocols, and third-party dependencies; they are not part of this project's name, server identifier, or plugin identifier.

### Migration from earlier releases

The old plugin and MCP-server identifier has been replaced by `robot-nxt-control`, and the
executables are now named `robot-nxt-control-mcp`, `robot-nxt-control-mcp-stdio`, and
`robot-nxt-control-mcp-http`. Reinstall the editable package after pulling this change and
replace earlier MCP configuration entries with the examples below.

## Install in Claude Desktop or Codex desktop (Windows)

Complete the [Windows installation](#windows-11-installation) first. These desktop
apps start the MCP server themselves, so do **not** run `robot-nxt-control-mcp-stdio.exe` manually.
The examples assume this repository is at `C:\Users\lukas\workspace\NXT-MCP`; replace
that part in every path if your checkout is elsewhere.

### Claude Desktop

1. Fully quit Claude Desktop (including its tray icon).
2. Open `%APPDATA%\Claude\claude_desktop_config.json`. Create the file if it does not
   exist. If it already has an `mcpServers` object, add only the `robot-nxt-control` entry below.
3. Save the file and start Claude Desktop again. The server should appear in
   **Settings → Developer → MCP servers**.

```json
{
  "mcpServers": {
    "robot-nxt-control": {
      "command": "C:\\Users\\lukas\\workspace\\NXT-MCP\\.venv\\Scripts\\robot-nxt-control-mcp-stdio.exe",
      "cwd": "C:\\Users\\lukas\\workspace\\NXT-MCP"
    }
  }
}
```

The same ready-to-copy configuration is in
[`packaging/claude-desktop/mcp.json`](packaging/claude-desktop/mcp.json).

### Codex desktop

The Codex desktop host and Codex CLI use the shared MCP configuration in
`%USERPROFILE%\.codex\config.toml`. Add this block (or run the equivalent
`codex mcp add` command below), then restart the Codex app:

```toml
[mcp_servers.robot-nxt-control]
command = "C:\\Users\\lukas\\workspace\\NXT-MCP\\.venv\\Scripts\\robot-nxt-control-mcp-stdio.exe"
cwd = "C:\\Users\\lukas\\workspace\\NXT-MCP"
startup_timeout_sec = 10
tool_timeout_sec = 120
```

PowerShell alternative:

```powershell
codex mcp add robot-nxt-control -- C:\Users\lukas\workspace\NXT-MCP\.venv\Scripts\robot-nxt-control-mcp-stdio.exe
codex mcp list
```

For the ChatGPT desktop MCP UI: **Settings → MCP servers → Add server**, choose
**STDIO**, enter `robot-nxt-control`, use the same executable as the command, save, then
restart the app. Local Codex clients support both STDIO and Streamable HTTP and share
this MCP configuration. [Official OpenAI MCP documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)

### First check

Open a new chat and ask for `nxt_info`. If it cannot connect, first confirm the robot
works with `./.venv/Scripts/nxt-test.exe --log-level=debug`; then verify that every
configured path exists and that the NXT is switched on. Movement tools control real
hardware: begin with `nxt_info` or `query_all_state`, then use low power and bounded
movement commands.

## MCP transports, hosts, and verification

The same `create_server()` factory powers both transports. `robot-nxt-control-mcp-stdio` is the
local-process transport for Claude Desktop, Claude Code, Codex CLI, Codex desktop,
and local Codex plugins. It writes protocol traffic only to stdout.

Use the supplied JSON as a starting configuration, replacing the absolute workspace
path after moving the checkout:

- Claude Desktop: `packaging/claude-desktop/mcp.json`
- Claude Code plugin: `packaging/claude-code/`
- Codex local plugin: `C:\Users\lukas\plugins\robot-nxt-control` (created in the personal marketplace)

For protocol testing, start Streamable HTTP on loopback:

```powershell
.\.venv\Scripts\robot-nxt-control-mcp-http.exe --port 8000
npx @modelcontextprotocol/inspector --cli http://127.0.0.1:8000/mcp --method tools/list
npx @modelcontextprotocol/conformance server --url http://127.0.0.1:8000/mcp --suite active
```

Run the repository checks with `.\.venv\Scripts\python.exe -m pytest`. They include an
in-process MCP negotiation, `tools/list`, annotations, and `tools/call` test, in
addition to controller and behavior tests. `conformance-baseline.yml` records only
generic scenarios requiring optional MCP features this focused hardware server does
not advertise; each entry is a burn-down assertion, so the runner flags stale entries.

`robot-nxt-control-mcp-http` binds to `127.0.0.1` by default and refuses non-loopback binding unless
`NXT_MCP_ALLOW_REMOTE=true` is explicitly set. A cloud client cannot reach a USB NXT
directly: run this server next to the robot and place a production HTTPS reverse proxy
with OAuth/token validation, authorization, audit logs, and network restrictions in
front of the Streamable HTTP endpoint. Never expose the USB-control endpoint publicly
with only the environment override.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the module design, MCP and behavior execution
flows, USB stack, safety model, and Mermaid diagrams.

## Windows 11 installation

Use Python 3.11 x64. From PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
```

### 1. Install the NXT device driver with Zadig

Turn the NXT on and connect it by USB. In PowerShell, confirm that Windows sees the
normal-mode device:

```powershell
Get-PnpDevice -PresentOnly |
  Where-Object InstanceId -match 'VID_0694&PID_0002' |
  Format-List Status,FriendlyName,InstanceId,Problem
```

The hardware ID must contain `USB\VID_0694&PID_0002`. If `Problem` is
`CM_PROB_FAILED_INSTALL` or Device Manager shows Code 28, the driver is missing.

1. Download Zadig only from <https://zadig.akeo.ie/>.
2. Run Zadig as Administrator.
3. Select **Options > List All Devices**.
4. Select the entry whose USB ID is exactly `0694:0002`. Use the ID, not only the
   displayed device name.
5. Choose **WinUSB** in the driver selector.
6. Click **Install Driver** or **Replace Driver**.
7. Disconnect and reconnect the NXT, leaving it switched on.

Do not select `03EB:6124`; that is the NXT bootloader/firmware-update mode. Do not
replace drivers for any unrelated USB device. Installing WinUSB may prevent the old
LEGO NXT-G software from talking to the brick until its LEGO/Fantom driver is restored.

### 2. Install the x64 libusb runtime for PyUSB

WinUSB is the Windows device driver. PyUSB separately needs the user-space
`libusb-1.0.dll`. The repository includes a helper that downloads the official libusb
1.0.30 archive, verifies its SHA-256, and installs the VS2022 x64 DLL beside this
environment's `python.exe`:

```powershell
.\scripts\install-libusb-runtime.ps1
```

The helper requires `7z.exe` on `PATH`. To install manually, download
`libusb-1.0.30.7z` from the official libusb GitHub release, extract
`VS2022\MS64\dll\libusb-1.0.dll`, and copy it to `.venv\Scripts\libusb-1.0.dll`.
Do not use an `MS32` DLL with 64-bit Python.

Verify the runtime independently:

```powershell
$env:PATH = "$PWD\.venv\Scripts;$env:PATH"
.\.venv\Scripts\python.exe -c "import usb.backend.libusb1 as b; assert b.get_backend() is not None; print('libusb OK')"
```

The MCP server automatically adds a DLL installed beside its virtual-environment Python
to its own search path. `nxt-test.exe` is an external NXT-Python command, so either run
the `$env:PATH` line above first or activate the virtual environment before using it.

### 3. Test the brick

Verify the hardware before MCP:

```powershell
.\.venv\Scripts\nxt-test.exe --log-level=debug
```

A successful test prints the brick name, battery level, protocol version, and firmware
version. If it still reports no brick, recheck the `0694:0002` device in Device Manager
and confirm that its driver is WinUSB.

### Firmware

No firmware installation or update is needed when the NXT boots normally and Windows
shows `VID 0694 / PID 0002`. The MCP server uses standard NXT direct commands and also
reports the installed firmware and protocol versions through `nxt_info`.

Only perform firmware recovery if the brick cannot boot normally and Windows instead
shows `VID 03EB / PID 6124`, which is Atmel SAM-BA firmware-update mode. Recovery erases
and rewrites brick firmware and is outside the normal MCP setup:

1. Do not install the normal NXT WinUSB rule against `03EB:6124`.
2. Restore/use the firmware-update driver required by the original LEGO MINDSTORMS NXT
   software.
3. In that software, use **Tools > Update NXT Firmware** with an official NXT firmware
   image.
4. After recovery, power-cycle the brick. It must return as `0694:0002`; then install
   WinUSB for that normal-mode device again if necessary.

NXT-Python deliberately does not provide firmware flashing. Do not invoke firmware boot
mode or attempt an update merely to troubleshoot `NoBackendError`, Code 28, or an MCP
connection failure.

Then open the MCP Inspector:

```powershell
.\.venv\Scripts\mcp.exe dev src\nxt_mcp\server.py
```

For a local MCP host, configure a stdio server with command
`.venv\Scripts\robot-nxt-control-mcp.exe` and the repository as its working directory.

Declare the sensors attached to the brick before starting the server so the whole-brick
snapshot can return typed readings immediately:

```powershell
$env:NXT_SENSOR_MAP = "1:touch,2:light,4:ultrasonic"
.\.venv\Scripts\robot-nxt-control-mcp.exe
```

Calling `read_sensor` or a sensor-driven motor command also remembers that port's type
for later snapshots.

## High-level tools

- `move_motor_relative(port="C", power=40, degrees=2000)` moves C forward by 2000
  encoder degrees. Use negative power for the opposite direction. The adapter uses a
  tight USB encoder loop because NXT-Python's standard `turn()` loop polls too slowly
  for small movements. Use lower power, such as 20, for movements around 45 degrees.
- `zero_motor_position(port="C")` defines the current C encoder position as absolute 0.
  `move_motor_absolute(port="C", target_degrees=-90, power=20)` then moves to -90.
  Absolute movement derives direction from the target; its `power` is a positive
  magnitude.
- `motor_position(port="C")` reports the absolute/program-relative encoder position and
  the raw tacho counters.
- `run_motor(port="C", power=-30)` runs continuously in the negative direction until a
  stop command or a bounded behavior stops it. With `regulated=true`, `power` is the NXT
  regulated speed setting, not a calibrated degrees-per-second value.
- `run_motors(ports=["B", "C"], powers=[30, -30])` starts a motor group in one MCP call.
  `stop_motors`, `move_motors_relative`, and `move_motors_absolute` operate on groups in
  the same way. Lists are positional: each power/degree value belongs to the port at the
  same index.
- `run_motor_until_sensor(port="B", power=40, sensor_port=1,
  sensor_type="touch", condition="pressed")` runs B until touch S1 is pressed.
- `run_motors_until_sensor(ports=["B", "C"], powers=[40, 40], sensor_port=4,
  sensor_type="ultrasonic", condition="lte", threshold=20)` drives both motors until an
  obstacle is at most 20 cm away, then stops the entire group.
- `run_motor_until_sensor(port="B", power=40, sensor_port=4,
  sensor_type="ultrasonic", condition="lte", threshold=20)` runs B until an
  obstacle is at most 20 cm away.
- `query_all_state(format="text")` returns one compact text snapshot of the brick,
  all motor ports, and all sensor ports. Use `format="json"` for structured data.
- `cycle_motor_on_touch(port="C", touch_port=1, cycles=5)` runs forward until S1 is
  pressed, reverses until it is released, repeats five times, and beeps after success.
  Every press and release phase has its own timeout and encoder-travel ceiling.

Every sensor-driven motion has a timeout and an encoder travel limit. Reaching either
limit stops the motor and returns `ok: false` with the reason. The motor is also stopped
if a sensor or USB read fails.

### Extended diagnostics, storage, and telemetry

- `motor_state(port)` reports regulation, run state, tachos, and configured output state.
  `drive_sync(left_port, right_port, power, turn_ratio=0)` uses NXT firmware sync
  regulation for a differential-drive pair; `wait_motors(...)` has a deadline and stops
  its ports on timeout.
- `read_sensor_raw(port, sensor_type?)`, `wait_sensor(...)`, and `sensor_stream(...)`
  expose bounded diagnostics, debounced sensor waits, and finite samples.
- For light, color, and ultrasonic sensors, call
  `zero_sensor_reference(port, sensor_type)` then
  `read_sensor_relative(port, sensor_type)`. It returns the change from the captured
  zero plus the absolute value. Color uses reflected-light intensity (not the discrete
  red/blue/etc. label) for meaningful subtraction.
- `log_start`, `log_status`, `log_stop`, and `log_export` provide bounded host-side CSV
  telemetry. Valid channels are `battery_mv`, `motor:A` through `motor:C`, and
  `sensor:1:touch` (or another supported sensor type/port).
- `list_files`, `read_file`, `write_file`, and `delete_file` manage bounded NXT user
  files. Writes are limited to `.txt`, `.csv`, `.dat`, and `.rso`; sound playback uses
  `play_sound_file(name)` and `stop_sound()`.
- `mailbox_send` / `mailbox_receive` support messages up to 58 UTF-8 bytes;
  `i2c_transaction` is an opt-in low-speed operation limited to 16-byte request and
  response payloads. `set_brick_name` and `keep_alive` are the supported administrative
  direct commands.

The stock NXT direct-command protocol cannot draw on the NXT LCD or read its buttons.
Those NXT-G/ROBOTC features require a separately installed NXT-resident bridge program;
they are intentionally not exposed by this server.

### Motor positioning semantics

NXT encoder counts are degrees at the motor shaft, not degrees of robot heading or linear
millimetres. Gear ratios, wheel circumference, and wheel slip must be handled by a robot
behavior if physical units are needed.

Absolute zero is held by the NXT firmware's program-relative rotation counter. It is not
a homing sensor and is not persistent: power cycling the brick or starting/stopping an
`.rxe` program invalidates the reference. Home against a touch sensor and call
`zero_motor_position` again before relying on absolute targets.

Group commands start motors using consecutive USB packets within one controller lock.
They avoid MCP/LLM round-trip skew and monitor all encoders together, but they are not
hard real-time or mechanically phase-locked. For a two-wheel robot this is appropriate
for ordinary driving; precision synchronization may require an NXT-resident control
program.

## Hardware reporting limitation

The NXT firmware reports the configured state of every port, but it cannot safely tell
whether an idle motor is physically plugged in. The whole-brick query therefore reports
all A/B/C firmware states rather than claiming motor presence. Sensor ports that have
already been configured by `read_sensor` or a sensor-driven command show typed values;
other sensor ports show their raw firmware state. Querying raw state does not reconfigure
ports or briefly energize hardware.

Do not use direct MCP motor commands while an `.rxe` program is controlling the same ports.

## PC-side Python behaviors through MCP

The stock NXT does not run Python. This server can instead save and run restricted Python
behaviors on the PC; every robot operation still crosses the controller seam, so scripts
do not open USB, instantiate NXT-Python sensors, or implement their own polling loops.

Example behavior:

```python
def run(robot):
    robot.configure_sensor(1, "touch")

    for _ in range(5):
        robot.motor_until("C", 20, 1, "pressed")
        robot.motor_until("C", -20, 1, "released")

    robot.play_tone(440, 500)
    return "completed 5 touch cycles"
```

The same example is included as `behaviors/touch_cycle.py`. Use these MCP tools:

```text
validate_behavior(source)
submit_behavior(name, source)
list_behaviors()
get_behavior(name)
run_behavior(name, timeout_seconds=120)
```

The script-visible `robot` interface contains:

```text
configure_sensor(port, sensor_type)
read_sensor(port, sensor_type)
read_sensor_raw(port, sensor_type=None)
zero_sensor_reference(port, sensor_type)
read_sensor_relative(port, sensor_type)
wait_sensor(port, sensor_type, condition, ...)
sensor_stream(port, sensor_type, ...)
log_start(channels, interval_ms=100, duration_seconds=10)
log_status(job_id)
log_stop(job_id)
log_export(job_id)
motor_until(port, power, sensor_port, condition, sensor_type="touch", ...)
motor_for_ticks(port, power, ticks, ...)
motor_position(port)
zero_motor_position(port)
motor_to(port, target_degrees, power=20, ...)
run_motor(port, power, regulated=True)
drive_sync(left_port, right_port, power, turn_ratio=0)
wait_motors(ports, ...)
stop_motor(port, brake=False)
run_motors(ports, powers, regulated=True)
stop_motors(ports, brake=False)
motors_relative(ports, powers, degrees, ...)
motors_absolute(ports, powers, target_degrees, ...)
motors_until(ports, powers, sensor_port, condition, ...)
state(format="text")
play_tone(frequency_hz=440, duration_ms=500)
play_sound_file(name, loop=False)
stop_sound()
sleep(seconds)
```

Imports, classes, exception handling, access to private attributes, and calls outside the
documented robot methods and basic built-ins are rejected. Scripts are limited to 64 KiB,
only one may run at a time, and `run_behavior` accepts a 1–300 second deadline. All motors
are stopped when a script finishes or raises an exception.

This validation is intended to prevent accidental access outside the robot interface; it
is not a security sandbox for hostile code. Only grant MCP access to trusted local users.
Set `NXT_BEHAVIOR_DIR` before starting the server to store behaviors somewhere other than
the default `behaviors` directory under the server working directory.

For a command-line demonstration that still uses MCP stdio rather than importing the
controller directly:

```powershell
.\.venv\Scripts\python.exe scripts\mcp-behavior-client.py list
.\.venv\Scripts\python.exe scripts\mcp-behavior-client.py submit touch_cycle behaviors\touch_cycle.py
.\.venv\Scripts\python.exe scripts\mcp-behavior-client.py run touch_cycle --timeout 120
```

The final command performs physical movement. The client only calls MCP tools; the MCP
server loads the behavior and owns all NXT communication.

## Test without a brick

```powershell
$env:PYTHONPATH = "src"
py -3.11 -m pytest
```
