# Talaria

This is a small local app for uploading planned workouts to Intervals.icu and generating a completed-training summary you can paste into an AI coach.

It uses only Python's standard library. No npm, no package installs, no hosted service.

Logo asset:

```text
Talaria.app/Contents/Resources/app/assets/talaria-logo.png
```

## Easiest Start

Double-click:

```text
Start Intervals Planner.command
```

That opens the native desktop app. There is no browser URL and no port to think about.

If macOS cannot find a Python install with Tkinter after you move the app, Talaria will automatically fall back to its local browser UI and open it for you.

## Terminal Start

If double-clicking is blocked by macOS permissions, open Terminal in this folder and run:

```bash
open Talaria.app
```

The Python source, inputs folder, and assets are bundled inside `Talaria.app/Contents/Resources/app`.

## Setup

1. In Intervals.icu, create or copy your personal API key from settings.
2. Open the app's `Setup` tab.
3. Paste the API key.
4. Leave athlete id as `0` for your own account.
5. Click `Save`.
6. Click `Test key`.

The API key is saved locally in:

```text
~/Library/Application Support/Talaria/intervals_config.json
```

This keeps auth working when `Talaria.app` is moved to another folder.

## Upload Workouts

The app reads workout text files from:

```text
Talaria.app/Contents/Resources/app/inputs/intervals_workouts
```

The expected filename pattern is:

```text
YYYY-MM-DD_workout-name.txt
```

Examples:

```text
2027-03-14_easy-bike-45m.txt
2027-03-15_swim-technique.txt
2027-03-16_strength-upper-body.txt
2027-03-17_yoga-mobility.txt
```

The app infers the workout type from the filename, title, and workout text. It understands common words for ride, run, swim, strength training, walking, yoga/mobility, and rowing. Unknown workouts still appear as `Other`.

Select the workouts you want and click `Upload selected`.

Uploads are sent to:

```text
POST https://intervals.icu/api/v1/athlete/0/events/bulk?upsert=true
```

Each workout has a stable `external_id`, so re-running the upload updates existing planned workouts instead of creating duplicates.

## Progress Read

Choose a date range and click `Fetch summary`.

The app reads:

- completed activities
- recent activity details and intervals
- HR histograms, time-at-HR, and HR load model data where available
- power-vs-HR, decoupling, power/pace histograms, best efforts, and recent streams where available
- athlete curve context for HR, power, pace, and power-vs-HR
- wellness data such as sleep, sleep score, HRV, resting HR, readiness, fatigue, stress, soreness, nutrition, and steps if your key has access

Then it creates a plain-text summary you can copy into ChatGPT, Claude, or another AI. If the range has more than 25 completed activities, Talaria asks whether to also save the full report as Markdown in `Talaria.app/Contents/Resources/app/reports`.

Use `View reports` in the progress tab to open that folder.

## Moving The App

Keep `Talaria.app` intact when moving it. The app internals are bundled inside the package.

You need:

- Python 3
- an Intervals.icu account
- an Intervals.icu API key

You do not need to edit the code.
