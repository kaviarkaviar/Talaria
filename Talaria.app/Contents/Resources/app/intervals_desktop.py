#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from pathlib import Path

import intervals_gui


class IntervalsDesktopApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Talaria")
        self.geometry("1140x780")
        self.minsize(1040, 700)

        self.config_data = intervals_gui.load_config()
        self.workouts = intervals_gui.workout_files()
        self.visible_workouts: list[dict[str, object]] = []
        self.sort_column = "date"
        self.sort_descending = False
        self.last_upload: list[dict[str, object]] = []
        self.logo_image = None
        self.header_logo = None

        self._build_styles()
        self._load_logo()
        self._build_ui()
        self.center_window()

    def _load_logo(self) -> None:
        logo_path = intervals_gui.ROOT / "assets" / "talaria-logo.png"
        if not logo_path.exists():
            return
        try:
            self.logo_image = tk.PhotoImage(file=str(logo_path))
            self.iconphoto(True, self.logo_image)
            self.header_logo = self.logo_image.subsample(16, 16)
        except tk.TclError:
            self.logo_image = None
            self.header_logo = None

    def _build_styles(self) -> None:
        self.style = ttk.Style(self)
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass
        self.configure(background="#f4f6f8")
        self.style.configure("TFrame", background="#f4f6f8")
        self.style.configure("Panel.TFrame", background="#ffffff")
        self.style.configure("TLabel", background="#f4f6f8", foreground="#1f2933")
        self.style.configure("Panel.TLabel", background="#ffffff", foreground="#20211f")
        self.style.configure("Muted.TLabel", foreground="#64748b")
        self.style.configure("TButton", padding=(11, 7), borderwidth=1)
        self.style.configure("Accent.TButton", padding=(11, 7), background="#176b5f", foreground="#ffffff")
        self.style.map("Accent.TButton", background=[("active", "#145b51")])
        self.style.configure("TNotebook", background="#f4f6f8", borderwidth=0)
        self.style.configure("TNotebook.Tab", padding=(14, 8), background="#e9eef3")
        self.style.map("TNotebook.Tab", background=[("selected", "#ffffff")])
        self.style.configure("TEntry", padding=(6, 5))
        self.style.configure("TCombobox", padding=(6, 5))
        self.style.configure("Treeview", rowheight=28, background="#ffffff", fieldbackground="#ffffff", foreground="#1f2933")
        self.style.configure("Treeview.Heading", padding=(8, 6), background="#edf2f7", foreground="#1f2933")
        self.style.configure("Vertical.TScrollbar", background="#d7dee6")

    def center_window(self) -> None:
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = max(0, (self.winfo_screenwidth() - width) // 2)
        y = max(0, (self.winfo_screenheight() - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=16)
        root.pack(fill="both", expand=True)

        header = ttk.Frame(root)
        header.pack(fill="x", pady=(0, 14))
        if self.header_logo:
            ttk.Label(header, image=self.header_logo).pack(side="left", padx=(0, 10))
            text_header = ttk.Frame(header)
            text_header.pack(side="left", fill="x", expand=True)
        else:
            text_header = header
        ttk.Label(text_header, text="Talaria", font=("Helvetica", 20, "bold")).pack(anchor="w")
        ttk.Label(
            text_header,
            text="Upload workouts and copy completed-training context for your AI coach.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(4, 0))
        ttk.Button(header, text="Open Web App", command=self.open_web_app).pack(side="right")
        self.undo_button = ttk.Button(header, text="Undo upload", command=self.undo_last_upload)
        self.undo_button.pack(side="right", padx=(0, 8))

        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True)

        self.setup_tab = ttk.Frame(notebook, padding=14)
        self.upload_tab = ttk.Frame(notebook, padding=14)
        self.progress_tab = ttk.Frame(notebook, padding=14)
        notebook.add(self.setup_tab, text="Setup")
        notebook.add(self.upload_tab, text="Upload Workouts")
        notebook.add(self.progress_tab, text="Progress Read")

        self._build_setup_tab()
        self._build_upload_tab()
        self._build_progress_tab()

    def _build_setup_tab(self) -> None:
        ttk.Label(self.setup_tab, text="Intervals.icu API key", font=("Helvetica", 14, "bold")).pack(anchor="w")
        ttk.Label(
            self.setup_tab,
            text="Paste your Intervals.icu API key. Athlete id can usually stay as 0.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(4, 12))

        form = ttk.Frame(self.setup_tab)
        form.pack(fill="x", pady=(0, 12))

        ttk.Label(form, text="API key").grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.api_key_var = tk.StringVar(value=str(self.config_data.get("api_key") or ""))
        api_entry = ttk.Entry(form, textvariable=self.api_key_var, width=48)
        api_entry.grid(row=1, column=0, sticky="ew", padx=(0, 12))

        ttk.Label(form, text="Athlete id").grid(row=0, column=1, sticky="w", pady=(0, 6))
        self.athlete_id_var = tk.StringVar(value=str(self.config_data.get("athlete_id") or "0"))
        ttk.Entry(form, textvariable=self.athlete_id_var, width=18).grid(row=1, column=1, sticky="ew")
        form.columnconfigure(0, weight=1)

        button_row = ttk.Frame(self.setup_tab)
        button_row.pack(fill="x", pady=(4, 12))
        ttk.Button(button_row, text="Save", command=self.save_config, style="Accent.TButton").pack(side="left")
        ttk.Button(button_row, text="Test key", command=self.test_key).pack(side="left", padx=(8, 0))

        saved = "Saved API key present." if self.config_data.get("api_key") else "No API key saved yet."
        self.setup_status = tk.StringVar(value=saved)
        ttk.Label(self.setup_tab, textvariable=self.setup_status, style="Muted.TLabel", wraplength=760).pack(anchor="w")

        note = (
            "Settings are stored in ~/Library/Application Support/Talaria. "
            "They stay saved when Talaria is moved to another folder."
        )
        ttk.Label(self.setup_tab, text=note, style="Muted.TLabel", wraplength=720).pack(anchor="w", pady=(20, 0))

    def _build_upload_tab(self) -> None:
        top = ttk.Frame(self.upload_tab)
        top.pack(fill="x", pady=(0, 10))
        self.workout_count_var = tk.StringVar(value=f"{len(self.workouts)} workouts found")
        ttk.Label(top, textvariable=self.workout_count_var, font=("Helvetica", 14, "bold")).pack(side="left")

        action_row = ttk.Frame(self.upload_tab)
        action_row.pack(fill="x", pady=(0, 10))
        ttk.Button(action_row, text="Upload selected", command=self.upload_selected, style="Accent.TButton").pack(side="left")
        ttk.Button(action_row, text="Delete local files", command=self.delete_selected_local).pack(side="left", padx=(8, 0))
        ttk.Button(action_row, text="Refresh", command=self.refresh_workouts).pack(side="left", padx=(8, 0))
        ttk.Button(action_row, text="Future only", command=self.select_future).pack(side="left", padx=(8, 0))
        ttk.Button(action_row, text="Select all", command=self.select_all).pack(side="left", padx=(8, 0))
        ttk.Button(action_row, text="Clear", command=self.clear_selection).pack(side="left", padx=(8, 0))
        ttk.Label(action_row, text="Sport", style="Muted.TLabel").pack(side="right")
        self.sport_filter_var = tk.StringVar(value="All")
        self.sport_filter = ttk.Combobox(action_row, textvariable=self.sport_filter_var, state="readonly", width=16)
        self.sport_filter.pack(side="right", padx=(0, 8))
        self.sport_filter.bind("<<ComboboxSelected>>", lambda _: self.render_workouts())

        panes = ttk.PanedWindow(self.upload_tab, orient="horizontal")
        panes.pack(fill="both", expand=True)

        folder_panel = ttk.Frame(panes)
        panes.add(folder_panel, weight=1)
        ttk.Label(folder_panel, text="Workout folders", style="Muted.TLabel").pack(anchor="w", pady=(0, 6))
        self.folder_tree = ttk.Treeview(folder_panel, show="tree", selectmode="browse", height=14)
        folder_scroll = ttk.Scrollbar(folder_panel, orient="vertical", command=self.folder_tree.yview)
        self.folder_tree.configure(yscrollcommand=folder_scroll.set)
        self.folder_tree.pack(side="left", fill="both", expand=True)
        folder_scroll.pack(side="right", fill="y")

        table_panel = ttk.Frame(panes)
        panes.add(table_panel, weight=4)
        columns = ("date", "type", "name", "filename")
        self.workout_table = ttk.Treeview(table_panel, columns=columns, show="headings", selectmode="extended", height=14)
        headings = {"date": "Date", "type": "Sport", "name": "Workout", "filename": "File"}
        widths = {"date": 104, "type": 120, "name": 300, "filename": 280}
        for column in columns:
            self.workout_table.heading(column, text=headings[column], command=lambda c=column: self.sort_workouts(c))
            self.workout_table.column(column, width=widths[column], minwidth=80, anchor="w")
        table_scroll_y = ttk.Scrollbar(table_panel, orient="vertical", command=self.workout_table.yview)
        table_scroll_x = ttk.Scrollbar(table_panel, orient="horizontal", command=self.workout_table.xview)
        self.workout_table.configure(yscrollcommand=table_scroll_y.set, xscrollcommand=table_scroll_x.set)
        self.workout_table.grid(row=0, column=0, sticky="nsew")
        table_scroll_y.grid(row=0, column=1, sticky="ns")
        table_scroll_x.grid(row=1, column=0, sticky="ew")
        table_panel.rowconfigure(0, weight=1)
        table_panel.columnconfigure(0, weight=1)
        self.workout_table.bind("<MouseWheel>", self.scroll_workout_table)
        self.workout_table.bind("<Shift-MouseWheel>", self.scroll_workout_table_horizontal)
        self.folder_tree.bind("<MouseWheel>", self.scroll_folder_tree)

        self.update_sport_filter_options()
        self.render_folder_tree()
        self.render_workouts()

        self.upload_status = tk.StringVar(value="Ready.")
        bottom_row = ttk.Frame(self.upload_tab)
        bottom_row.pack(fill="x", pady=(10, 0))
        ttk.Label(bottom_row, textvariable=self.upload_status, style="Muted.TLabel").pack(side="left", fill="x", expand=True)
        ttk.Button(bottom_row, text="Open workout folder", command=self.open_workout_folder).pack(side="right")

    def render_workouts(self) -> None:
        selected_ids = set(self.workout_table.selection()) if hasattr(self, "workout_table") else set()
        sport = self.sport_filter_var.get() if hasattr(self, "sport_filter_var") else "All"
        workouts = [workout for workout in self.workouts if sport == "All" or workout["type"] == sport]
        workouts.sort(key=lambda item: str(item.get(self.sort_column, "")), reverse=self.sort_descending)
        self.visible_workouts = workouts
        self.workout_table.delete(*self.workout_table.get_children())
        for workout in workouts:
            values = (workout["date"], workout["type"], workout["name"], workout["filename"])
            self.workout_table.insert("", "end", iid=str(workout["id"]), values=values)
        keep_selected = [item for item in selected_ids if self.workout_table.exists(item)]
        if keep_selected:
            self.workout_table.selection_set(keep_selected)
        self.workout_count_var.set(f"{len(workouts)} shown, {len(self.workouts)} total")

    def render_folder_tree(self) -> None:
        self.folder_tree.delete(*self.folder_tree.get_children())
        root_id = "root"
        self.folder_tree.insert("", "end", iid=root_id, text=f"intervals_workouts ({len(self.workouts)})", open=True)
        file_counts: dict[str, int] = {}
        for workout in self.workouts:
            file_counts[str(workout["filename"])] = file_counts.get(str(workout["filename"]), 0) + 1
        node_ids = {".": root_id}
        for filename, count in sorted(file_counts.items()):
            parts = Path(filename).parts
            parent_key = "."
            for part in parts[:-1]:
                key = f"{parent_key}/{part}"
                if key not in node_ids:
                    node_ids[key] = key
                    self.folder_tree.insert(node_ids[parent_key], "end", iid=key, text=part, open=True)
                parent_key = key
            label = parts[-1]
            if count > 1:
                label = f"{label} ({count})"
            self.folder_tree.insert(node_ids[parent_key], "end", text=label)

    def update_sport_filter_options(self) -> None:
        sports = ["All"] + sorted({str(workout["type"]) for workout in self.workouts})
        current = self.sport_filter_var.get() if hasattr(self, "sport_filter_var") else "All"
        self.sport_filter.configure(values=sports)
        self.sport_filter_var.set(current if current in sports else "All")

    def sort_workouts(self, column: str) -> None:
        if self.sort_column == column:
            self.sort_descending = not self.sort_descending
        else:
            self.sort_column = column
            self.sort_descending = False
        self.render_workouts()

    def scroll_units(self, event: tk.Event) -> int:
        delta = getattr(event, "delta", 0)
        if delta == 0:
            return 0
        if abs(delta) < 120:
            return -1 if delta > 0 else 1
        return int(-1 * (delta / 120))

    def scroll_workout_table(self, event: tk.Event) -> str:
        self.workout_table.yview_scroll(self.scroll_units(event), "units")
        return "break"

    def scroll_workout_table_horizontal(self, event: tk.Event) -> str:
        self.workout_table.xview_scroll(self.scroll_units(event), "units")
        return "break"

    def scroll_folder_tree(self, event: tk.Event) -> str:
        self.folder_tree.yview_scroll(self.scroll_units(event), "units")
        return "break"

    def refresh_workouts(self) -> None:
        self.workouts = intervals_gui.workout_files()
        self.update_sport_filter_options()
        self.render_folder_tree()
        self.render_workouts()
        self.upload_status.set("Workout folder refreshed.")

    def _build_progress_tab(self) -> None:
        controls = ttk.Frame(self.progress_tab)
        controls.pack(fill="x", pady=(0, 12))

        today = intervals_gui.date.today()
        oldest = today - intervals_gui.timedelta(days=7)
        newest = today

        ttk.Label(controls, text="Oldest").pack(side="left")
        self.oldest_var = tk.StringVar(value=oldest.isoformat())
        ttk.Entry(controls, textvariable=self.oldest_var, width=14).pack(side="left", padx=(6, 14))

        ttk.Label(controls, text="Newest").pack(side="left")
        self.newest_var = tk.StringVar(value=newest.isoformat())
        ttk.Entry(controls, textvariable=self.newest_var, width=14).pack(side="left", padx=(6, 14))

        ttk.Button(controls, text="Fetch summary", command=self.fetch_progress).pack(side="left")
        ttk.Button(controls, text="Copy", command=self.copy_summary).pack(side="left", padx=(8, 0))

        self.summary_text = tk.Text(
            self.progress_tab,
            wrap="word",
            height=22,
            padx=12,
            pady=12,
            background="#ffffff",
            foreground="#1f2933",
            insertbackground="#1f2933",
            relief="solid",
            borderwidth=1,
        )
        self.summary_text.pack(fill="both", expand=True)

        bottom_row = ttk.Frame(self.progress_tab)
        bottom_row.pack(fill="x", pady=(10, 0))
        self.progress_status = tk.StringVar(value="Ready.")
        ttk.Label(bottom_row, textvariable=self.progress_status, style="Muted.TLabel").pack(side="left", fill="x", expand=True)
        ttk.Button(bottom_row, text="View reports", command=self.view_reports).pack(side="right")

    def save_config(self) -> None:
        update = {"athlete_id": self.athlete_id_var.get().strip() or "0"}
        if self.api_key_var.get().strip():
            update["api_key"] = self.api_key_var.get().strip()
        intervals_gui.save_config(update)
        self.config_data = intervals_gui.load_config()
        self.setup_status.set("Saved locally.")

    def run_background(self, status_var: tk.StringVar, loading: str, fn) -> None:
        status_var.set(loading)

        def worker() -> None:
            try:
                result = fn()
                self.after(0, lambda: status_var.set(result))
            except Exception as exc:
                self.after(0, lambda: status_var.set(f"Error: {exc}"))

        threading.Thread(target=worker, daemon=True).start()

    def test_key(self) -> None:
        self.save_config()

        def task() -> str:
            config = intervals_gui.load_config()
            athlete_id = config.get("athlete_id", "0") or "0"
            intervals_gui.intervals_request(
                "GET",
                f"/athlete/{athlete_id}/activities",
                config.get("api_key", ""),
                query={"oldest": intervals_gui.date.today().isoformat(), "newest": intervals_gui.date.today().isoformat()},
            )
            return "API key works. Activity read succeeded."

        self.run_background(self.setup_status, "Testing API key...", task)

    def select_all(self) -> None:
        self.workout_table.selection_set(self.workout_table.get_children())

    def clear_selection(self) -> None:
        self.workout_table.selection_remove(self.workout_table.selection())

    def select_future(self) -> None:
        today = intervals_gui.date.today().isoformat()
        future_ids = [str(workout["id"]) for workout in self.visible_workouts if str(workout["date"]) >= today]
        self.workout_table.selection_set(future_ids)

    def delete_selected_local(self) -> None:
        selected = list(self.workout_table.selection())
        if not selected:
            messagebox.showinfo("No workouts selected", "Select at least one local workout file first.")
            return
        files = sorted({str(workout["filename"]) for workout in self.workouts if workout["id"] in selected})
        if not messagebox.askyesno(
            "Delete local workout files?",
            f"Delete {len(files)} local .txt/.md file(s) from the workout folder? This will not delete anything from Intervals.icu.",
        ):
            return
        removed = intervals_gui.delete_workout_files(selected)
        self.refresh_workouts()
        self.upload_status.set(f"Deleted {len(removed)} local workout file(s).")

    def upload_selected(self) -> None:
        selected = list(self.workout_table.selection())
        if not selected:
            messagebox.showinfo("No workouts selected", "Select at least one workout first.")
            return

        def task() -> str:
            config = intervals_gui.load_config()
            athlete_id = config.get("athlete_id", "0") or "0"
            events = intervals_gui.selected_events(selected)
            response = intervals_gui.intervals_request(
                "POST",
                f"/athlete/{athlete_id}/events/bulk",
                config.get("api_key", ""),
                body=events,
                query={"upsert": "true"},
            )
            self.remember_upload(events, response)
            count = len(response) if isinstance(response, list) else len(events)
            return f"Uploaded or updated {count} planned workouts."

        self.run_background(self.upload_status, f"Uploading {len(selected)} workouts...", task)

    def remember_upload(self, events: list[dict[str, object]], response: object) -> None:
        uploaded: list[dict[str, object]] = []
        response_items = response if isinstance(response, list) else []
        if response_items:
            for index, event in enumerate(events):
                returned = response_items[index] if index < len(response_items) and isinstance(response_items[index], dict) else {}
                uploaded.append({**event, "id": returned.get("id") or returned.get("event_id")})
        else:
            uploaded = events
        self.last_upload = uploaded

    def undo_last_upload(self) -> None:
        if not self.last_upload:
            messagebox.showinfo("Nothing to undo", "Talaria can undo the most recent workout upload from this session.")
            return
        if not messagebox.askyesno(
            "Undo last upload?",
            f"Delete {len(self.last_upload)} planned workout event(s) from Intervals.icu?",
        ):
            return

        def task() -> str:
            config = intervals_gui.load_config()
            athlete_id = config.get("athlete_id", "0") or "0"
            api_key = config.get("api_key", "")
            events = list(self.last_upload)
            oldest, newest = intervals_gui.date_range_for_events(events)
            calendar_events = intervals_gui.intervals_request(
                "GET",
                f"/athlete/{athlete_id}/events",
                api_key,
                query={"oldest": oldest, "newest": newest},
            ) or []
            by_external = {
                str(event.get("external_id")): str(event.get("id") or event.get("event_id"))
                for event in calendar_events
                if event.get("external_id") and (event.get("id") or event.get("event_id"))
            }
            deleted = 0
            missing = 0
            for event in events:
                event_id = event.get("id") or by_external.get(str(event.get("external_id")))
                if not event_id:
                    missing += 1
                    continue
                intervals_gui.delete_event(athlete_id, api_key, str(event_id))
                deleted += 1
            self.last_upload = []
            detail = f" Deleted {deleted} planned workout event(s) from Intervals.icu."
            if missing:
                detail += f" Could not find {missing} event id(s) to delete."
            return detail.strip()

        self.run_background(self.upload_status, "Undoing last upload...", task)

    def fetch_progress(self) -> None:
        self.progress_status.set("Fetching Intervals.icu data...")

        def worker() -> None:
            try:
                config = intervals_gui.load_config()
                athlete_id = config.get("athlete_id", "0") or "0"
                api_key = config.get("api_key", "")
                oldest = self.oldest_var.get().strip()
                newest = self.newest_var.get().strip()
                params = {"oldest": oldest, "newest": newest}
                activities = intervals_gui.intervals_request("GET", f"/athlete/{athlete_id}/activities", api_key, query=params) or []
                events = []
                try:
                    wellness = intervals_gui.intervals_request("GET", f"/athlete/{athlete_id}/wellness", api_key, query=params) or []
                except Exception:
                    wellness = []
                activity_enrichment = intervals_gui.fetch_activity_enrichment(activities, api_key)
                fitness_events = intervals_gui.fetch_fitness_model_events(athlete_id, api_key)
                curve_context = intervals_gui.fetch_athlete_curve_context(athlete_id, api_key, oldest, newest)
                athlete_context = intervals_gui.fetch_athlete_context(athlete_id, api_key, oldest, newest)
                summary = intervals_gui.build_progress_summary(
                    activities,
                    events,
                    wellness,
                    oldest,
                    newest,
                    activity_enrichment=activity_enrichment,
                    fitness_events=fitness_events,
                    curve_context=curve_context,
                    athlete_context=athlete_context,
                )
                result = {
                    "summary": summary,
                    "oldest": oldest,
                    "newest": newest,
                    "activity_count": len(activities),
                    "wellness_count": len(wellness),
                    "fitness_count": len(fitness_events),
                    "context_count": sum(1 for value in athlete_context.values() if value),
                }
                self.after(0, lambda: self.handle_progress_result(result))
            except Exception as exc:
                self.after(0, lambda: self.progress_status.set(f"Error: {exc}"))

        threading.Thread(target=worker, daemon=True).start()

    def handle_progress_result(self, result: dict[str, object]) -> None:
        summary = str(result["summary"])
        self.set_summary(summary)
        activity_count = int(result["activity_count"])
        message = (
            f"Fetched {activity_count} activities, "
            f"{result['wellness_count']} wellness records, {result['fitness_count']} fitness/load events, "
            f"{result['context_count']} context groups."
        )
        if activity_count > 25:
            should_save = messagebox.askyesno(
                "Save Markdown report?",
                (
                    f"Talaria fetched {activity_count} completed activities. "
                    "Do you want to also save the full summary as a Markdown file?"
                ),
            )
            if should_save:
                path = intervals_gui.save_markdown_report(summary, str(result["oldest"]), str(result["newest"]))
                message += f" Markdown report saved to {path}."
            else:
                message += " Markdown save skipped; the text summary is still shown here."
        self.progress_status.set(message)

    def set_summary(self, summary: str) -> None:
        self.summary_text.delete("1.0", "end")
        self.summary_text.insert("1.0", summary)

    def copy_summary(self) -> None:
        text = self.summary_text.get("1.0", "end").strip()
        self.clipboard_clear()
        self.clipboard_append(text)
        self.progress_status.set("Copied summary to clipboard.")

    def view_reports(self) -> None:
        path = intervals_gui.open_reports_folder()
        self.progress_status.set(f"Opened reports folder: {path}")

    def open_workout_folder(self) -> None:
        path = intervals_gui.open_workout_folder()
        self.upload_status.set(f"Opened workout folder: {path}")

    def open_web_app(self) -> None:
        env = os.environ.copy()
        env["TALARIA_ROOT"] = str(intervals_gui.ROOT)
        env["TALARIA_OPEN_BROWSER"] = "1"
        log_path = intervals_gui.ROOT / "talaria-web.log"
        log_file = log_path.open("a", encoding="utf-8")
        subprocess.Popen(
            [sys.executable, str(intervals_gui.ROOT / "intervals_gui.py")],
            cwd=str(intervals_gui.ROOT),
            env=env,
            stdout=log_file,
            stderr=log_file,
            start_new_session=True,
        )
        self.progress_status.set("Opening web app in your browser.")


if __name__ == "__main__":
    app = IntervalsDesktopApp()
    app.mainloop()
