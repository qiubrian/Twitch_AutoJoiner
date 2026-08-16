# Twitch_AutoJoiner
Script that allows you to join a twitch stream the minute the streamer goes live without active user action

To run, clone the repo and go to twitch dev tools (https://dev.twitch.tv/login) and login. 

After logging in, go to applications and register a new application. Then, name it and use a localhost URL for the OAuth Redirect URL (ex: http://localhost:3000) (The OAuth Redirect URL isnt needed for this as the program uses client credentials). Select the catagory of "Other" and then select confidential and create. 

Then, click manage on the application. Create a config.json file using the config.example.json file present in the repo and copy and paste the client ID and secret (Generate a new secret if one doesnt appear) into the proper fields. Dont commit or share these credentials. 

Then run the program by using 

cd Twitch_AutoJoiner 

and using 

python3 main.py 

after changing directory. After running, the terminal should display a constant stream of checking if the streamer is online. Set device to not turn off/sleep and let the program run. After the streamer goes live, the program will launch a tab to the streamers stream. It will only do this if there is no tab of the streamers stream already open or if the program has already opened the stream tab and it is still open. After joining, feel free to 

CTRL + C (Keyboard Interrupt) 

the program.

