#!/usr/bin/env python3
"""A window for Haldor: keep the mod list, install it, launch the game."""

import contextlib
import io
import queue
import subprocess
import threading
import tkinter as tk
import urllib.parse
from tkinter import ttk

import haldor

PAD = 16
SOURCE = urllib.parse.urlsplit(haldor.API).hostname


class Relay(io.TextIOBase):
    """Stands in for stdout while a job runs, handing its text to the window."""

    def __init__(self, out: queue.Queue):
        self.out = out

    def write(self, text: str) -> int:
        self.out.put(text)
        return len(text)


class App(ttk.Frame):
    """The mod list on top, what Haldor is saying below."""

    def __init__(self, master: tk.Tk):
        super().__init__(master, padding=PAD)
        self.messages: queue.Queue = queue.Queue()
        self.game = None
        self.failure = None
        self.pack = tk.StringVar()
        self.status = tk.StringVar()

        master.title("Haldor")
        master.minsize(520, 480)
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)
        self.grid(sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(5, weight=1)
        self.rowconfigure(8, weight=2)

        ttk.Label(self, text="Source").grid(row=0, column=0, sticky="w")
        # Thunderstore is the only index Haldor reads. The host comes off the
        # API so the list cannot drift from it.
        source = ttk.Combobox(self, values=[SOURCE], state="readonly", width=16)
        source.current(0)
        source.grid(row=1, column=0, sticky="w", pady=(4, PAD))

        ttk.Label(self, text="Modpack").grid(row=2, column=0, sticky="w")
        entry = ttk.Entry(self, textvariable=self.pack)
        entry.grid(row=3, column=0, sticky="ew", pady=(4, PAD))

        ttk.Label(self, text="Extras, one namespace/name per line").grid(row=4, column=0, sticky="w")
        self.extras = self.text(height=5)
        self.extras.grid(row=5, column=0, sticky="nsew", pady=(4, PAD))

        bar = ttk.Frame(self)
        bar.grid(row=6, column=0, sticky="ew")
        bar.columnconfigure(1, weight=1)
        self.install = ttk.Button(bar, text="Install", command=self.do_install)
        self.install.grid(row=0, column=0)
        self.launch = ttk.Button(bar, text="Play", command=self.do_play)
        self.launch.grid(row=0, column=2)

        ttk.Separator(self).grid(row=7, column=0, sticky="ew", pady=PAD)
        self.console = self.text(height=10, wrap="word",
                                 font="TkFixedFont", state="disabled")
        self.console.grid(row=8, column=0, sticky="nsew")
        ttk.Label(self, textvariable=self.status).grid(row=9, column=0, sticky="w", pady=(PAD, 0))

        entry.focus_set()
        self.load()
        self.pump()

    def text(self, **kw) -> tk.Text:
        """A text box that sits flat in the layout."""
        return tk.Text(self, relief="flat", padx=8, pady=6,
                       highlightthickness=1, **kw)

    def load(self) -> None:
        """Fill the list from the install, if there is one."""
        try:
            self.game = haldor.game_dir()
        except SystemExit as e:
            self.busy(True, str(e))
            return
        try:
            installed = haldor.state()
        except FileNotFoundError:
            return self.status.set("Nothing installed yet")
        self.pack.set(installed["pack"])
        self.extras.insert("1.0", "\n".join(installed.get("extras", [])))
        self.say("\n".join(installed["mods"]) + "\n")
        self.status.set("Ready")

    # What the buttons do

    def do_install(self) -> None:
        pack = self.pack.get().strip()
        if not pack:
            return self.status.set("Name a modpack, such as MahMods/Trollheim")
        # Read the list here. The worker thread must not touch a widget.
        extras = self.extras.get("1.0", "end").split()
        self.work(lambda: haldor.install(pack, extras))

    def do_play(self) -> None:
        script = self.game / "run_bepinex.sh"
        if not script.exists():
            return self.status.set("Install first")
        game = subprocess.Popen(["/bin/sh", script.name], cwd=script.parent,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.busy(True, "Valheim is running")
        self.wait(game)

    def wait(self, game: subprocess.Popen) -> None:
        if game.poll() is None:
            return self.after(1000, self.wait, game)
        self.busy(False, "Ready")

    # Running a job without freezing the window

    def work(self, job) -> None:
        """Run the job off the main thread, its output replacing the console."""
        self.busy(True, "Installing…")
        self.failure = None
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")

        def run() -> None:
            relay = Relay(self.messages)
            try:
                with contextlib.redirect_stdout(relay):
                    job()
            except (Exception, SystemExit) as e:
                self.failure = f"{type(e).__name__}: {e}"
                relay.write(self.failure + "\n")
            self.messages.put(None)

        threading.Thread(target=run, daemon=True).start()

    def pump(self) -> None:
        """Drain what the job said. Only this thread touches a widget."""
        while True:
            try:
                message = self.messages.get_nowait()
            except queue.Empty:
                break
            if message is None:
                self.busy(False, self.failure or "Ready")
            else:
                self.say(message)
        self.after(100, self.pump)

    # Chrome

    def busy(self, working: bool, status: str) -> None:
        for button in (self.install, self.launch):
            button.state(["disabled" if working else "!disabled"])
        self.status.set(status)

    def say(self, text: str) -> None:
        self.console.configure(state="normal")
        self.console.insert("end", text)
        self.console.see("end")
        self.console.configure(state="disabled")


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
