# Talaria

This folder contains:

- a native desktop app for uploading workouts to Intervals.icu
- a macOS app wrapper at `Talaria.app`
- bundled Python code, inputs, and assets inside the app package

## Easiest Start

Double-click:

```text
Start Intervals Planner.command
```

The launcher runs the bundled Talaria app from wherever this folder currently lives. You can move the whole `Talaria` folder, including into folders with spaces in their names.

If macOS blocks the launcher, open Terminal in this folder and run:

```bash
open Talaria.app
```

If the app wrapper does not open after moving the folder, double-click `Start Intervals Planner.command`; it uses a more direct launch path.

`Talaria.app` opens the native local app. Use `Open Web App` in the top right of Talaria only if you want the browser version.

## Setup

1. Open the app.
2. Paste your Intervals.icu API key in the `Setup` tab.
3. Leave athlete id as `0` unless you know you need a different athlete id.
4. Click `Save`.
5. Click `Test key`.

The API key is saved in your user settings at `~/Library/Application Support/Talaria/intervals_config.json`. This means auth stays working if you move `Talaria.app` to another folder.

## Add Workouts

Put any Intervals.icu workout `.txt` files into:

```text
Talaria.app/Contents/Resources/app/inputs/intervals_workouts
```

The app reads those folders automatically. The expected filename pattern is:

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

The app infers the workout type from the filename, title, and workout text. It understands common words for ride, run, swim, strength training, walking, yoga/mobility, and rowing.

The Python code, inputs folder, and assets live inside `Talaria.app/Contents/Resources/app`.
