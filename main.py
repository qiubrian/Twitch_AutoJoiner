import json
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"
STATE_FILE = BASE_DIR / "state.json"

def load_config():
    if not CONFIG_FILE.exists():
        print("ERROR: config.json was not found.")
        print("\nCreate it by running:")
        print("\ncp config.example.json config.json")
        print("\nThen edit config.json and add your Twitch credentials.")
        raise SystemExit(1)
    try:
        with open(CONFIG_FILE, "r") as file:
            config = json.load(file)
    except json.JSONDecodeError as error:
        print("ERROR: config.json contains invalid JSON.")
        raise SystemExit(1)
    required_fields = ["client_id", "client_secret", "streamer"]
    for field in required_fields:
        if field not in config or not config[field]:
            print(f"ERROR: Missing required config value: {field}")
            raise SystemExit(1)
    return config

config = load_config()

CLIENT_ID = config["client_id"]
CLIENT_SECRET = config["client_secret"]
STREAMER = config["streamer"].strip().lower()
CHECK_INTERVAL = config.get("check_interval", 60)
TWITCH_URL = f"https://www.twitch.tv/{STREAMER}"

def get_access_token():
    token_url = "https://id.twitch.tv/oauth2/token"
    data = urllib.parse.urlencode({"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "grant_type": "client_credentials"}).encode("utf-8")
    request = urllib.request.Request(token_url, data=data, method="POST")
    with urllib.request.urlopen(request, timeout=15) as response:
        result = json.load(response)
    return result["access_token"]

def get_live_stream(access_token):
    query = urllib.parse.urlencode({"user_login": STREAMER})
    url = f"https://api.twitch.tv/helix/streams?{query}"
    request = urllib.request.Request(url,headers={"Client-Id": CLIENT_ID, "Authorization": f"Bearer {access_token}"})
    with urllib.request.urlopen(request, timeout=15) as response:
        result = json.load(response)
    streams = result.get("data", [])
    if not streams:
        return None
    return streams[0]

def load_state():
    if not STATE_FILE.exists():
        return {}
    try:
        with open(STATE_FILE, "r") as file:
            return json.load(file)
    except (json.JSONDecodeError, OSError):
        return {}

def save_state(state):
    with open(STATE_FILE, "w") as file:
        json.dump(state, file, indent=4)

def get_last_opened_stream_id():
    state = load_state()
    return state.get("last_opened_stream_id")

def save_last_opened_stream(stream):
    state = {"last_opened_stream_id": stream["id"], "streamer": STREAMER, "title": stream.get("title", ""), "started_at": stream.get("started_at", "")}
    save_state(state)

def open_stream():
    print(f"Opening {TWITCH_URL}", flush=True)
    subprocess.Popen(["/usr/bin/open", TWITCH_URL])

def check_stream(access_token):
    stream = get_live_stream(access_token)
    if stream is None:
        print(f"{STREAMER} is offline", flush=True)
        return access_token
    stream_id = stream["id"]
    stream_title = stream.get("title", "")
    print(f"{STREAMER} is live: {stream_title}", flush=True)
    last_stream_id = get_last_opened_stream_id()
    if stream_id != last_stream_id:
        print("Stream detected", flush=True)
        open_stream()
        save_last_opened_stream(stream)
    else:
        print("This stream has already been opened", flush=True)
    return access_token

def main():
    print(f"Watching channel: {STREAMER}", flush=True)
    print(f"Checking every {CHECK_INTERVAL} seconds.", flush=True)
    print(f"Stream URL: {TWITCH_URL}", flush=True)
    print(flush=True)
    access_token = None
    while True:
        try:
            if access_token is None:
                print("Getting token", flush=True)
                access_token = get_access_token()
                print("Twitch authenticated", flush=True)
            access_token = check_stream(access_token)
        except urllib.error.HTTPError as error:
            print(f"Twitch API returned HTTP {error.code}", flush=True)
            if error.code == 401:
                print("Token expired", flush=True)
                print("Refreshing token", flush=True)
                access_token = None
            elif error.code == 400:
                print("Twitch rejected request", flush=True)
                print("Check Client ID and secret, and streamer name", flush=True)
            else:
                print(f"HTTP error: {error}", flush=True)
        except urllib.error.URLError as error:
            print(f"Network error: {error}", flush=True)
        except KeyboardInterrupt:
            print("Program terminated", flush=True)
            break
        except Exception as error:
            print(f"Error: {error}", flush=True)
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()