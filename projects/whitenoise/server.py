import argparse
import os
import socket
import time
from datetime import datetime, timedelta

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask
from schedule_vol import Volumizer, get_now
from srutils import cmd

app = Flask(__name__)
scheduler = None

# To autoplay Privacy and security > Site Settings > Additional Content Settings > Sites can play sound > Allowed to play sound > Add [*].mynoise.net
brown_noise_url = "https://mynoise.net/NoiseMachines/whiteNoiseGenerator.php?l=72818175533616000000&title=White%20Noise%20&%20Co"


class Globals:
    def __init__(self):
        self.v = Volumizer()
        self.scheduler = None
        self.stop_ramp = False
        self.shush_end_time = None
        self.shush_thread = None


_g = Globals()

####################################################
# Heper functions
####################################################


def myip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    ip = str(s.getsockname()[0])
    s.close()
    return ip


def try_report_ip():
    ip = myip()
    print(f"IP is {ip}")
    url = "http://ec3.sfflux.com/djoli/postip"
    myobj = {"ip": str(ip)}
    try:
        x = requests.post(url, json=myobj, timeout=5)
        print(f"Reported IP result {x}")
    except Exception as ex:
        print(f"Failed to report ip: {ex}")
        return


def _serve_file(fid):
    pth = f"./files/{fid}"
    if not os.path.exists(pth):
        raise Exception(f"Path not found: {pth}")
    mode = "r"
    if "png" in fid or "ico" in fid:
        mode = "rb"
    with open(pth, mode) as f:
        return f.read()


def open_url(url):
    """Util to always open links in a specific chrome profile"""
    chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if not os.path.exists(chrome_path):
        import webbrowser

        webbrowser.open(url)
        return

    profile = os.getenv("CHROME_PROFILE", "Default")
    try:
        resp = cmd(f'"{chrome_path}" --profile-directory=\'{profile}\' "{url}"')
    except Exception as e:
        print(f"Error opening Chrome: {e}")
        resp = webbrowser.open(url)
    return resp


def kill_chrome():
    return cmd("pkill -9 Chrome")


def restart_noise_browser():
    resp = kill_chrome()
    time.sleep(3)
    resp += open_url(brown_noise_url)
    return resp


####################################################
# Routes
####################################################


def _cmd_resp(c):
    return {"res": "OK", "command": c, "time": get_now()}


@app.route("/vol/off")
def vol_off():
    global _g
    print("vol off")
    _g.v.apply_boost(b_abs=-10)
    return _cmd_resp("vol_off")


@app.route("/vol/less")
def vol_less():
    global _g
    _g.v.apply_boost(b_delta=-1)
    print("vol less")
    return _cmd_resp("vol_less")


@app.route("/vol/more")
def vol_more():
    global _g
    _g.v.apply_boost(b_delta=1)
    print("vol more")
    return _cmd_resp("vol_more")


@app.route("/vol/max")
def vol_max():
    global _g
    _g.v.apply_boost(b_abs=7)
    print("vol max")
    return _cmd_resp("vol_max")


####################################################
# Audio Playing
####################################################


def play_audio(filename):
    import pygame

    pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=4096)
    sound = pygame.mixer.Sound(filename)

    while True:
        pygame.mixer.Sound.play(sound)
        time.sleep(sound.get_length())


def play_brownnoise(filename):
    import multiprocessing

    process = multiprocessing.Process(target=play_audio, args=(filename,), daemon=True)
    print(f"Statrting proces {process}")
    process.start()
    return process


def play_shush_loop():
    import threading

    import pygame

    global _g

    def shush_thread():
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=4096)
        sound = pygame.mixer.Sound("files/shush.wav")

        while _g.shush_end_time and time.time() < _g.shush_end_time:
            pygame.mixer.Sound.play(sound)
            time.sleep(sound.get_length())
            time.sleep(1)  # 1 second delay between plays

        # Reset when done
        _g.shush_end_time = None
        _g.shush_thread = None

    thread = threading.Thread(target=shush_thread, daemon=True)
    thread.start()
    _g.shush_thread = thread
    return thread


##################################################
# Ramps
##################################################


def do_ramp(delta):
    print(f"Background job doing ramp {delta}")
    ramp_intervals = int(10 * abs(delta))
    ramp_seconds = int(5 * abs(delta))
    for i in range(ramp_intervals):
        if _g.stop_ramp:
            _g.stop_ramp = False
            print("Stopping ramp")
            return
        _g.v.apply_boost(b_delta=(delta / ramp_intervals))
        time.sleep(ramp_seconds / ramp_intervals)


