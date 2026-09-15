#!/usr/bin/env python3
"""A window for Haldor: keep the mod list, install it, launch the game."""

import contextlib
import queue
import subprocess
import threading
import tkinter as tk
import tkinter.font as tkfont
import urllib.parse
from pathlib import Path

import haldor

# The terminal's own colors, dark. State is blue and amber rather than green and
# red, the way the daltonized theme next to this window has it.
BG, FG, BRIGHT, DIM, LINE = "#1e2029", "#a0b3cc", "#bdcde1", "#6a7488", "#2d3450"
BLUE, CYAN, AMBER, MAGENTA = "#6db1f7", "#56b6c2", "#e5c07b", "#c678dd"
PAD = 18
SOURCE = urllib.parse.urlsplit(haldor.API).hostname
# Enough of the game path to tell two Steam libraries apart, and no wider than
# the header.
KEEP = 4


def shorten(path: Path) -> str:
    parts = path.parts[-KEEP:]
    return ("…/" if len(path.parts) > KEEP else "") + "/".join(parts)


class App(tk.Frame):
    """A terminal pane. What to install on top, what happened below."""

    def __init__(self, master: tk.Tk):
        # MesloLGS NF is the terminal's font. Menlo is on every Mac.
        self.family = "MesloLGS NF" if "MesloLGS NF" in tkfont.families() else "Menlo"
        master.option_add("*Frame.background", BG)
        master.option_add("*Label.background", BG)
        master.option_add("*Label.foreground", FG)
        master.option_add("*Label.font", "{%s} -13" % self.family)
        super().__init__(master, bg=BG, padx=PAD, pady=14)

        self.messages: queue.Queue = queue.Queue()
        self.game = None
        self.running = None
        self.failure = None
        self.working = False
        self.active = False
        self.buttons: list = []
        self.published = ""
        self.modpack = tk.StringVar()
        self.version = tk.StringVar()
        self.where = tk.StringVar()
        self.status = tk.StringVar()

        master.title("Haldor")
        master.minsize(560, 520)
        master.configure(bg=BG)
        # The title bar is the system's, and follows the system appearance unless
        # asked not to. A terminal keeps its dark chrome in a light Mac, so does this.
        with contextlib.suppress(tk.TclError):
            master.tk.call("::tk::unsupported::MacWindowStyle", "appearance",
                           master, "darkaqua")
        master.bind("<Activate>", lambda e: self.light(True))
        master.bind("<Deactivate>", lambda e: self.light(False))
        self.pack(fill="both", expand=True)

        head = tk.Frame(self)
        head.pack(fill="x")
        tk.Label(head, text="haldor", fg=BRIGHT,
                 font=self.font(weight="bold")).pack(side="left")
        tk.Label(head, text=SOURCE, fg=CYAN).pack(side="right")
        tk.Label(head, textvariable=self.where, fg=DIM).pack(side="left", padx=(10, 0))
        tk.Frame(self, bg=LINE, height=1).pack(fill="x", pady=(10, 16))

        # The footer first, so a short window takes its space out of the log.
        self.foot()
        self.fields()
        self.bar()
        self.console = self.log()

        self.entry.focus_set()
        self.load()
        self.pump()

    def font(self, size: int = 13, weight: str = "normal") -> tuple:
        # Negative is pixels, and a macOS point is a pixel, so this matches the system
        # font beside it. Tk reads a positive size as a point at 96dpi, a third larger.
        return self.family, -size, weight

    # The window

    def prompt(self, label: str) -> tk.Frame:
        """A ❯ line, and the ruled space that its field sits in."""
        row = tk.Frame(self)
        row.pack(fill="x", pady=(0, 14))
        tk.Label(row, text="❯", fg=BLUE,
                 font=self.font(weight="bold")).pack(side="left", anchor="n")
        tk.Label(row, text=f" {label} ", fg=MAGENTA).pack(side="left", anchor="n")
        box = tk.Frame(row)
        box.pack(side="left", fill="x", expand=True)
        return box

    def fields(self) -> None:
        box = self.prompt("modpack")
        # Packed before the field, which expands into whatever is left over.
        self.button(box.master, "refresh", CYAN, self.do_refresh,
                    side="right", padx=(14, 0), before=box)
        tk.Label(box.master, textvariable=self.version, fg=DIM).pack(
            side="right", before=box)
        self.entry = tk.Entry(box, textvariable=self.modpack, font=self.font(),
                              bg=BG, fg=BRIGHT, relief="flat", highlightthickness=0,
                              insertbackground=BLUE, selectbackground=LINE,
                              selectforeground=BRIGHT)
        self.entry.pack(fill="x")
        self.entry.bind("<Return>", lambda e: self.do_install())
        tk.Frame(box, bg=LINE, height=1).pack(fill="x", pady=(4, 0))

        box = self.prompt("extras ")
        self.extras = tk.Text(box, height=3, font=self.font(), bg=BG, fg=BRIGHT,
                              relief="flat", highlightthickness=0, padx=0, pady=0,
                              wrap="none", insertbackground=BLUE,
                              selectbackground=LINE, selectforeground=BRIGHT)
        self.extras.pack(fill="x")
        tk.Frame(box, bg=LINE, height=1).pack(fill="x", pady=(4, 0))

    def bar(self) -> None:
        bar = tk.Frame(self)
        bar.pack(fill="x", pady=(2, 14))
        self.button(bar, "install", BLUE, self.do_install)
        self.button(bar, "play", CYAN, self.do_play)

    def button(self, bar: tk.Frame, text: str, color: str, command, **pack) -> None:
        """A bracketed word. Tk's own button takes no color on macOS."""
        button = tk.Label(bar, text=f"[ {text} ]", fg=color, cursor="pointinghand",
                          font=self.font(weight="bold"))
        button.pack(**{"side": "left", "padx": (0, 14), **pack})
        button.bind("<Button-1>", lambda e: None if self.working else command())
        button.bind("<Enter>", lambda e: self.light(self.active))
        button.bind("<Leave>", lambda e: self.light(self.active))
        self.buttons.append((button, color))

    def light(self, active: bool) -> None:
        """Light the word under the pointer, and only while the window is the
        active one. macOS keeps the click that activates a window, so a
        background window that answers the pointer promises a click it eats.
        """
        self.active = active
        under = self.winfo_containing(self.winfo_pointerx(), self.winfo_pointery())
        for button, color in self.buttons:
            button.configure(fg=DIM if self.working else
                             BRIGHT if active and button is under else color)

    def log(self) -> tk.Text:
        out = tk.Text(self, font=self.font(12), bg=BG, fg=FG, relief="flat",
                      highlightthickness=1, highlightbackground=LINE,
                      highlightcolor=LINE, padx=10, pady=8, wrap="none",
                      state="disabled", selectbackground=LINE,
                      selectforeground=BRIGHT)
        out.pack(fill="both", expand=True)
        out.tag_configure("step", foreground=BRIGHT)
        out.tag_configure("detail", foreground=DIM)
        out.tag_configure("error", foreground=AMBER)
        # Configured last, so the dot keeps its color on a step line.
        out.tag_configure("dot", foreground=BLUE)
        return out

    def foot(self) -> None:
        foot = tk.Frame(self)
        foot.pack(side="bottom", fill="x", pady=(12, 0))
        self.dot = tk.Label(foot, text="●", fg=BLUE, font=self.font(11))
        self.dot.pack(side="left")
        tk.Label(foot, textvariable=self.status, fg=DIM,
                 font=self.font(12)).pack(side="left", padx=(6, 0))
        tk.Label(foot, text=f"arm64 · BepInEx {haldor.BEPINEX_VERSION}", fg=DIM,
                 font=self.font(11)).pack(side="right")

    def load(self) -> None:
        """Fill the window from the install, if there is one."""
        try:
            self.game = haldor.game_dir()
        except haldor.HaldorError as e:
            self.failure = str(e)
            return self.busy(True, str(e))
        self.where.set(shorten(self.game))
        try:
            installed = haldor.state()
        except haldor.NotInstalled:
            return self.busy(False, "nothing installed yet")
        self.modpack.set(installed["pack"])
        self.show_version()
        self.extras.insert("1.0", "\n".join(installed.get("extras", [])))
        self.say("⏺ Installed\n" + "".join(f"  ⎿  {mod}\n" for mod in installed["mods"]))
        self.busy(False, "ready")

    def show_version(self) -> None:
        """What is installed, and what a refresh found published beyond it."""
        try:
            here = haldor.state().get("version", "")
        except haldor.HaldorError:
            here = ""
        if self.published and self.published != here:
            self.version.set(f"{here} → {self.published}" if here else self.published)
        else:
            self.version.set(here)

    # What the buttons do

    def do_install(self) -> None:
        if self.playing():
            return self.status.set("quit the game first")
        pack = self.modpack.get().strip()
        if not pack:
            return self.status.set("name a modpack, such as MahMods/Trollheim")
        # Read the list here. The worker thread must not touch a widget.
        extras = self.extras.get("1.0", "end").split()
        self.clear()
        self.work(lambda log: haldor.install(pack, extras, log), "installing…")

    def do_refresh(self) -> None:
        """What Thunderstore publishes for the pack now, against what is laid down."""
        pack = self.modpack.get().strip()
        if not pack:
            return self.status.set("name a modpack, such as MahMods/Trollheim")

        def check(log) -> None:
            self.published = haldor.newest(pack)
            log(f"⏺ {pack} {self.published} is published")

        self.work(check, "checking…")

    def do_play(self) -> None:
        if self.playing():
            # A second one starts happily and helps nobody, so raise the first.
            subprocess.run(["open", "-a", str(self.game / "valheim.app")], check=False)
            return self.status.set("Valheim is already running")
        script = self.game / "run_bepinex.sh"
        if not script.exists():
            return self.status.set("install first")
        self.running = subprocess.Popen(["/bin/sh", script.name], cwd=script.parent,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # The buttons stay live while the game runs. Only a job takes them away.
        self.dot.configure(fg=CYAN)
        self.status.set("Valheim is running")
        self.wait()

    def playing(self) -> bool:
        return self.running is not None and self.running.poll() is None

    def wait(self) -> None:
        if self.playing():
            return self.after(1000, self.wait)
        self.busy(False, "ready")

    # Running a job without freezing the window

    def work(self, job, status: str) -> None:
        """Run the job off the main thread, the lines it logs going to the log."""
        self.failure = None
        self.busy(True, status)

        def run() -> None:
            def line(text: str) -> None:
                self.messages.put(text + "\n")

            try:
                job(line)
            except haldor.HaldorError as e:
                self.failure = str(e)
            except Exception as e:
                self.failure = f"{type(e).__name__}: {e}"
            if self.failure:
                line(f"✗ {self.failure}")
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
                self.show_version()
                self.busy(False, self.failure or "ready")
            else:
                self.say(message)
        self.after(100, self.pump)

    # Chrome

    def busy(self, working: bool, status: str) -> None:
        self.working = working
        self.light(self.active)
        self.dot.configure(fg=AMBER if self.failure else CYAN if working else BLUE)
        self.status.set(status)

    def clear(self) -> None:
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")

    def say(self, text: str) -> None:
        """Write to the log, a step line and its details telling themselves apart."""
        self.console.configure(state="normal")
        first = int(self.console.index("end-1c").split(".")[0])
        self.console.insert("end", text)
        for line in range(first, int(self.console.index("end-1c").split(".")[0]) + 1):
            head = self.console.get(f"{line}.0")
            if head == "⏺":
                self.console.tag_add("step", f"{line}.0", f"{line}.end")
                self.console.tag_add("dot", f"{line}.0", f"{line}.1")
            elif head == " ":
                self.console.tag_add("detail", f"{line}.0", f"{line}.end")
            elif head == "✗":
                self.console.tag_add("error", f"{line}.0", f"{line}.end")
        self.console.see("end")
        self.console.configure(state="disabled")


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
