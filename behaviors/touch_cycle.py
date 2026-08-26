def run(robot):
    robot.configure_sensor(1, "touch")

    for _ in range(5):
        robot.motor_until("C", 20, 1, "pressed")
        robot.motor_until("C", -20, 1, "released")

    robot.play_tone(440, 500)
    return "completed 5 touch cycles"
