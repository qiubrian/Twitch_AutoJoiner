import argparse
import json
import os
import platform
import re
import time
import uuid
import webbrowser
from datetime import datetime

import requests
from bridge import startTamperMonkey

currentOS = platform.system()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
STATE_FILE = os.path.join(BASE_DIR, "state.json")

def checkPosInt(value):
    num = int(value)
    if num <= 0:
        raise argparse.ArgumentTypeError("Error, must be greater than 0")
    return num

def checkDateTime(value):
    try:
        dateTime = datetime.fromisoformat(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError("Error, last match must use ISO format") from e
    if dateTime.tzinfo is None:
        raise argparse.ArgumentTypeError("Error, last match time must include a timezone")
    return dateTime

def applyCustomConfig():
    global STREAMER, CHECK_INTERVAL, TWITCH_URL, LAST_MATCH_TIME
    parser = argparse.ArgumentParser()
    parser.add_argument("--streamer")
    parser.add_argument("--interval", type = checkPosInt)
    parser.add_argument("--last-match-time", type = checkDateTime)
    args = parser.parse_args()
    if args.streamer:
        STREAMER = args.streamer.strip().lower()
    if args.interval is not None:
        CHECK_INTERVAL = args.interval
    if args.last_match_time is not None:
        LAST_MATCH_TIME = args.last_match_time
    TWITCH_URL = f"https://www.twitch.tv/{STREAMER}"

def loadConfig():
    if not os.path.exists(CONFIG_FILE):
        print("ERROR: config.json was not found.")
        print("\nCopy config.example.json to config.json.")
        print("\nThen edit config.json and add your Twitch credentials.")
        raise SystemExit(1)
    try:
        with open(CONFIG_FILE, "r") as file:
            config = json.load(file)
    except json.JSONDecodeError:
        print("ERROR: config.json contains invalid JSON.")
        raise SystemExit(1)
    if not isinstance(config, dict):
        raise SystemExit("ERROR: config.json must contain an object")
    requiredFields = ["client_id", "client_secret", "streamer"]
    for field in requiredFields:
        if not isinstance(config.get(field), str) or not config[field].strip():
            print(f"ERROR: Missing required config value: {field}")
            raise SystemExit(1)
    bridgeConfig = config.get("bridge")
    if not isinstance(bridgeConfig, dict):
        raise SystemExit("ERROR: bridge must be an object")
    token = bridgeConfig.get("token")
    if not isinstance(token, str) or len(token) < 32 or not token.isascii() or any(character.isspace() for character in token) or token.startswith(("PASTE_", "YOUR_", "ENTER_")):
        raise SystemExit("ERROR: Set bridge.token to a generated random token")
    bridgeConfig.setdefault("open_tab_interval", bridgeConfig.get("cooldown_seconds", 90))
    for field, default, minimum, maximum in (("port", 8765, 1024, 65535), ("open_tab_interval", 90, 1, None), ("max_reopens", 3, 0, None)):
        value = bridgeConfig.get(field, default)
        if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
            raise SystemExit(f"ERROR: Invalid numeric value: bridge.{field}")
        bridgeConfig[field] = value
    return config

config = loadConfig()

CLIENT_ID = config["client_id"]
CLIENT_SECRET = config["client_secret"]
STREAMER = config["streamer"].strip().lower()
CHECK_INTERVAL = config.get("check_interval", 60)
TWITCH_URL = f"https://www.twitch.tv/{STREAMER}"
LAST_MATCH_TIME = None

def getToken():
    tokenUrl = "https://id.twitch.tv/oauth2/token"
    data = {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "grant_type": "client_credentials"}
    response = requests.post(tokenUrl, data = data, timeout = 15)
    response.raise_for_status()
    result = response.json()
    return result["access_token"]

def getStream(accessToken):
    url = "https://api.twitch.tv/helix/streams"
    params = {"user_login": STREAMER}
    headers = {"Client-Id": CLIENT_ID, "Authorization": f"Bearer {accessToken}"}
    response = requests.get(url, params = params, headers = headers, timeout = 15)
    response.raise_for_status()
    result = response.json()
    streams = result.get("data", [])
    if not streams:
        return None
    return streams[0]

def loadState():
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r") as file:
            state = json.load(file)
            return state if isinstance(state, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}

def saveState(state):
    with open(STATE_FILE, "w") as file:
        json.dump(state, file, indent = 4)

def getLastOpenedStreamID():
    state = loadState()
    return state.get("lastOpenedStreamID")

def saveLastOpenedStream(stream):
    state = {"lastOpenedStreamID": stream["id"], "streamer": STREAMER, "title": stream.get("title", ""), "started_at": stream.get("started_at", "")}
    try:
        saveState(state)
    except OSError as error:
        print(f"Could not save state.json: {error}", flush = True)

def openStream(bridge, streamID, recovery = False):
    instanceID = uuid.uuid4().hex
    url = f"{TWITCH_URL}?autojoiner_id={instanceID}#autojoiner_port={config['bridge']['port']}&autojoiner_token={bridge.getTabToken(instanceID)}"
    print(f"Opening {TWITCH_URL}", flush = True)
    if not webbrowser.open_new_tab(url):
        raise RuntimeError("Could not open the default browser")
    bridge.recordOpen(instanceID, streamID, recovery = recovery)

def checkStream(accessToken, bridge):
    stream = getStream(accessToken)
    if stream is None:
        print(f"{STREAMER} is offline", flush = True)
        return False
    streamID = stream["id"]
    streamTitle = stream.get("title", "")
    print(f"{STREAMER} is live: {streamTitle}", flush = True)
    lastStreamID = getLastOpenedStreamID()
    if bridge.stream_id is not None:
        lastStreamID = bridge.stream_id
    if streamID != lastStreamID or bridge.instance_id is None:
        print("Stream detected", flush = True)
        openStream(bridge, streamID)
        saveLastOpenedStream(stream)
    elif bridge.recoveryDue():
        print("Persistent playback failure; opening a recovery tab", flush = True)
        openStream(bridge, streamID, recovery = True)
    else:
        print(f"This stream has already been opened: {bridge.getStatus()}", flush = True)
    return True

def main(bridge):
    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)
    print(f"Watching channel: {STREAMER}", flush = True)
    print(f"Checking every {CHECK_INTERVAL} seconds.", flush = True)
    print(f"Stream URL: {TWITCH_URL}", flush = True)
    print(flush = True)
    accessToken = None
    hasSeenStream = False
    while True:
        try:
            if accessToken is None:
                print("Getting token", flush = True)
                accessToken = getToken()
                print("Twitch authenticated", flush = True)
            streamIsLive = checkStream(accessToken, bridge)
            if streamIsLive:
                hasSeenStream = True
            elif LAST_MATCH_TIME is not None:
                currentTime = datetime.now(LAST_MATCH_TIME.tzinfo)
                if currentTime >= LAST_MATCH_TIME:
                    print("Stream has ended and no later matches are scheduled today", flush = True)
                    break
            elif hasSeenStream:
                print(f"{STREAMER} is offline, ending Twitch Autojoiner", flush = True)
                break
        except requests.exceptions.HTTPError as error:
            print(f"Twitch API returned HTTP {error.response.status_code}", flush = True)
            if error.response.status_code == 401:
                print("Token expired", flush = True)
                print("Refreshing token", flush = True)
                accessToken = None
            elif error.response.status_code == 400:
                print("Twitch rejected request", flush = True)
                print("Check Client ID and secret, and streamer name", flush = True)
            else:
                print(f"HTTP error: {error}", flush = True)
        except requests.exceptions.RequestException as error:
            print(f"Network error: {error}", flush = True)
        except KeyboardInterrupt:
            print("Program terminated", flush = True)
            break
        except Exception as error:
            print(f"Error: {error}", flush = True)
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    applyCustomConfig()
    if not re.fullmatch(r"[a-z0-9_]+", STREAMER):
        raise SystemExit("ERROR: Invalid streamer name")
    if type(CHECK_INTERVAL) is not int or CHECK_INTERVAL <= 0:
        raise SystemExit("ERROR: check_interval must be a positive integer")
    bridge = startTamperMonkey(streamer = STREAMER, token = config["bridge"]["token"], port = config["bridge"]["port"], cooldown_seconds = config["bridge"]["open_tab_interval"], max_reopens = config["bridge"]["max_reopens"])
    try:
        main(bridge)
    except KeyboardInterrupt:
        print("Program terminated", flush = True)
    finally:
        bridge.stop()