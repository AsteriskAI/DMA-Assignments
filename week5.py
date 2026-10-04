"""
Week 5 Sensor Assignment

OVERVIEW:
A 1D LED strip game. The player (blue pixel) slides along the strip with the
potentiometer. Enemies (red pixels) spawn at both ends and crawl toward you.
Cover the photocell to attack: a yellow blast hits the 2 pixels in front of
you (the direction you last moved). Kill enemies to win, you have 3 lives, if enemies touch you
touch you, you lose a life, 3 lives lost and you're out.

  Potentiometer -> move player
  Photocell     -> attack (covered = light value below 0.5)
  LED strip     -> game display
  Piezo         -> kill blip, hit buzz, win jingle (high), lose sound (low)
  Servo         -> progress gauge: arm sweeps 0 -> 180 as kills approach goal

WIRING
  Potentiometer: outer legs to 3V and GND, middle to A1
  Photocell: one leg to 3V, other leg to A0; 10k resistor from A0 to GND
  NeoPixel strip: 5V to power, GND to GND, data to D6
  Piezo: one leg to D9, other leg to GND
  Servo: plug into the Prop-Maker servo header
"""

import time
import random
import board
import analogio
import pwmio
import neopixel
from digitalio import DigitalInOut, Direction
from adafruit_motor import servo

# game settings
NUM_PIXELS = 35        # length of the strip
ATTACK_RANGE = 2       # pixels the attack reaches
ATTACK_LEVEL = 0.5     # photocell below this = covered = attack
ATTACK_COOLDOWN = 0.5  # seconds between attacks
WIN_KILLS = 10         # kills needed to win
START_LIVES = 3
POT_MIN = 2000    # lowest reading
POT_MAX = 63000   # highest reading

# power for the servo header
ext_power = DigitalInOut(board.EXTERNAL_POWER)
ext_power.direction = Direction.OUTPUT
ext_power.value = True

# Pins for the potentiometer and photocell
pot = analogio.AnalogIn(board.A1)
photo = analogio.AnalogIn(board.A0)

# Neopixel initialization (auto write false so the next frame is shown when its ready)
pixels = neopixel.NeoPixel(board.D6, NUM_PIXELS, brightness=0.3, auto_write=False)

# Piezo initalization, start the scene with it turned off
piezo = pwmio.PWMOut(board.D9, frequency=440, duty_cycle=0, variable_frequency=True)

# micro servo initiailization
pwm = pwmio.PWMOut(board.EXTERNAL_SERVO, frequency=50)
gauge = servo.Servo(pwm)


last_good = 0.5

def read_pot():
    global last_good
    # raw value
    raw = pot.value
    # If the reading goes above our min or max by too much ignore value
    if raw < POT_MIN - 1500 or raw > POT_MAX + 1500:
        return last_good
    # Normalization of value
    val = (min(max(raw, POT_MIN), POT_MAX) - POT_MIN) / (POT_MAX - POT_MIN)
    last_good = val
    return val

def tone(freq, dur):
    # play a short beep on the piezzo
    piezo.frequency = freq
    piezo.duty_cycle = 2 ** 15
    time.sleep(dur)
    piezo.duty_cycle = 0


def read_norm(pin):
    # Analog reading scaled to 0.0 - 1.0
    return pin.value / 65535


def flash(color, times=3):
    # Flash the whole strip
    for _ in range(times):
        pixels.fill(color)
        pixels.show()
        time.sleep(0.1)
        pixels.fill((0, 0, 0))
        pixels.show()
        time.sleep(0.1)


def win():
    gauge.angle = 180
    for f in (523, 659, 784, 1047):   # rising jingle
        tone(f, 0.12)
    flash((0, 255, 0), 4)


def lose():
    gauge.angle = 0
    for f in (330, 262, 196, 147):    # falling low sound
        tone(f, 0.25)
    flash((255, 0, 0), 4)


def new_game():
    gauge.angle = 0
    return {
        "player": NUM_PIXELS // 2, "facing": 1, "enemies": [],
        "lives": START_LIVES, "kills": 0,
        "last_step": time.monotonic(), "last_spawn": time.monotonic(),
        "last_attack": 0, "blast_until": 0, "blast": [],
    }


#main game, store function values in a variable
game = new_game()

while True:
    now = time.monotonic()

    # move player with the pot, remember which way we last moved
    new_pos = min(int(read_pot() * NUM_PIXELS), NUM_PIXELS - 1)
    if new_pos > game["player"]:
        game["facing"] = 1
    elif new_pos < game["player"]:
        game["facing"] = -1
    game["player"] = new_pos

    # Attack when photocell is covered
    if read_norm(photo) < ATTACK_LEVEL and now - game["last_attack"] > ATTACK_COOLDOWN:
        game["last_attack"] = now
        game["blast_until"] = now + 0.15
        # Blast the pixels depending where the player is and which direction they're facing
        game["blast"] = [game["player"] + game["facing"] * i for i in range(1, ATTACK_RANGE + 1)]
        # Make a copy to loop through while we edit the array
        for enemy in game["enemies"].copy():
            if enemy in game["blast"]:
                game["enemies"].remove(enemy)
                game["kills"] += 1
                gauge.angle = min(180, game["kills"] / WIN_KILLS * 180)
                tone(1200, 0.05)  # kill sfx
        if game["kills"] >= WIN_KILLS:
            win()
            game = new_game()
            continue

    # spawn enemies at either end (gets harder the more enemies you kill)
    if now - game["last_spawn"] > max(0.8, 2.0 - game["kills"] * 0.12):
        game["last_spawn"] = now
        spawn = random.choice((0, NUM_PIXELS - 1))
        if abs(spawn - game["player"]) > 3:
            game["enemies"].append(spawn)

    # enemies step toward the player
    if now - game["last_step"] > max(0.12, 0.35 - game["kills"] * 0.02):
        game["last_step"] = now
        game["enemies"] = [e + (1 if e < game["player"] else -1) for e in game["enemies"]]

    # enemy touching player = lose a life
    for enemy in game["enemies"].copy():
        if enemy == game["player"]:
            game["enemies"].remove(enemy)
            game["lives"] -= 1
            tone(150, 0.2)  # low hit buzz
            if game["lives"] <= 0:
                lose()
                game = new_game()
                break

    # draw everything
    pixels.fill((0, 0, 0))
    for enemy in game["enemies"]:
        pixels[enemy] = (255, 0, 0)
    if now < game["blast_until"]:
        for b in game["blast"]:
            if 0 <= b < NUM_PIXELS:
                pixels[b] = (255, 180, 0)
    pixels[game["player"]] = (0, 0, 255)
    # lives shown as dim green pixels at the strip start
    for i in range(game["lives"]):
        if pixels[i] == (0, 0, 0):
            pixels[i] = (0, 20, 0)
    pixels.show()

    time.sleep(0.02)
