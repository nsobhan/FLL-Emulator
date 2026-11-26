"""Sample SPIKE App 3 Python programs for trying the simulator without the app."""

EXAMPLES = {
    "camp3": {
        "name": "Camp 3: Follow the line", "mat": "camp3follow",
        "source": '''from hub import port
import motor_pair, color_sensor, runloop

async def main():
    # Driving Base: drive C (left) + D (right), color sensor on B
    motor_pair.pair(motor_pair.PAIR_1, port.C, port.D)
    while True:
        if color_sensor.reflection(port.B) < 50:        # on black: turn one way
            motor_pair.move(motor_pair.PAIR_1, 50, velocity=333)
        else:                                            # on white: turn the other way
            motor_pair.move(motor_pair.PAIR_1, -50, velocity=333)
        await runloop.sleep_ms(10)

runloop.run(main())
''',
    },
    "relay": {
        "name": "Camp 2: Relay race", "mat": "relay",
        "source": '''from hub import port
import motor, motor_pair, distance_sensor, runloop

async def main():
    # Practice Driving Base: drive C (left) + D (right), arm on E, distance sensor on F
    motor_pair.pair(motor_pair.PAIR_1, port.C, port.D)
    for baton in range(4):
        motor_pair.move(motor_pair.PAIR_1, 0, velocity=333)
        while distance_sensor.distance(port.F) == -1 or distance_sensor.distance(port.F) > 80:  # mm
            await runloop.sleep_ms(10)
        motor_pair.stop(motor_pair.PAIR_1)
        await motor.run_for_degrees(port.E, 90, 832)          # lower the arm
        await motor_pair.move_for_degrees(motor_pair.PAIR_1, -450, 0, velocity=333)  # back 22 cm
        await motor.run_for_degrees(port.E, -90, 832)         # raise the arm, let go
        print("baton", baton + 1, "home")
        await runloop.sleep_ms(1000)

runloop.run(main())
''',
    },
    "camp1": {
        "name": "Camp 1: Drive a square", "mat": "camp1",
        "source": '''from hub import port
import motor_pair, runloop

async def main():
    # Practice Driving Base: drive motors on C (left) and D (right)
    motor_pair.pair(motor_pair.PAIR_1, port.C, port.D)
    for side in range(4):
        # 40 cm = 40 / 17.6 x 360 = about 819 wheel degrees
        await motor_pair.move_for_degrees(motor_pair.PAIR_1, 819, 0, velocity=555)
        # turn left 90 degrees: steering -100 for half a rotation
        await motor_pair.move_for_degrees(motor_pair.PAIR_1, 180, -100, velocity=555)
        print("side", side + 1, "done")

runloop.run(main())
''',
    },
    "square": {
        "name": "Drive a square", "mat": "playground",
        "source": '''from hub import port, light_matrix, sound
import motor_pair, runloop

async def main():
    motor_pair.pair(motor_pair.PAIR_1, port.A, port.B)
    light_matrix.show_image(light_matrix.IMAGE_HAPPY)
    for side in range(4):
        await motor_pair.move_for_degrees(motor_pair.PAIR_1, 720, 0, velocity=500)
        await motor_pair.move_for_degrees(motor_pair.PAIR_1, 180, 100, velocity=300)
        print("side", side + 1, "done")
    await sound.beep(660, 300)
    await light_matrix.write("Done")

runloop.run(main())
''',
    },
    "wall": {
        "name": "Stop before the wall", "mat": "playground",
        "source": '''from hub import port, light_matrix
import motor_pair, distance_sensor, runloop

async def main():
    motor_pair.pair(motor_pair.PAIR_1, port.A, port.B)
    # turn to face the wall on the right
    await motor_pair.move_for_degrees(motor_pair.PAIR_1, 180, 100, velocity=300)
    motor_pair.move(motor_pair.PAIR_1, 0, velocity=600)
    while True:
        d = distance_sensor.distance(port.D)
        if 0 < d < 100:
            break
        await runloop.sleep_ms(20)
    motor_pair.stop(motor_pair.PAIR_1)
    print("Stopped", distance_sensor.distance(port.D), "mm from the wall")
    light_matrix.show_image(light_matrix.IMAGE_YES)

runloop.run(main())
''',
    },
    "line": {
        "name": "Follow the line", "mat": "line",
        "source": '''from hub import port, light_matrix
import motor_pair, color_sensor, color, runloop

async def main():
    motor_pair.pair(motor_pair.PAIR_1, port.A, port.B)
    light_matrix.show_image(light_matrix.IMAGE_ARROW_N)
    while color_sensor.color(port.C) != color.RED:
        # follow the left edge of the black line
        error = color_sensor.reflection(port.C) - 50
        motor_pair.move(motor_pair.PAIR_1, int(error * 1.5), velocity=350)
        await runloop.sleep_ms(10)
    motor_pair.stop(motor_pair.PAIR_1)
    await light_matrix.write("Red!")

runloop.run(main())
''',
    },
    "colors": {
        "name": "Say the colors", "mat": "playground",
        "source": '''from hub import port, light_matrix, light
import motor_pair, color_sensor, color, runloop

NAMES = {color.RED: "red", color.BLUE: "blue", color.GREEN: "green",
         color.YELLOW: "yellow", color.WHITE: "white", color.BLACK: "black"}

async def main():
    motor_pair.pair(motor_pair.PAIR_1, port.A, port.B)
    last = None
    motor_pair.move(motor_pair.PAIR_1, 0, velocity=300)
    for _ in range(450):
        c = color_sensor.color(port.C)
        if c != last:
            print("I see", NAMES.get(c, c))
            light.color(light.POWER, c)
            last = c
        await runloop.sleep_ms(20)
    motor_pair.stop(motor_pair.PAIR_1)

runloop.run(main())
''',
    },
}
