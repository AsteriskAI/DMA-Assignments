import time
import board
import neopixel
from rainbowio import colorwheel

# Setup a single NeoPixel LED at 30% brightness
pixel = neopixel.NeoPixel(board.NEOPIXEL, 1)
pixel.brightness = 0.3


# Helper function to smoothly transition brightness
def fade(color, target, step, delay):
    while abs(pixel.brightness - target) > abs(step):
        pixel[0] = color
        pixel.brightness += step
        time.sleep(delay)
    pixel.brightness = target
    pixel[0] = color


# Slowly fade in cyan from black
def intro():
    pixel.brightness = 0.3
    for c in range(255):
        pixel[0] = (0, c, c)
        pixel.brightness += 0.0027
        time.sleep(0.01)


# Cycle through the rainbow for 5 seconds to make disco
def disco():
    start = time.monotonic()
    while time.monotonic() - start < 5:
        for i in range(255):
            pixel[0] = colorwheel(i)
            time.sleep(0.0015)


# Pulse cyan on and off to simulate our character looking left and right
def seeking():
    pixel[0] = (0, 0, 0)
    time.sleep(0.5)
    cyan = (0, 255, 255)
    for target in (0.05, 1, 0.05, 1, 0):
        step = 0.005 if target > pixel.brightness else -0.005
        fade(cyan, target, step, 0.01)


# Slow, long fades of deep blue
def depression():
    blue = (0, 0, 140)
    time.sleep(1.5)
    fade(blue, 0.8, 0.008, 0.04)
    time.sleep(5)
    fade(blue, 0, -0.008, 0.04)
    time.sleep(5)


# Hold a solid bright orange for 'timer' seconds
def friend(timer):
    pixel.brightness = 1
    start = time.monotonic()
    while time.monotonic() - start < timer:
        pixel[0] = (254, 60, 0)


# Quick blue fade up and down
def wakeup():
    pixel[0] = (0, 0, 0)
    blue = (0, 0, 140)
    time.sleep(1.5)
    pixel.brightness = 0
    fade(blue, 0.5, 0.003, 0.02)
    fade(blue, 0, -0.003, 0.02)


# Pulse bright orange quickly 10 times 
def calling():
    pixel.brightness = 1
    orange = (254, 60, 0)
    for i in range(10):
        fade(orange, 0.5, -0.03, 0.003)
        fade(orange, 1, 0.03, 0.003)
        fade(orange, 0.5, -0.03, 0.003)


# One slow cyan pulse
def alive():
    pixel.brightness = 0
    cyan = (0, 255, 255)
    for i in range(1):
        fade(cyan, 0.6, 0.003, 0.02)
        fade(cyan, 0.1, -0.001, 0.01)


# Alternate orange and cyan, speeding up until they fuse
def pulse():
    cyan = (0, 255, 255)
    orange = (254, 60, 0)
    
    up_step = 0.01
    down_step = -0.01
    delay = 0.015
    
    for i in range(10):
        fade(orange, 1.0, up_step, delay)
        fade(orange, 0.1, down_step, delay)
        
        fade(cyan, 1.0, up_step, delay)
        fade(cyan, 0.1, down_step, delay)
        
        # Speed up the fade for the next loop
        up_step *= 1.4
        down_step *= 1.4
        delay *= 0.8

    # Strobe really fast so the colors blur together
    pixel.brightness = 1.0
    for i in range(40):
        pixel[0] = orange
        time.sleep(0.004)
        pixel[0] = cyan
        time.sleep(0.004)
        
    # Fade out to white
    white = (255, 255, 255)
    pixel[0] = white
    fade(white, 0, -0.005, 0.02)


# Play all animations in order
def story():
    intro()
    disco()
    seeking()
    depression()
    friend(5)
    disco()
    wakeup()
    calling()
    alive()
    pulse()


# Loop the story forever
while True:
    story()
