import time
import math
import array
import board
import digitalio
import neopixel
import audiocore
import audiobusio
import adafruit_vl53l4cd
import adafruit_lis3dh


# Predefined values
MAX_DISTANCE_CM = 100.0        # farther than this = no target
MIN_DISTANCE_CM = 2.0          # ignore readings closer than this
BRIGHTNESS = 0.25

RING_PIXEL_COUNT = 12
BAR_PIXEL_COUNT = 8
SOUND_MUTED = False

FLICK_THRESHOLD_G = 2        # G value required to switch modes
FLICK_COOLDOWN_SECONDS = 1.0
MISSES_BEFORE_TARGET_LOST = 4  # bad readings in a row before target is lost

# C major pentatonic, used by theremin mode
PENTATONIC_NOTES_HZ = [262, 294, 330, 392, 440, 523, 587, 659, 784, 880]

# Powers the speaker amp and the NEO terminal
external_power = digitalio.DigitalInOut(board.EXTERNAL_POWER)
external_power.direction = digitalio.Direction.OUTPUT
external_power.value = True

# Ring on D5
ring_pixels = neopixel.NeoPixel(
    board.D5, RING_PIXEL_COUNT, brightness=BRIGHTNESS, auto_write=False
)

# Bar on the NEO terminal
bar_pixels = neopixel.NeoPixel(
    board.EXTERNAL_NEOPIXELS, BAR_PIXEL_COUNT, brightness=BRIGHTNESS,
    auto_write=False, pixel_order=neopixel.GRBW
)

i2c = board.I2C()

#Initalization of distance sensor

distance_sensor = adafruit_vl53l4cd.VL53L4CD(i2c)
distance_sensor.inter_measurement = 0
distance_sensor.timing_budget = 50
distance_sensor.start_ranging()

# Initialization of accelerometer
for address in (0x18, 0x19):
    accelerometer = adafruit_lis3dh.LIS3DH_I2C(i2c, address=address)
    accelerometer.range = adafruit_lis3dh.RANGE_8_G
    break


# Sound helper functions

# The sample rate stays fixed so pitch comes from how many samples one sine cycle uses.
SOUND_SAMPLE_RATE = 22050
speaker = audiobusio.I2SOut(board.I2S_BIT_CLOCK, board.I2S_WORD_SELECT, board.I2S_DATA)

tone_cache = {}            # ready-made sine sample
current_tone_hz = 0        # 0 = silent
tone_stop_time = None      # when a timed tone should end


def get_tone_sample(frequency_hz):
    # Build a looping sine wave for this pitch the first time it's needed
    samples_per_cycle = max(4, int(SOUND_SAMPLE_RATE / frequency_hz + 0.5))
    if samples_per_cycle not in tone_cache:
        wave = array.array(
            "h",
            [int(math.sin(2 * math.pi * i / samples_per_cycle) * 22000)
for i in range(samples_per_cycle)],)
        tone_cache[samples_per_cycle] = audiocore.RawSample(wave, sample_rate=SOUND_SAMPLE_RATE)
    return tone_cache[samples_per_cycle] # Add to the cache so we can call it instantly


# Start the tone and stop when required.
def start_tone(frequency_hz, duration_seconds=None):
    # Play a tone, it stops by itself if a duration is given
    global current_tone_hz, tone_stop_time
    if SOUND_MUTED:
        return
    frequency_hz = int(frequency_hz)
    if frequency_hz != current_tone_hz or not speaker.playing:
        if speaker.playing:
            speaker.stop()   # restart so the new pitch takes effect
        speaker.play(get_tone_sample(frequency_hz), loop=True)
    current_tone_hz = frequency_hz
    tone_stop_time = (time.monotonic() + duration_seconds) if duration_seconds else None


def stop_tone():
    global current_tone_hz, tone_stop_time
    current_tone_hz = 0
    tone_stop_time = None
    if speaker.playing:
        speaker.stop()


def stop_timed_tone_if_finished(now):
    if tone_stop_time is not None and now >= tone_stop_time:
        stop_tone()

# LED helper functions

def clamp(value, lowest=0.0, highest=1.0):
    return max(lowest, min(highest, value))

def dim(color, factor):
    red, green, blue = color
    return (int(red * factor), int(green * factor), int(blue * factor))

def distance_to_color(distance_cm):
    # Near = red, middle = yellow/green, far = cyan
    fraction_of_max = clamp(distance_cm / MAX_DISTANCE_CM)
    if fraction_of_max < 0.5:
        return (255, int(510 * fraction_of_max), 0)
    return (int(510 * (1 - fraction_of_max)), 255, int(510 * (fraction_of_max - 0.5)))

def set_ring_pixel(position, color):
    # Positions wrap around, so -1 is the last pixel
    if RING_REVERSED:
        position = -position
    ring_pixels[position % RING_PIXEL_COUNT] = color

def clear_ring():
    for position in range(RING_PIXEL_COUNT):
        ring_pixels[position] = 0

