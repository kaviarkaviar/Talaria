<img width="313" height="313" alt="talaria-logo" src="https://github.com/user-attachments/assets/ffd3f6ea-066c-47f6-b16e-3ca57a11363b" /><p align="center">

</p>

# Talaria

Local Intervals.icu tools for workout uploads and AI-ready training summaries.

Talaria is a small macOS app. It stores your API key locally, uploads workout text files to Intervals.icu, and reads completed activity/recovery data so you can paste useful context into an AI coach.

## Start

Double-click `Talaria.app`.

If macOS is awkward after moving the folder, double-click `Start Intervals Planner.command`.

`Talaria.app` opens the native local app. Use `Open Web App` in the top right only if you want the browser version.

## Setup

1. Create or copy your Intervals.icu API key from Intervals.icu settings.
2. Open Talaria.
3. Paste the key in `Setup`.
4. Leave athlete id as `0` for your own account.
5. Click `Save`, then `Test key`.

Your API key is stored locally:

```text
~/Library/Application Support/Talaria/intervals_config.json
```

## Upload Workouts

Put workout `.txt` files here:

```text
Talaria.app/Contents/Resources/app/inputs/intervals_workouts
```

Use this filename format:

```text
YYYY-MM-DD_workout-name.txt
```

Refer to [Intervals workout formatting](https://forum.intervals.icu/t/workout-builder-syntax-quick-guide/123701) for workout syntax.

Talaria infers workout type from the filename, title, and workout text. It recognises common ride, run, swim, strength, walk, yoga/mobility, and rowing wording. Re-uploading is safe: planned workouts use stable external ids and upsert.

## Progress Read

The default date range is the last 7 days through today. Change the dates if needed, then click `Fetch summary`.

Talaria reads completed activities, full activity detail for every activity in the range, intervals, HR/load data, streams, weather, best efforts, athlete curve context, and wellness fields when available.

The summary appears as copyable text. If there are more than 25 completed activities, Talaria asks whether to also save a Markdown report.

Saved reports live here:

```text
Talaria.app/Contents/Resources/app/reports
```

Use `View reports` to open that folder.

## Notes

- No hosted backend.
- No npm or package install.
- Keep the whole `Talaria` folder together when moving it.
- Python 3 with Tkinter is needed for the native app.
