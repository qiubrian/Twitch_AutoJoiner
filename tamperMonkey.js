// ==UserScript==
// @name         Twitch AutoJoiner Playback Monitor
// @namespace    twitch-autojoiner
// @version      1.1.0
// @description  Report persistent playback failures to Twitch AutoJoiner.
// @match        https://www.twitch.tv/*
// @run-at       document-start
// @noframes
// @grant        GM_xmlhttpRequest
// @grant        GM_getValue
// @grant        GM_setValue
// @connect      127.0.0.1
// ==/UserScript==

(() => {
    "use strict";
    const initialUrl = new URL(location.href);
    const instanceId = initialUrl.searchParams.get("autojoiner_id");
    const channelPath = /^\/([a-zA-Z0-9_]+)\/?$/;
    const initialChannel = location.pathname.match(channelPath);
    if (!instanceId || !/^[0-9a-f]{32}$/.test(instanceId) || !initialChannel) {
        return;
    }
    const settings = new URLSearchParams(initialUrl.hash.slice(1));
    const storageKey = "autojoiner:" + instanceId;
    const saved = GM_getValue(storageKey, {}) || {};
    const TOKEN = settings.get("autojoiner_token") || saved.token;
    const port = Number(settings.get("autojoiner_port") || saved.port);
    if (typeof TOKEN !== "string" || !/^[0-9a-f]{64}$/.test(TOKEN) || !Number.isInteger(port) || port < 1024 || port > 65535) {
        console.warn("[AutoJoiner] Open this stream through Python first.");
        return;
    }
    GM_setValue(storageKey, {token: TOKEN, port});
    if (settings.has("autojoiner_token")) {
        initialUrl.hash = "";
        history.replaceState(history.state, "", initialUrl.href);
    }
    const BRIDGE = "http://127.0.0.1:" + port + "/status";
    const INTERVAL_MS = 5000;
    const FAILURE_MS = 45000;
    const STARTUP_MS = 60000;
    const streamer = initialChannel[1].toLowerCase();
    let video = null;
    let lastTime = 0;
    let lastProgress = performance.now();
    let lastTick = lastProgress;
    let graceUntil = lastProgress + STARTUP_MS;
    let errorSince = null;
    let stopped = false;
    let registered = false;

    function sample() {
        const now = performance.now();
        const channel = location.pathname.match(channelPath);
        const gap = now - lastTick;
        lastTick = now;
        if (!channel || channel[1].toLowerCase() !== streamer) {
            video = null;
            graceUntil = now + STARTUP_MS;
            return "suspended";
        }
        if (gap > INTERVAL_MS * 3) {
            lastProgress = now;
            errorSince = null;
            graceUntil = now + STARTUP_MS;
            return "suspended";
        }
        const nextVideo = document.querySelector('[data-a-target="video-player"] video') || document.querySelector("video");
        if (nextVideo !== video) {
            video = nextVideo;
            lastTime = video ? video.currentTime : 0;
            lastProgress = now;
            errorSince = null;
            graceUntil = now + STARTUP_MS;
        }
        if (!video) {
            return "loading";
        }
        const progressed = Math.abs(video.currentTime - lastTime) > 0.05;
        lastTime = video.currentTime;
        if (progressed || video.paused || video.seeking || video.ended) {
            lastProgress = now;
        }
        if (!video.error) {
            errorSince = null;
        }
        if (video.error) {
            if (errorSince === null) errorSince = now;
            return now >= graceUntil && now - errorSince >= FAILURE_MS ? "failed" : "buffering";
        }
        if (video.ended) return "ended";
        if (video.paused) return "paused";
        if (video.seeking) return "seeking";
        if (progressed) return "playing";
        return now >= graceUntil && now - lastProgress >= FAILURE_MS ? "failed" : "buffering";
    }

    function schedule() {
        if (!stopped) setTimeout(tick, INTERVAL_MS);
    }

    function tick() {
        const state = sample();
        try {
            GM_xmlhttpRequest({
                method: "POST",
                url: BRIDGE,
                headers: {"Content-Type": "application/json", "Authorization": "Bearer " + TOKEN},
                data: JSON.stringify({streamer, instance_id: instanceId, state}),
                timeout: 3000,
                onload(response) {
                    if (response.status === 200) {
                        try {
                            const accepted = JSON.parse(response.responseText).accepted;
                            if (accepted) registered = true;
                            if (accepted === false && registered) stopped = true;
                        } catch (error) {
                            console.warn("[AutoJoiner] Invalid bridge response.", error);
                        }
                    } else {
                        console.warn("[AutoJoiner] Bridge HTTP", response.status);
                    }
                    schedule();
                },
                onerror() {
                    console.warn("[AutoJoiner] Bridge unavailable.");
                    schedule();
                },
                ontimeout: schedule
            });
        } catch (error) {
            console.warn("[AutoJoiner] Report failed.", error);
            schedule();
        }
    }
    tick();
})();

// Paste this into tampermonkey