def clear_bar():
    for position in range(BAR_PIXEL_COUNT):
        bar_pixels[position] = 0

def show_all_pixels():
    ring_pixels.show()
    bar_pixels.show()

def show_distance_on_bar(distance_cm, color=None):
    # Closer target = more segments lit; no target = one dim green pixel
    clear_bar()
    if distance_cm is None:
        bar_pixels[0] = (0, 20, 0)
        return
    exact_segments = (1 - clamp(distance_cm / MAX_DISTANCE_CM)) * BAR_PIXEL_COUNT
    full_segments = int(exact_segments)
    for segment in range(full_segments):
        segment_distance = segment * MAX_DISTANCE_CM / BAR_PIXEL_COUNT
        bar_pixels[segment] = color or distance_to_color(segment_distance)
    if full_segments < BAR_PIXEL_COUNT:
        # Dim the last segment to show the fraction between steps
        partial_fraction = exact_segments - full_segments
        bar_pixels[full_segments] = dim(color or distance_to_color(distance_cm), partial_fraction)

# Distance sensor helper functions
smoothed_distance_cm = None    # None = no target
consecutive_misses = 0

def read_distance_sensor():
    global smoothed_distance_cm, consecutive_misses
    if not distance_sensor.data_ready:
        return
    distance_sensor.clear_interrupt()
    raw_distance_cm = distance_sensor.distance

    reading_is_valid = (
        raw_distance_cm is not None
        and MIN_DISTANCE_CM < raw_distance_cm <= MAX_DISTANCE_CM
    )
    if reading_is_valid:
        consecutive_misses = 0
        if smoothed_distance_cm is None:
            smoothed_distance_cm = raw_distance_cm
        else:
            # Average with the previous value to reduce jitter
            smoothed_distance_cm = smoothed_distance_cm * 0.5 + raw_distance_cm * 0.5
    else:
        consecutive_misses += 1
        if consecutive_misses >= MISSES_BEFORE_TARGET_LOST:
            smoothed_distance_cm = None


# Modes as classes

#Radar mode
class RadarMode:
    # Spinning beam; color and ping speed follow the target
    color = (0, 255, 60)

    def __init__(self):
        self.next_ping_time = 0

    def update(self, now):
        beam_head = int(now * 8) % RING_PIXEL_COUNT
        if smoothed_distance_cm is not None:
            beam_color = distance_to_color(smoothed_distance_cm)
        else:
            beam_color = (0, 70, 20)

        clear_ring()
        for tail_step in range(5):
            set_ring_pixel(beam_head - tail_step, dim(beam_color, 1 - tail_step * 0.2))
        show_distance_on_bar(smoothed_distance_cm)

        # Closer = higher pitch and faster pings
        if smoothed_distance_cm is not None and now >= self.next_ping_time:
            how_far = clamp(smoothed_distance_cm / MAX_DISTANCE_CM)
            start_tone(1400 - 800 * how_far, 0.04)
            self.next_ping_time = now + 0.08 + how_far * 0.8

# Depth tracing mode
class DepthTraceMode:
    # Sweep the wrist across a room, the ring records 12 distances
    color = (0, 120, 255)

    def __init__(self):
        self.saved_distances = [None] * RING_PIXEL_COUNT
        self.write_position = 0
        self.next_sample_time = 0

    def update(self, now):
        if now >= self.next_sample_time:
            self.next_sample_time = now + 0.18
            self.saved_distances[self.write_position] = smoothed_distance_cm
            if smoothed_distance_cm is not None:
                how_far = clamp(smoothed_distance_cm / MAX_DISTANCE_CM)
                start_tone(1200 - 800 * how_far, 0.025)
            self.write_position = (self.write_position + 1) % RING_PIXEL_COUNT

        for position in range(RING_PIXEL_COUNT):
            saved = self.saved_distances[position]
            if saved is not None:
                set_ring_pixel(position, distance_to_color(saved))
            else:
                set_ring_pixel(position, (6, 6, 12))
        set_ring_pixel(self.write_position, (255, 255, 255))  # next slot
        show_distance_on_bar(smoothed_distance_cm)


# Theremin mode
class ThereminMode:
    # Distance picks a note, the ring fills as you get closer
    color = (200, 0, 255)

    def update(self, now):
        clear_ring()
        clear_bar()
        if smoothed_distance_cm is None:
            stop_tone()
            bar_pixels[0] = (20, 0, 30)
            return

        closeness = 1 - clamp(smoothed_distance_cm / MAX_DISTANCE_CM)  # 0 far .. 1 near
        note_index = min(int(closeness * len(PENTATONIC_NOTES_HZ)), len(PENTATONIC_NOTES_HZ) - 1)
        start_tone(PENTATONIC_NOTES_HZ[note_index])

        pixels_lit = 1 + int(closeness * (RING_PIXEL_COUNT - 1))
        fill_color = (int(255 * closeness), 40, int(255 * (1 - closeness)))
        for position in range(pixels_lit):
            set_ring_pixel(position, fill_color)
        show_distance_on_bar(smoothed_distance_cm, (180, 0, 255))