@app.route("/vol/rampup")
def ramp_up():
    global _g
    print("ramp up")
    _g.scheduler.add_job(
        do_ramp, "date", run_date=datetime.now() + timedelta(seconds=1), args=[1]
    )
    return _cmd_resp("rampup")


@app.route("/vol/rampdown")
def ramp_down():
    global _g
    _g.scheduler.add_job(
        do_ramp, "date", run_date=datetime.now() + timedelta(seconds=1), args=[-1]
    )
    print("ramp down")
    return _cmd_resp("ramp_down")


@app.route("/vol/rampmax")
def ramp_max():
    global _g
    print("ramp_max")
    _g.scheduler.add_job(
        do_ramp, "date", run_date=datetime.now() + timedelta(seconds=1), args=[7]
    )
    return _cmd_resp("ramp_max")


@app.route("/vol/rampoff")
def ramp_off():
    global _g
    _g.scheduler.add_job(
        do_ramp, "date", run_date=datetime.now() + timedelta(seconds=1), args=[-10]
    )
    print("ramp off")
    return _cmd_resp("ramp_off")


@app.route("/vol/unset")
def vol_unset():
    global _g
    _g.stop_ramp = True
    _g.v.unset_boost()
    print("vol boost unset")
    return _cmd_resp("vol_unset")


@app.route("/reset")
def reset():
    resp = restart_noise_browser()
    return {"status": "OK", "now": get_now(), "resp": str(resp)}


@app.route("/shush")
def shush():
    global _g
    current_time = time.time()

    if _g.shush_end_time and current_time < _g.shush_end_time:
        # Extend existing shush by 5 minutes
        _g.shush_end_time += 5 * 60
        remaining_minutes = int((_g.shush_end_time - current_time) / 60)
        print(
            f"Extending shush by 5 minutes, now {remaining_minutes} minutes remaining"
        )
        return {
            "status": "OK",
            "now": get_now(),
            "message": f"Shush extended by 5 minutes, now {remaining_minutes} minutes remaining",
            "shush_end_time": _g.shush_end_time,
        }
    else:
        # Start new shush session
        _g.shush_end_time = current_time + (5 * 60)  # 5 minutes from now
        print("Starting shush audio loop for 5 minutes")
        _thread = play_shush_loop()
        return {
            "status": "OK",
            "now": get_now(),
            "message": "Shush audio started for 5 minutes",
            "shush_end_time": _g.shush_end_time,
        }


@app.route("/status")
def status():
    global _g
    now = get_now()
    vol, debug = _g.v.get_vol(now, debug=True)

    shush_remaining = 0
    if _g.shush_end_time and time.time() < _g.shush_end_time:
        shush_remaining = int((_g.shush_end_time - time.time()) / 60)

    return {
        "debug": debug,
        "vol": round(vol, 2),
        "now": now,
        "shush_remaining_minutes": shush_remaining,
    }


@app.route("/files/<fid>")
def get_files(fid):
    return _serve_file(fid)


@app.route("/index.html")
def get_index(fid):
    return _serve_file("index.html")


@app.route("/")
def homepage():
    return _serve_file("index.html")


####################################################
# Main
####################################################


def background_job():
    global _g

    _g.v.update()

    try_report_ip()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="""
        web-server example
"""
    )
    parser.add_argument(
        "--debug-mode",
        dest="debug_mode",
        action="store_true",
        help="Run in debug mode, where flask auto-restarts on code-changes",
    )
    parser.add_argument(
        "--play-audio",
        dest="play_audio",
        action="store_true",
        help="Play audio (Experimental)",
    )
    args = parser.parse_args()

    try_report_ip()

    # run once immediately on init
    background_job()

    print("Starting background scheduler")
    _g.scheduler = BackgroundScheduler()
    job = _g.scheduler.add_job(background_job, "interval", minutes=5)
    _g.scheduler.start()

    audio_process = None
    if args.play_audio:
        print("Playing audio process")
        audio_process = play_brownnoise("brownnoise-longtrim.mp3")

    def _cleanup():
        if audio_process:
            print("Terminating audio process")
            audio_process.terminate()

    # app.run(debug=args.debug_mode, host="127.0.0.1", port=80)
    try:
        app.run(debug=args.debug_mode, host="0.0.0.0", port=8080)
    except KeyboardInterrupt as ex:
        print(f"Keyboard Interrupt {ex}")
        _cleanup()
        raise
    except Exception as ex:
        print(f"Exception {ex}")
        _cleanup()
        raise
