import json
import subprocess
import time
import requests
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
STATE_FILE = os.path.join(BASE_DIR, "state.json")

def loadConfig():
    if not os.path.exists(CONFIG_FILE):
        print("ERROR: config.json was not found.")
        print("\nCreate it by running:")
        print("\ncp config.example.json config.json")
        print("\nThen edit config.json and add your Twitch credentials.")
        raise SystemExit(1)
    try:
        with open(CONFIG_FILE, "r") as file:
            config = json.load(file)
    except json.JSONDecodeError:
        print("ERROR: config.json contains invalid JSON.")
        raise SystemExit(1)
    requiredFields = ["client_id", "client_secret", "streamer"]
    for field in requiredFields:
        if field not in config or not config[field]:
            print(f"ERROR: Missing required config value: {field}")
            raise SystemExit(1)
    return config

config = loadConfig()

CLIENT_ID = config["client_id"]
CLIENT_SECRET = config["client_secret"]
STREAMER = config["streamer"].strip().lower()
CHECK_INTERVAL = config.get("check_interval", 60)
TWITCH_URL = f"https://www.twitch.tv/{STREAMER}"

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
            return json.load(file)
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
    saveState(state)

def openStream():
    print(f"Opening {TWITCH_URL}", flush = True)
    subprocess.Popen(["/usr/bin/open", TWITCH_URL])

def checkStream(accessToken):
    stream = getStream(accessToken)
    if stream is None:
        print(f"{STREAMER} is offline", flush = True)
        return accessToken
    streamID = stream["id"]
    streamTitle = stream.get("title", "")
    print(f"{STREAMER} is live: {streamTitle}", flush = True)
    lastStreamID = getLastOpenedStreamID()
    if streamID != lastStreamID:
        print("Stream detected", flush = True)
        openStream()
        saveLastOpenedStream(stream)
    else:
        print("This stream has already been opened", flush = True)
    return accessToken

def main():
    print(f"Watching channel: {STREAMER}", flush = True)
    print(f"Checking every {CHECK_INTERVAL} seconds", flush = True)
    print(f"Stream URL: {TWITCH_URL}", flush = True)
    print(flush = True)
    accessToken = None
    while True:
        try:
            if accessToken is None:
                print("Getting token", flush = True)
                accessToken = getToken()
                print("Twitch authenticated", flush = True)
            accessToken = checkStream(accessToken)
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
    main()