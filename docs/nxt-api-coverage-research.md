# NXT API coverage research

Date: 2026-08-26. This note compares the existing behavior-facing surface with
the capabilities exposed by the original vendor's graphical NXT programming model and
the official ROBOTC API. It is a capability study, not a proposal to run
arbitrary ROBOTC code or replace the safety boundary.

LEGO, MINDSTORMS, and NXT are trademarks of the LEGO Group. This independent project
uses those names only where needed to identify a cited source, compatible hardware,
protocol, software, or dependency; it is not affiliated with, sponsored by, or
endorsed by the LEGO Group.

## Sources and scope

* The vendor's [NXT software guide](https://www.lego.com/cdn/product-assets/product.bi.core.pdf/4520736.pdf)
  describes the NXT-G palette, configurable blocks, the standard ports, and
  its program/file UI. The vendor also publishes the final NXT software as v2.1f6,
  and says that it is no longer updated or officially supported on modern
  systems ([support article](https://www.lego.com/en-us/service/help-topics/article/all-about-lego-mindstorms-nxt?age-gate=grown_up&opt-out-modal=show)).
* The official [ROBOTC function index](https://www.robotc.net/WebHelpMindstorms/Content/Resources/topics/test_TOCProxy.htm)
  is the primary inventory for NXT APIs. Its NXT entries cover motor control,
  raw/scaled sensor access, sound, display drawing, buttons, tasks/timers,
  Bluetooth, and datalogging.
* The vendor's later [EV3 block taxonomy](https://ev3-help-online.api.education.lego.com/Education/en-gb/index.html)
  is used only as a coverage benchmark for NXT-compatible components. It must
  not be read as evidence that every EV3 block or feature is supported by an
  NXT brick; the vendor documents those compatibility limits
  [separately](https://education.lego.com/en-gb/product-resources/mindstorms-ev3/teacher-resources/nxt-compatibility/).

The current project already covers: continuous and encoder-bounded motor
motion, independent motor groups, brake/float stopping, encoder state/reset,
the standard touch/light/sound/ultrasonic/color/temperature sensors, polling
until a sensor condition, snapshots, program start/stop/status, tone playback,
and safe local behaviors. The dependency's `Brick` API also already exposes
several NXT direct commands that the project does not yet wrap (files,
mailboxes, sound files, low-speed/I2C, keep-alive and brick renaming).

## Critical execution-model constraint

This server controls *stock firmware* through NXT direct and system commands;
it does not run an NXT-G or ROBOTC runtime on the brick. NXT-Python's `Brick`
direct-command surface, which is the project's transport dependency, has no LCD
drawing or brick-button-read command. Consequently, ROBOTC's
display/buttons/timers/tasks APIs and NXT-G's Display block are not directly
implementable as new calls in this server. They work because an NXT-resident
program/runtime owns the LCD and buttons. Display and buttons need either a
separately installed NXT-resident bridge program with a deliberately specified
mailbox protocol, or a different firmware/runtime; they must not be advertised
as stock-direct-command APIs.

## What NXT-G and ROBOTC add conceptually

| Area | Useful reference capabilities | MCP implication |
| --- | --- | --- |
| Motors | NXT-G's Move/Motor blocks; ROBOTC targets, absolute positions, encoder reset, regulated/unregulated operation, synchronization, brake mode, running/RPM state, and `waitUntilMotorStop`. ROBOTC documents [relative targeting](https://www.robotc.net/WebHelpMindstorms/Content/Resources/topics/LEGO_NXT/Natural_Language/Motor_Commands/moveMotorTarget.htm) and [absolute targeting](https://www.robotc.net/WebHelpMindstorms/Content/Resources/topics/LEGO_NXT/Natural_Language/Motor_Commands/setMotorTarget.htm). | Expose the remaining *observable* motor state and an explicit safe paired-drive primitive. Do not expose a raw PWM command as the default. |
| Sensors | NXT-G uses touch, light/color, sound and ultrasonic conditions; ROBOTC exposes sensor type/mode, raw, normalized and scaled values. | Preserve typed high-level reads, but add a controlled diagnostic/raw read and event-style waits/streams. This makes calibration and line following practical. |
| Brick UI | ROBOTC lists text (normal/large/centered/inverse), pixels, lines, rectangles, ellipses, bitmap drawing and screen clearing; it also lists button read/wait APIs. | Valuable, but not in the stock direct-command surface. Offer it only through an explicitly installed, versioned on-brick bridge protocol. |
| Sound | NXT-G has sound output; ROBOTC lists volume, tones, sound files, queue status and stop/clear sound. | Keep `play_tone`; add file playback, volume and stop only after validating the file name and ranges. |
| Timing/control | NXT-G supplies Wait, Loop, Switch and Stop; ROBOTC lists timers plus task start/stop/priority. | Behaviors already provide Python control flow. Add cancellable scheduled jobs and timer/elapsed-time helpers; avoid general task priorities or CPU-hogging primitives. |
| Files/communications | NXT-G supports brick program/file operations and messaging. ROBOTC has Bluetooth state/configuration and file transfer; its [Bluetooth reference](https://www.robotc.net/WebHelpArduino/scr/NXT_Functions_New/NXT_Functions_Bluetooth.htm) documents connect/disconnect, mailbox messages, raw-mode caveats and NXT-to-NXT file transfer. | Add host-to-brick file management and mailbox messaging first. Treat pairing, PIN mutation, raw Bluetooth, and factory reset as separately authorized administrative operations. |
| Data logging | ROBOTC lists `datalogAddValue`, timestamped writes, grouping, clearing and polling pause/resume. | Add a host-managed sampling/logging job and export rather than depending on an IDE debugger window. |

## Recommended additions

### Priority 1 — safe, high-value primitives

1. `nxt_motor_state(port)` / enrich the existing state result with `speed`,
   `running`, `brake_mode`, regulation mode and target. This makes behavior
   decisions based on evidence rather than elapsed time.
2. `nxt_drive_sync(left_port, right_port, power, turn_ratio=0, ...)` and
   `nxt_motor_wait(port|ports, timeout_seconds)`. Design it as an encoder- and
   timeout-bounded operation which always stops its motors on cancellation.
3. `nxt_sensor_read_raw(port)` and `nxt_sensor_wait(port, sensor_type,
   condition, threshold, debounce_ms, timeout_seconds)`. Return raw,
   normalized and scaled values with the configured type/mode, rather than an
   unlabelled number. A later `nxt_sensor_stream` should be a bounded job
   (`sample_interval_ms`, `duration`, `max_samples`) with cancellation.
4. `nxt_sound_play_file(name, loop=false)`, `nxt_sound_stop()`, and
   `nxt_sound_set_volume(percent)`. These complement the existing tone API;
   restrict `name` to a brick file basename.

### Priority 2 — workflow and observability

5. `nxt_file_list(pattern="*.*")`, `nxt_file_read(name, max_bytes)`,
   `nxt_file_write(name, content, overwrite=false)`, and `nxt_file_delete(name)`.
   Put uploads/downloads behind byte and extension allow-lists; never expose a
   bulk flash erase as a normal MCP tool.
6. `nxt_mailbox_send(inbox, data)` / `nxt_mailbox_receive(inbox)` for NXT
   messaging, plus read-only `nxt_bluetooth_status()`. ROBOTC documents
   messages of at most 58 bytes for one lower-level Bluetooth write, a useful
   conservative bound for an initial MCP design.
7. `nxt_log_start(channels, interval_ms, duration_seconds)`,
   `nxt_log_status(job_id)`, `nxt_log_stop(job_id)`, and
   `nxt_log_export(job_id, format="csv")`. Channels should be declarative
   (motor encoder/state, configured sensor reading, battery), with maximum
   duration/sample count. Store log data on the host by default; optionally
   use brick files only through the file APIs above.
8. `nxt_i2c_transaction(port, write_bytes, read_length, timeout_seconds)`
   as an advanced opt-in tool. This enables validated drivers for documented
   third-party sensors while keeping raw bus traffic out of ordinary behavior
   scripts.

### Priority 3 — only with explicit safeguards

9. `nxt_brick_set_name(name)`, `nxt_keep_alive()`, and administrative
    Bluetooth visibility/connect/disconnect tools. The ROBOTC documentation
    shows why raw Bluetooth mode is distinct: it disables the normal vendor
    protocol and can only be exited when the program ends. Do **not** make raw
    Bluetooth, PIN persistence, contact deletion, Bluetooth factory reset,
    firmware flashing, or user-flash erase routine behavior APIs.

## Behavior API shape

The safe behavior façade should receive a compact subset, for example
`robot.read_sensor_raw`, `robot.wait_sensor`, `robot.drive_sync`,
`robot.log_samples`, and `robot.play_sound_file`. Each blocking API needs a
timeout; each movement or sampling job needs a cancellation path; and behavior
finalization must retain the present emergency stop. `robot.display_text` and
`robot.wait_button` become possible only when an optional on-brick bridge is
present and its version/capabilities have been detected. This matches the
useful NXT-G blocks (action, sensor, flow, data and advanced) without allowing
a stored behavior to alter firmware, pairing credentials or the host
filesystem.

## Suggested delivery order

Implement raw sensor metadata first, then bounded sensor/log jobs and safe
synchronized drive. Follow with brick file and mailbox support. Treat a
display/button bridge as a separate compatibility project. Hardware-facing
integration tests should verify stop-on-error, timeout/cancellation, value
units, and malformed file/message/I2C input; unit tests can cover the
controller and behavior validation without a brick.