# Anomaly mode
class AnomalyMode:
    # Learns a wall for 2 seconds, then alarms when the distance changes
    color = (255, 80, 0)
    CALIBRATION_SECONDS = 3.5
    ALARM_DIFFERENCE_CM = 5.0

    def __init__(self):
        self.calibration_started_at = None
        self.calibration_readings = []
        self.baseline_cm = None    # None until calibrated

    def update(self, now):
        if self.baseline_cm is None:
            self.calibrate(now)
            return
        distance_cm = smoothed_distance_cm if smoothed_distance_cm is not None else MAX_DISTANCE_CM
        difference_cm = abs(distance_cm - self.baseline_cm)
        clear_ring()
        clear_bar()
        if difference_cm < self.ALARM_DIFFERENCE_CM:
            stop_tone()
            glow = 0.25 + 0.25 * math.sin(now * 2)   # slow green pulse
            for position in range(RING_PIXEL_COUNT):
                set_ring_pixel(position, dim((0, 255, 80), glow * 0.4))
        else:
            beam_head = int(now * 20) % RING_PIXEL_COUNT
            for tail_step in range(6):
                set_ring_pixel(beam_head - tail_step, dim((255, 0, 0), 1 - tail_step * 0.16))
            segments_lit = int(clamp(difference_cm / 40) * BAR_PIXEL_COUNT) + 1
            for segment in range(min(segments_lit, BAR_PIXEL_COUNT)):
                bar_pixels[segment] = (255, 0, 0)
            start_tone(700 if int(now * 8) % 2 else 500)   # siren warble

    def calibrate(self, now):
        if self.calibration_started_at is None:
            self.calibration_started_at = now

        elapsed = now - self.calibration_started_at
        clear_ring()
        clear_bar()
        pixels_lit = int(clamp(elapsed / self.CALIBRATION_SECONDS) * RING_PIXEL_COUNT)
        for position in range(pixels_lit):
            set_ring_pixel(position, (255, 120, 0))   # orange progress

        if smoothed_distance_cm is not None:
            self.calibration_readings.append(smoothed_distance_cm)

        if elapsed >= self.CALIBRATION_SECONDS:
            if self.calibration_readings:
                self.baseline_cm = sum(self.calibration_readings) / len(self.calibration_readings)
            else:
                self.baseline_cm = MAX_DISTANCE_CM
            start_tone(880, 0.1)

MODE_CLASSES = [RadarMode, DepthTraceMode, ThereminMode, AnomalyMode]
current_mode_number = 0
current_mode = None

def switch_to_mode(mode_number):
    global current_mode_number, current_mode
    current_mode_number = mode_number % len(MODE_CLASSES)
    current_mode = MODE_CLASSES[current_mode_number]()   # fresh state
    stop_tone()

    ring_pixels.fill(0)
    bar_pixels.fill(0)
    for position in range(RING_PIXEL_COUNT):             # ring fills with mode color
        set_ring_pixel(position, current_mode.color)
        show_all_pixels()
        time.sleep(0.02)
    for segment in range(current_mode_number + 1):       # bar shows mode number
        bar_pixels[segment] = current_mode.color
    show_all_pixels()
    for chirp_number in range(current_mode_number + 1):  # one chirp per mode number
        start_tone(600 + chirp_number * 200, 0.08)
        time.sleep(0.12)
    stop_tone()

# Wrist flick
next_flick_allowed_time = 0

def check_for_wrist_flick(now):
    global next_flick_allowed_time
    if accelerometer is None:
        return
    
    accel_x, accel_y, accel_z = accelerometer.acceleration
    # Calculate g force andif it is over the required amount to switch modes, then switch the mode to the next one.
    total_g = math.sqrt(accel_x ** 2 + accel_y ** 2 + accel_z ** 2) / 9.80665
    if now > next_flick_allowed_time and total_g > FLICK_THRESHOLD_G:
        switch_to_mode(current_mode_number + 1)
        next_flick_allowed_time = time.monotonic() + FLICK_COOLDOWN_SECONDS

# Startup
for position in range(RING_PIXEL_COUNT):
    set_ring_pixel(position, (0, 120, 255))
    show_all_pixels()
    time.sleep(0.03)
start_tone(440, 0.1)
time.sleep(0.15)
start_tone(880, 0.15)
time.sleep(0.2)

switch_to_mode(0)
next_flick_allowed_time = time.monotonic() + FLICK_COOLDOWN_SECONDS


# main loop
while True:
    now = time.monotonic()
    read_distance_sensor()
    check_for_wrist_flick(now)
    current_mode.update(now)
    show_all_pixels()
    stop_timed_tone_if_finished(now)
    time.sleep(0.01)
