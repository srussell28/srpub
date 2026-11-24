import multiprocessing
import time

import pygame


def play_audio(filename):
    pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=4096)
    sound = pygame.mixer.Sound(filename)

    while True:
        pygame.mixer.Sound.play(sound)
        time.sleep(sound.get_length())


if __name__ == "__main__":
    filename = "brownnoise-longtrim.mp3"
    process = multiprocessing.Process(target=play_audio, args=(filename,), daemon=True)
    process.start()

    try:
        while True:
            time.sleep(5)
            print("other thing")
    except KeyboardInterrupt:
        process.terminate()
