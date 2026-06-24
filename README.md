# Talaria

Minimal local tools for Intervals.icu.

Talaria uploads plain-text workouts and turns completed Intervals.icu activity data into an AI-coach-ready training summary. It runs locally on macOS, keeps API keys on your machine, and uses the Intervals.icu API directly.

## What It Does

- Upload planned workouts from local `.txt` files.
- Read completed activities, HR/load signals, wellness, intervals, streams, weather, and curve context.
- Generate copyable coach summaries.
- Save long reports as local Markdown files.
- Open a native app first, with an optional web UI button.

## Requirements

- macOS
- Python 3 with Tkinter for the native app
- Intervals.icu API key

## Start

Double-click `Talaria.app`.

If macOS is awkward after moving the folder, double-click `Start Intervals Planner.command`.

## Privacy

Talaria has no hosted backend. Your API key is stored locally in:

```text
~/Library/Application Support/Talaria/intervals_config.json
```

Saved reports live inside:

```text
Talaria.app/Contents/Resources/app/reports
```
