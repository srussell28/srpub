#!/usr/bin/env python3

import datetime
import sys
import time
import uuid

# constants
ALICE_STATUS_RUNNING = "status_running"
ALICE_STATUS_HEARTBEAT = "status_heartbeat"
ALICE_STATUS_PAUSED = "status_paused"
ALICE_STATUS_KILLED = "status_killed"
ALICE_STATUS_ERROR = "status_error"
ALICE_STATUS_FATALERROR = "status_fatalerror"
ALICE_STATUS_COMPLETE = "status_completed"

ALICE_INTERVAL_SLOW = 30
ALICE_INTERVAL_FAST = 3

alice_uuid = None
alice_host = None
alice_status = None
alice_lastcheck = None
alice_interval = None
alice_fast_until = None
alice_custom_actions = None
alice_debug = False


def get_now():
    return datetime.datetime.now()


def seconds_between(da, db):
    return (db - da).total_seconds()


def _alice_post_status(s, perc_done=None, message=None):
    from srutils import cmd

    c = (
        "curl -s -X POST -d uuid='"
        + alice_uuid
        + "' -d name='"
        + alice_name
        + "' -d host='"
        + alice_host
        + "' -d status='"
        + s
        + "'"
    )
    if perc_done is not None:
        c += " -d perc_done='" + str(perc_done) + "'"
    if message:
        c += " -d message='" + str(message) + "'"
    if alice_custom_actions:
        c += " -d custom_actions='" + str(",".join(alice_custom_actions.keys())) + "'"
    c += " http://ec3.sfflux.com/alice/report"
    resp = cmd(c)
    return resp


def _alice_status_once(perc_done=None, message=None):
    global alice_status, alice_interval, alice_fast_until, alice_debug

    messages = []
    if message:
        messages.append(message)
    if alice_interval == ALICE_INTERVAL_FAST:
        messages.append("fast_interval")

    resp = _alice_post_status(alice_status, perc_done=perc_done, message=messages)
    if alice_debug:
        print(
            "cmd was\n-----------------------------------------\n"
            + str(resp)
            + "\n----------------------------------------\n"
        )

    # special, since can be combined with others
    if "action_fast_interval" in resp:
        alice_interval = ALICE_INTERVAL_FAST
        alice_fast_until = get_now() + datetime.timedelta(minutes=3)

    if alice_custom_actions:
        for action in alice_custom_actions.keys():
            if action in resp:
                # Do the action?
                action_result = alice_custom_actions[action]()
                _alice_post_status(action, message=action_result)

    # Terminating actions
    if "action_terminate" in resp:
        print(str(get_now()) + " i am dying")
        alice_status = ALICE_STATUS_KILLED
        _alice_post_status(alice_status)
        sys.exit(1)
    elif "action_run" in resp:
        if alice_status != ALICE_STATUS_RUNNING:
            alice_status = ALICE_STATUS_RUNNING
            alice_interval = ALICE_INTERVAL_FAST
            alice_fast_until = get_now() + datetime.timedelta(minutes=3)
        return True
    elif "action_pause" in resp:
        if alice_status != ALICE_STATUS_PAUSED:
            alice_status = ALICE_STATUS_PAUSED
            alice_interval = ALICE_INTERVAL_FAST
            alice_fast_until = get_now() + datetime.timedelta(minutes=3)
        return False
    else:
        print("error getting status, response was >" + str(resp) + "<")
        return True


# Interface functions
def alice_init(name=None, custom_actions=None, debug=False):
    from srutils import cmd

    global \
        alice_name, \
        alice_uuid, \
        alice_host, \
        alice_status, \
        alice_lastcheck, \
        alice_interval, \
        alice_fast_until, \
        alice_custom_actions, \
        alice_debug
    alice_uuid = str(uuid.uuid4())

    if name:
        alice_name = name
    else:
        alice_name = sys.argv[0]
        alice_name = alice_name.removeprefix("./")

    alice_host = cmd("hostname").strip()
    alice_status = ALICE_STATUS_RUNNING
    alice_lastcheck = None
    alice_interval = ALICE_INTERVAL_FAST
    alice_fast_until = get_now() + datetime.timedelta(minutes=3)
    alice_custom_actions = custom_actions
    alice_debug = debug


def alice_enabled():
    return alice_uuid is not None


def alice_check_status(perc_done=None, message=None):
    global alice_lastcheck, alice_interval, alice_fast_until, alice_debug

    if not alice_enabled():
        alice_init()

    # Expire fast_interval calls
    if get_now() > alice_fast_until:
        alice_interval = ALICE_INTERVAL_SLOW
    if alice_debug:
        print(
            "interval is "
            + str(alice_interval)
            + " expire fast interval in "
            + str(alice_fast_until - get_now())
        )

    # Update if we haven't updated in interval seconds
    now = get_now()
    if (
        alice_lastcheck is None
        or seconds_between(alice_lastcheck, now) > alice_interval
    ):
        alice_lastcheck = now
        while not _alice_status_once(perc_done=perc_done, message=message):
            print(str(get_now()) + " i am  paused")
            time.sleep(alice_interval)


def alice_complete():
    alice_status = ALICE_STATUS_COMPLETE
    _alice_post_status(alice_status)


def alice_error(details=None):
    alice_status = ALICE_STATUS_ERROR
    _alice_post_status(alice_status, message=details)


def alice_fatalerror(details=None):
    alice_status = ALICE_STATUS_FATALERROR
    _alice_post_status(alice_status, message=details)


def alice_success(details=None):
    alice_status = ALICE_STATUS_RUNNING
    _alice_post_status(alice_status, message=details)
