def run(robot):
    robot.configure_sensor(1, "touch")
    robot.configure_sensor(2, "ultrasonic")

    while True:
        touch = robot.read_sensor(1, "touch")
        if touch["value"]:
            robot.stop_motors(("A", "B", "C"), brake=True)
            return "stopped by touch sensor"

        ultrasonic = robot.read_sensor(2, "ultrasonic")
        distance = ultrasonic["value"]
        if distance < 9:
            robot.run_motors(("A", "B", "C"), (100, 100, 100))
        elif distance > 11:
            robot.run_motors(("A", "B", "C"), (-100, -100, -100))
        else:
            robot.stop_motors(("A", "B", "C"), brake=True)

        robot.sleep(0.1)
