import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import tkinter.font as tkfont
import threading
import queue
import time
from pathlib import Path
import serial
from serial.tools import list_ports

BAUD_RATE = 115200
MAX_MESSAGE_LENGTH = 80
BOOT_WAIT_SECONDS = 2.5
RESPONSE_TIMEOUT_SECONDS = 60

# Phase 8: both RX1 (01) and RX2 (02) now have file-receiver firmware.
# 7 s separates frames: each RX needs 3.2 s to close a frame and may need additional
# automatic-recovery time after optical interference. This is NOT RX feedback.
FILE_INTER_PACKET_GAP_SECONDS = 7.0
FILE_PACKET_COMPLETION_MARGIN = 1.65
FILE_PACKET_TIMEOUT_PADDING_SECONDS = 45.0

# =============================================================
# PHASE 8 FILE PACKETS AND SEPARATE FILE TRANSMISSION PATH
# Preparation/verification is local. Optional FILE| packet transmission
# requires Phase 8 TX firmware and the addressed Phase 8 RX firmware to be flashed.
# There is no RX acknowledgement/return link in this hardware version.
# =============================================================
FILE_CHUNK_SIZE = 40
FILE_MAX_PACKETS = 999
FILE_SUPPORTED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ")


def phase8_prepare_packets(filename, receiver_address):
    """Return (normalized_file_text, file_packets) for offline preparation.

    Packet format matches the previously verified Phase 8 Python generator:
    AA F SSS TTT LL PAYLOAD CCC
    checksum = sum(ASCII of all preceding fields) mod 256.
    """
    if receiver_address not in ("01", "02"):
        raise ValueError("Receiver must be 01 or 02")

    path = Path(filename)
    if not path.is_file():
        raise ValueError("Select an existing .txt file")
    if path.suffix.lower() != ".txt":
        raise ValueError("Only .txt files are supported in Phase 8")
    if path.stat().st_size > FILE_MAX_PACKETS * FILE_CHUNK_SIZE + 2:
        raise ValueError("File is too large (maximum 999 packets)")

    text = path.read_text(encoding="ascii").rstrip("\r\n").upper()
    if not text:
        raise ValueError("Text file is empty")
    unsupported = next((c for c in text if c not in FILE_SUPPORTED), None)
    if unsupported is not None:
        raise ValueError(
            "Unsupported character " + repr(unsupported) +
            ". Use A-Z, 0-9 and spaces only; no internal line breaks."
        )

    chunks = [text[i:i + FILE_CHUNK_SIZE]
              for i in range(0, len(text), FILE_CHUNK_SIZE)]
    if len(chunks) > FILE_MAX_PACKETS:
        raise ValueError("File exceeds 999 packets")
    packets = []
    for seq, payload in enumerate(chunks, 1):
        without_checksum = (
            receiver_address + "F" + f"{seq:03d}" + f"{len(chunks):03d}"
            + f"{len(payload):02d}" + payload
        )
        checksum = sum(without_checksum.encode("ascii")) % 256
        packets.append(without_checksum + f"{checksum:03d}")
    return text, packets


def phase8_verify_packets(packets, expected_address=None):
    """Validate and reconstruct a sequence of file packets, offline only."""
    if not packets:
        raise ValueError("No packets to verify")
    chunks = {}
    total_expected = None
    address_expected = expected_address
    for line in packets:
        if len(line) < 15 or not line[3:6].isdigit() or not line[6:9].isdigit() \
                or not line[9:11].isdigit() or not line[-3:].isdigit():
            raise ValueError("Invalid file packet structure")
        address, ptype = line[:2], line[2]
        sequence, total, length = int(line[3:6]), int(line[6:9]), int(line[9:11])
        payload = line[11:-3]
        if address not in ("01", "02") or (address_expected and address != address_expected):
            raise ValueError("Wrong or inconsistent receiver address")
        if ptype != "F" or not (1 <= sequence <= total <= FILE_MAX_PACKETS):
            raise ValueError("Invalid packet type or sequence")
        if not (1 <= length <= FILE_CHUNK_SIZE) or len(payload) != length:
            raise ValueError("Invalid packet payload length")
        if any(c not in FILE_SUPPORTED for c in payload):
            raise ValueError("Unsupported packet payload character")
        if sum(line[:-3].encode("ascii")) % 256 != int(line[-3:]):
            raise ValueError(f"Checksum mismatch in packet {sequence}")
        if total_expected is not None and total != total_expected:
            raise ValueError("Inconsistent total packet count")
        if sequence in chunks:
            raise ValueError(f"Duplicate packet {sequence}")
        address_expected, total_expected = address, total
        chunks[sequence] = payload
    if len(chunks) != total_expected:
        raise ValueError("Missing file packets")
    return "".join(chunks[i] for i in range(1, total_expected + 1))


def phase8_estimate_morse_seconds(frame):
    """Approximate time for a full TX frame using actual Phase 8 ESP32 timings.

    This is a planning/timeout estimate, not an actual measured transmission time.
    """
    total_ms = 0
    for ch in frame:
        if ch == " ":
            total_ms += 1400
            continue
        code = MORSE_VISUAL.get(ch)
        if not code:
            raise ValueError(f"Unsupported Morse character: {ch!r}")
        total_ms += sum(200 if symbol == "." else 600 for symbol in code)
        total_ms += 200 * (len(code) - 1) + 700
    return total_ms / 1000.0


def phase8_packet_timeout_seconds(frame):
    """Long file packets take minutes at the established Morse timing."""
    return max(90.0, phase8_estimate_morse_seconds(frame)
               * FILE_PACKET_COMPLETION_MARGIN + FILE_PACKET_TIMEOUT_PADDING_SECONDS)


# =============================================================
# THEME  (edit colors here)
# =============================================================
BG = "#F6F7FB"            # window background
CARD = "#FFFFFF"          # card surface
CARD_BORDER = "#E5E7EF"
SHADOW = "#ECEEF6"

TEXT = "#111827"
MUTED = "#6B7280"
FAINT = "#9CA3AF"

ACCENT = "#4F46E5"        # indigo (primary)
ACCENT_HOVER = "#4338CA"
ACCENT_PRESS = "#3730A3"
ACCENT_TINT = "#EEF2FF"
ACCENT_MID = "#E0E7FF"
ACCENT_DARK = "#3730A3"

IR = "#E11D48"            # infrared / highlight (rose)
IR_TINT = "#FFF1F2"
IR_DARK = "#9F1239"

CYAN = "#0891B2"
CYAN_TINT = "#CFFAFE"
CYAN_DARK = "#155E75"

GREEN = "#10B981"
GREEN_TINT = "#D1FAE5"
GREEN_DARK = "#065F46"

AMBER = "#F59E0B"
AMBER_TINT = "#FEF3C7"
AMBER_DARK = "#92400E"

RED = "#DC2626"
RED_TINT = "#FEE2E2"
RED_DARK = "#B91C1C"

TRACK = "#F3F4F8"
INPUT_BORDER = "#D1D5E3"
DISABLED_BG = "#E5E7EB"
DISABLED_FG = "#9CA3AF"

LOG_BG = "#0F1226"

FONT = "Segoe UI"
MONO = "Consolas"
SYMBOL_FONT = "Segoe UI Symbol"

# Visual-only Morse table, used ONLY to draw the pulse waveform preview.
# The real Morse encoding is still done by the ESP32.
MORSE_VISUAL = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.",
    "G": "--.", "H": "....", "I": "..", "J": ".---", "K": "-.-", "L": ".-..",
    "M": "--", "N": "-.", "O": "---", "P": ".--.", "Q": "--.-", "R": ".-.",
    "S": "...", "T": "-", "U": "..-", "V": "...-", "W": ".--", "X": "-..-",
    "Y": "-.--", "Z": "--..",
    "0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-",
    "5": ".....", "6": "-....", "7": "--...", "8": "---..", "9": "----.",
}


# =============================================================
# DRAWING HELPERS / CUSTOM WIDGETS (Canvas based, standard library only)
# =============================================================

def _round_points(x1, y1, x2, y2, r):
    return [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]


def draw_round(canvas, x1, y1, x2, y2, r, **kw):
    r = max(1, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    return canvas.create_polygon(_round_points(x1, y1, x2, y2, r), smooth=True, **kw)


class Card(tk.Canvas):
    """Rounded white card with a soft shadow. Put content in card.inner."""

    PAD = 16

    def __init__(self, parent, radius=14, expand=False):
        # Start tall so the inner frame gets mapped; it shrinks to fit right away.
        super().__init__(parent, bg=BG, highlightthickness=0, bd=0, height=300)
        self.radius = radius
        self.expand = expand
        self._req_h = 300
        self.inner = tk.Frame(self, bg=CARD)
        self._win = self.create_window(self.PAD, self.PAD, window=self.inner, anchor="nw")
        self.bind("<Configure>", self._on_resize)
        self.inner.bind("<Configure>", self._on_inner)

    def _on_inner(self, _e):
        h = self.inner.winfo_reqheight() + 2 * self.PAD + 3
        if h != self._req_h:
            self._req_h = h
            tk.Canvas.configure(self, height=h)

    def _on_resize(self, e):
        self.delete("bg")
        w, h = e.width, e.height
        draw_round(self, 1, 3, w - 1, h - 1, self.radius, fill=SHADOW, outline="", tags="bg")
        draw_round(self, 1, 1, w - 2, h - 3, self.radius, fill=CARD, outline=CARD_BORDER, tags="bg")
        self.tag_lower("bg")
        if self.expand:
            self.itemconfigure(
                self._win,
                width=max(10, w - 2 * self.PAD),
                height=max(self.inner.winfo_reqheight(), h - 2 * self.PAD - 3),
            )
        else:
            self.itemconfigure(self._win, width=max(10, w - 2 * self.PAD))


class RoundButton(tk.Canvas):
    """Rounded button with hover/pressed colors. Supports .config(state=...)."""

    def __init__(self, parent, text, command, bg, fg="#FFFFFF", hover=None,
                 press=None, font=(FONT, 10, "bold"), padx=16, pady=9,
                 radius=10, parent_bg=CARD):
        self._text = text
        self._command = command
        self._bg = bg
        self._fg = fg
        self._hover_bg = hover or bg
        self._press_bg = press or bg
        self._fontspec = font
        self._radius = radius
        self._state = "normal"
        self._hover = False
        self._down = False

        f = tkfont.Font(font=font)
        self._bw = f.measure(text) + 2 * padx
        self._bh = f.metrics("linespace") + 2 * pady

        super().__init__(
            parent, width=self._bw, height=self._bh, bg=parent_bg,
            highlightthickness=0, bd=0, cursor="hand2",
        )
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Configure>", lambda _e: self._draw())
        self._draw()

    def configure(self, cnf=None, **kw):
        if cnf:
            kw = {**cnf, **kw}
        if not kw:
            return tk.Canvas.configure(self)
        redraw = False
        if "state" in kw:
            self._state = kw.pop("state")
            tk.Canvas.configure(
                self, cursor="hand2" if self._state == "normal" else "arrow"
            )
            redraw = True
        if "text" in kw:
            self._text = kw.pop("text")
            redraw = True
        if kw:
            tk.Canvas.configure(self, **kw)
        if redraw:
            self._draw()

    config = configure

    def _on_enter(self, _e):
        self._hover = True
        self._draw()

    def _on_leave(self, _e):
        self._hover = False
        self._down = False
        self._draw()

    def _on_press(self, _e):
        if self._state == "normal":
            self._down = True
            self._draw()

    def _on_release(self, e):
        was_down = self._down
        self._down = False
        self._draw()
        inside = 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height()
        if was_down and inside and self._state == "normal" and self._command:
            self._command()

    def _draw(self):
        self.delete("all")
        w = self.winfo_width() if self.winfo_width() > 5 else self._bw
        h = self.winfo_height() if self.winfo_height() > 5 else self._bh

        if self._state != "normal":
            fill, fg = DISABLED_BG, DISABLED_FG
        elif self._down:
            fill, fg = self._press_bg, self._fg
        elif self._hover:
            fill, fg = self._hover_bg, self._fg
        else:
            fill, fg = self._bg, self._fg

        draw_round(self, 1, 1, w - 1, h - 1, self._radius, fill=fill, outline="")
        self.create_text(w / 2, h / 2, text=self._text, fill=fg, font=self._fontspec)


class Pill(tk.Canvas):
    """Rounded status pill. Works with a StringVar, optional pulsing dot."""

    def __init__(self, parent, textvariable=None, text="", fg=TEXT, bg=TRACK,
                 font=(FONT, 9, "bold"), padx=12, pady=5, parent_bg=CARD,
                 transform=None):
        self._var = textvariable
        self._text = text
        self._fg = fg
        self._bg = bg
        self._fontspec = font
        self._font = tkfont.Font(font=font)
        self._padx = padx
        self._pady = pady
        self._transform = transform
        self._dot = None
        self._dot_alt = None
        self._pulse = False
        self._pulse_on = False
        self._loop = None

        super().__init__(parent, bg=parent_bg, highlightthickness=0, bd=0)
        if self._var is not None:
            self._var.trace_add("write", lambda *_: self._redraw())
        self._redraw()

    def configure(self, cnf=None, **kw):
        if cnf:
            kw = {**cnf, **kw}
        if not kw:
            return tk.Canvas.configure(self)
        if "fg" in kw:
            self._fg = kw.pop("fg")
        if "bg" in kw:
            self._bg = kw.pop("bg")
        if "text" in kw:
            self._text = kw.pop("text")
        if "dot" in kw:
            self._dot = kw.pop("dot")
        if "dot_alt" in kw:
            self._dot_alt = kw.pop("dot_alt")
        if "pulse" in kw:
            self._pulse = kw.pop("pulse")
        if kw:
            tk.Canvas.configure(self, **kw)
        self._redraw()
        if self._pulse and self._dot and self._loop is None:
            self._loop = self.after(650, self._tick)

    config = configure

    def _tick(self):
        if not (self._pulse and self._dot):
            self._loop = None
            self._pulse_on = False
            self._redraw()
            return
        self._pulse_on = not self._pulse_on
        self._redraw()
        self._loop = self.after(650, self._tick)

    def _redraw(self):
        txt = self._var.get() if self._var is not None else self._text
        if self._transform:
            txt = self._transform(txt)

        dot_w = 16 if self._dot else 0
        w = self._font.measure(txt) + 2 * self._padx + dot_w
        h = self._font.metrics("linespace") + 2 * self._pady
        tk.Canvas.configure(self, width=w, height=h)

        self.delete("all")
        draw_round(self, 1, 1, w - 1, h - 1, h / 2 - 1, fill=self._bg, outline="")

        x = self._padx
        if self._dot:
            color = self._dot_alt if (self._pulse_on and self._dot_alt) else self._dot
            self.create_oval(x, h / 2 - 4, x + 8, h / 2 + 4, fill=color, outline="")
            x += 16
        self.create_text(x, h / 2, text=txt, anchor="w", fill=self._fg, font=self._fontspec)


class StatusRing(tk.Canvas):
    """Circular progress ring. Exposes start()/stop() like the old progress bar."""

    def __init__(self, parent, size=108):
        super().__init__(parent, width=size, height=size, bg=CARD,
                         highlightthickness=0, bd=0)
        self.size = size
        self.value = 0.0
        self.target = 0.0
        self.color = ACCENT
        self.running = False
        self._loop = None
        self._draw()

    def start(self, _interval=None):
        self.running = True
        self.color = ACCENT
        self.value = 0.0
        self.target = 0.0
        self._kick()

    def stop(self):
        self.running = False

    def set_target(self, pct, color=None):
        self.target = max(0.0, min(100.0, float(pct)))
        if color:
            self.color = color
        self._kick()

    def reset(self):
        self.running = False
        self.color = ACCENT
        self.target = 0.0
        self._kick()

    def _kick(self):
        if self._loop is None:
            self._tick()

    def _tick(self):
        diff = self.target - self.value
        if abs(diff) < 0.4:
            self.value = self.target
            self._draw()
            self._loop = None
            return
        step = diff * 0.16
        if abs(step) < 0.5:
            step = 0.5 if diff > 0 else -0.5
        self.value += step
        self._draw()
        self._loop = self.after(30, self._tick)

    def _draw(self):
        self.delete("all")
        s = self.size
        pad = 9
        box = (pad, pad, s - pad, s - pad)
        self.create_oval(*box, outline=CARD_BORDER, width=10)
        if self.value > 0.5:
            self.create_arc(
                *box, start=90, extent=-min(self.value, 99.9) * 3.6,
                style="arc", outline=self.color, width=10,
            )
        self.create_text(
            s / 2, s / 2, text=f"{int(round(self.value))}%",
            fill=TEXT, font=(FONT, 17, "bold"),
        )


class SignalPath(tk.Canvas):
    """Transmitter -> IR beam -> receivers. The addressed receiver lights up."""

    def __init__(self, parent, height=150):
        super().__init__(parent, height=height, bg=CARD, highlightthickness=0, bd=0)
        self.address = "02"
        self.port_text = "Not connected"
        self.active = False
        self.offset = 0
        self.blink = 0
        self.led_on = None        # None = unknown, True/False = real LED state
        self._loop = None
        self.bind("<Configure>", lambda _e: self.redraw())

    def set_led(self, state):
        self.led_on = state
        if state is None:
            self.redraw()
            return
        self.itemconfigure("halo", fill="#FECDD3" if state else "#FFE4E6")
        self.itemconfigure("ledcore", fill=IR if state else "#FDA4AF")
        self.itemconfigure("beam", fill=IR if state else "#FDA4AF")

    def set_receiver(self, address):
        if not self.active:
            self.address = address
            self.redraw()

    def set_port(self, text):
        self.port_text = text
        self.redraw()

    def set_active(self, flag, address=None):
        self.active = flag
        if address:
            self.address = address
        if flag:
            if self._loop is None:
                self._loop = self.after(40, self._tick)
        else:
            if self._loop is not None:
                self.after_cancel(self._loop)
                self._loop = None
        self.redraw()

    def _tick(self):
        if not self.active:
            self._loop = None
            return
        self.offset = (self.offset - 3) % 20
        self.blink = (self.blink + 1) % 12
        self.itemconfigure("beam", dashoffset=self.offset)
        if self.led_on is None:
            self.itemconfigure("halo", fill="#FECDD3" if self.blink < 6 else "#FFE4E6")
        self._loop = self.after(40, self._tick)

    def redraw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 320 or h < 80:
            return

        m = 4
        bw = min(max(int(w * 0.27), 210), 250)
        tx1, tx2 = m, m + bw
        ty1, ty2 = int(h * 0.14), int(h * 0.86)
        cy = h / 2
        rx1, rx2 = w - m - bw, w - m
        rows = {"01": (4, int(h * 0.40)), "02": (int(h * 0.60), h - 4)}
        led_x = tx2

        beam_col = "#FDA4AF" if self.led_on is False else IR

        # beams
        for addr, (y1, y2) in rows.items():
            ty = (y1 + y2) / 2
            if self.active and addr == self.address:
                self.create_line(
                    led_x + 12, cy, rx1, ty, fill=beam_col, width=3,
                    dash=(12, 8), dashoffset=self.offset, tags="beam",
                )
            else:
                self.create_line(
                    led_x + 12, cy, rx1, ty, fill=INPUT_BORDER, width=2, dash=(4, 6),
                )

        # transmitter box
        draw_round(self, tx1, ty1, tx2, ty2, 14, fill=ACCENT_TINT, outline="#6366F1", width=1.5)
        self.create_text(tx1 + 18, cy - 22, text="TX ESP32", anchor="w",
                         fill="#312E81", font=(FONT, 13, "bold"))
        self.create_text(tx1 + 18, cy, text="Python GUI  ·  USB serial", anchor="w",
                         fill=ACCENT, font=(FONT, 9))
        self.create_text(tx1 + 18, cy + 20, text=self.port_text, anchor="w",
                         fill="#6366F1", font=(FONT, 9))

        # LED
        lit = self.active if self.led_on is None else self.led_on
        halo = "#FECDD3" if lit else "#FFE4E6"
        self.create_oval(led_x - 14, cy - 14, led_x + 14, cy + 14,
                         fill=halo, outline="", tags="halo")
        self.create_oval(led_x - 8, cy - 8, led_x + 8, cy + 8,
                         fill=IR if lit else "#FDA4AF", outline="", tags="ledcore")

        # receivers
        for addr, (y1, y2) in rows.items():
            selected = addr == self.address
            mid = (y1 + y2) / 2
            if self.active and selected:
                fill, outline, ow = IR_TINT, IR, 1.5
                tcol, scol, sub = IR_DARK, "#BE123C", "Receiving frame"
            elif self.active:
                fill, outline, ow = "#F9FAFB", INPUT_BORDER, 1
                tcol, scol, sub = MUTED, FAINT, "Ignoring frame"
            elif selected:
                fill, outline, ow = ACCENT_TINT, "#6366F1", 1.5
                tcol, scol, sub = "#312E81", ACCENT, "Selected"
            else:
                fill, outline, ow = "#F9FAFB", INPUT_BORDER, 1
                tcol, scol, sub = MUTED, FAINT, "Idle"

            draw_round(self, rx1, y1, rx2, y2, 12, fill=fill, outline=outline, width=ow)
            self.create_text(rx1 + 16, mid - 9, anchor="w", fill=tcol,
                             text=f"RX{int(addr)}  ·  address {addr}",
                             font=(FONT, 11, "bold"))
            self.create_text(rx1 + 16, mid + 10, anchor="w", fill=scol,
                             text=sub, font=(FONT, 9))

        if self.active:
            y1, y2 = rows[self.address]
            ty = (y1 + y2) / 2
            mx = (led_x + rx1) / 2
            my = (cy + ty) / 2 + (-14 if ty < cy else 14)
            self.create_text(mx, my, text="IR light pulses", fill="#BE123C",
                             font=(FONT, 9, "bold"))


class Waveform(tk.Canvas):
    """IR pulse waveform with three modes:
    preview  - what the frame WILL look like (from the Morse table)
    live     - real LED ON/OFF events from the ESP32, scrolling like a scope
    captured - the full real trace of the last transmission, fitted to width
    """

    PX_PER_MS = 0.08   # live scroll speed: 0.08 px per millisecond

    def __init__(self, parent, height=58, bg="#F9FAFB"):
        super().__init__(parent, height=height, bg=bg, highlightthickness=0, bd=0)
        self.frame_text = ""
        self.mode = "preview"
        self.events = []          # (time_ms, level) level: 1 = LED on, 0 = off
        self._offset = None       # PC clock minus ESP32 clock (ms)
        self._use_ts = False
        self._loop = None
        self.bind("<Configure>", lambda _e: self.redraw())

    # ---------- public API ----------
    def set_frame(self, text):
        self.frame_text = text
        if self.mode == "live":
            return
        self.mode = "preview"
        self.events = []
        self.redraw()

    def arm_live(self):
        self.events = []
        self._offset = None
        self._use_ts = False
        if self.mode != "preview":
            self.mode = "preview"
            self.redraw()

    def add_event(self, ts_ms, level):
        mono = time.monotonic() * 1000.0
        if self.mode != "live":
            self.mode = "live"
            self.events = []
            self._offset = None
        if ts_ms is None:
            self._use_ts = False
            t = mono
        else:
            self._use_ts = True
            diff = mono - ts_ms
            self._offset = diff if self._offset is None else min(self._offset, diff)
            t = float(ts_ms)
        self.events.append((t, level))
        if self._loop is None:
            self._loop = self.after(33, self._tick)
        self.redraw()

    def end_live(self):
        if self._loop is not None:
            self.after_cancel(self._loop)
            self._loop = None
        if self.mode == "live" and len(self.events) >= 2:
            self.mode = "captured"
        elif self.mode == "live":
            self.mode = "preview"
        self.redraw()

    # ---------- internals ----------
    def _tick(self):
        if self.mode != "live":
            self._loop = None
            return
        self.redraw()
        self._loop = self.after(33, self._tick)

    def _now(self):
        mono = time.monotonic() * 1000.0
        return mono - (self._offset if (self._use_ts and self._offset is not None) else 0.0)

    def _caption(self, text, color):
        self.create_text(10, 8, text=text, anchor="w", fill=color, font=(FONT, 8, "bold"))

    def redraw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 40 or h < 24:
            return
        if self.mode == "live":
            self._draw_live(w, h)
        elif self.mode == "captured":
            self._draw_captured(w, h)
        else:
            self._draw_preview(w, h)

    def _draw_preview(self, w, h):
        hi, lo, m = 22, h - 9, 12
        self._caption("Preview of the IR pulses", FAINT)
        segs = []
        for ch in self.frame_text:
            if ch == " ":
                segs.append((0, 4))
                continue
            code = MORSE_VISUAL.get(ch)
            if not code:
                continue
            for i, sym in enumerate(code):
                segs.append((1, 1 if sym == "." else 3))
                if i < len(code) - 1:
                    segs.append((0, 1))
            segs.append((0, 3))

        if not segs:
            self.create_line(m, lo, w - m, lo, fill=INPUT_BORDER, width=2)
            self.create_text(w / 2, (hi + lo) / 2, text="Pulses appear here",
                             fill=FAINT, font=(FONT, 9))
            return

        total = sum(d for _, d in segs)
        unit = min(6.0, (w - 2 * m) / total)
        x = m
        pts = [m, lo]
        for level, d in segs:
            y = hi if level else lo
            pts += [x, y, x + d * unit, y]
            x += d * unit
        self.create_line(*pts, fill=ACCENT, width=2 if unit >= 2 else 1, joinstyle="miter")

    def _draw_live(self, w, h):
        hi, lo, m = 22, h - 9, 12
        left, right = m, w - m
        now = self._now()
        ppm = self.PX_PER_MS
        window = (right - left) / ppm

        def X(t):
            return right - (now - t) * ppm

        # level at the left edge = last event older than the window
        base = 0
        first = 0
        for i in range(len(self.events) - 1, -1, -1):
            if self.events[i][0] < now - window:
                base = self.events[i][1]
                first = i + 1
                break

        y_prev = hi if base else lo
        pts = [left, y_prev]
        for t, level in self.events[first:]:
            x = max(left, min(right, X(t)))
            y_new = hi if level else lo
            pts += [x, y_prev, x, y_new]
            y_prev = y_new
        pts += [right, y_prev]

        self.create_line(left, lo, right, lo, fill=CARD_BORDER, width=1)
        self.create_line(*pts, fill=IR, width=2, joinstyle="miter")
        self.create_oval(right - 4, y_prev - 4, right + 4, y_prev + 4, fill=IR, outline="")

        self._caption("Live LED signal", IR_DARK)
        on = y_prev == hi
        self.create_text(
            w - 10, 8, text="LED ON" if on else "LED OFF", anchor="e",
            fill=IR if on else FAINT, font=(FONT, 8, "bold"),
        )

    def _draw_captured(self, w, h):
        hi, lo, m = 22, h - 9, 12
        t0 = self.events[0][0]
        t1 = self.events[-1][0]
        span = max(1.0, t1 - t0)

        def X(t):
            return m + (t - t0) / span * (w - 2 * m)

        y_prev = lo
        pts = [m, lo]
        for t, level in self.events:
            x = X(t)
            y_new = hi if level else lo
            pts += [x, y_prev, x, y_new]
            y_prev = y_new
        pts += [w - m, y_prev]

        self.create_line(*pts, fill=ACCENT, width=2 if len(self.events) < 400 else 1,
                         joinstyle="miter")
        self._caption("Last transmission (real LED signal)", ACCENT)
        self.create_text(w - 10, 8, text=f"{span / 1000.0:.1f} s", anchor="e",
                         fill=MUTED, font=(FONT, 8))


# =============================================================
# MAIN APPLICATION
# =============================================================

class MorseIRStudio(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Morse IR Communication Studio")
        self.geometry("1440x880")
        self.minsize(1220, 760)
        self.configure(bg=BG)

        self.ser = None
        self.busy = False
        self.worker_queue = queue.Queue()

        # Additional Phase 8-only transfer state; original message methods intact.
        self.file_transfer_active = False
        self.file_transfer_window = None
        self.file_stop_event = threading.Event()

        self.port_var = tk.StringVar()
        self.receiver_var = tk.StringVar(value="02")
        self.message_var = tk.StringVar()

        self.conn_status_var = tk.StringVar(value="OFFLINE")
        self.conn_detail_var = tk.StringVar(value="Connect the TX ESP32 to begin.")

        self.preview_message_var = tk.StringVar(value="—")
        self.preview_checksum_var = tk.StringVar(value="—")
        self.preview_frame_var = tk.StringVar(value="—")

        self.tx_status_var = tk.StringVar(value="READY")
        self.tx_detail_var = tk.StringVar(value="No transmission in progress.")
        self.count_var = tk.StringVar(value="0 / 80")

        # visual-only state
        self._tx_total = 1
        self._tx_lines = 0

        self._setup_style()
        self._build_ui()

        self.message_var.trace_add("write", self._update_preview)
        self.receiver_var.trace_add("write", self._update_preview)

        # visual-only traces
        self.receiver_var.trace_add(
            "write", lambda *_: self.signal.set_receiver(self.receiver_var.get())
        )
        self.preview_frame_var.trace_add("write", lambda *_: self._refresh_waveform())
        self.conn_status_var.trace_add("write", lambda *_: self._sync_signal_port())
        self.port_var.trace_add("write", lambda *_: self._sync_signal_port())

        self._refresh_ports()
        self._update_preview()

        self.after(80, self._poll_worker_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # =========================================================
    # STYLE
    # =========================================================

    def _setup_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(
            "Port.TCombobox",
            fieldbackground=CARD,
            background=CARD,
            foreground=TEXT,
            arrowcolor=MUTED,
            bordercolor=INPUT_BORDER,
            lightcolor=INPUT_BORDER,
            darkcolor=INPUT_BORDER,
            padding=6,
        )
        style.map(
            "Port.TCombobox",
            fieldbackground=[("readonly", CARD)],
            foreground=[("readonly", TEXT)],
            selectbackground=[("readonly", CARD)],
            selectforeground=[("readonly", TEXT)],
        )
        self.option_add("*TCombobox*Listbox.background", CARD)
        self.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.option_add("*TCombobox*Listbox.selectForeground", "#FFFFFF")
        self.option_add("*TCombobox*Listbox.font", (FONT, 10))

        # slim scrollbar for the log
        style.layout(
            "Log.Vertical.TScrollbar",
            [("Vertical.Scrollbar.trough", {
                "sticky": "ns",
                "children": [("Vertical.Scrollbar.thumb",
                              {"expand": "1", "sticky": "nswe"})],
            })],
        )
        style.configure(
            "Log.Vertical.TScrollbar",
            troughcolor=LOG_BG,
            background="#3B3F66",
            bordercolor=LOG_BG,
            lightcolor="#3B3F66",
            darkcolor="#3B3F66",
            gripcount=0,
            width=9,
        )
        style.map("Log.Vertical.TScrollbar", background=[("active", "#5B5F95")])

    def _label(self, parent, text="", size=10, weight="normal", fg=TEXT, bg=None, **kwargs):
        return tk.Label(
            parent,
            text=text,
            font=(FONT, size, weight),
            fg=fg,
            bg=bg if bg else parent.cget("bg"),
            **kwargs
        )

    def _card(self, parent, expand=False):
        return Card(parent, expand=expand)

    def _button(self, parent, text, command, bg, fg=TEXT, hover=None, press=None,
                font=(FONT, 9, "bold"), padx=14, pady=8):
        return RoundButton(
            parent, text, command, bg=bg, fg=fg,
            hover=hover, press=press, font=font, padx=padx, pady=pady,
            parent_bg=parent.cget("bg"),
        )

    def _card_title(self, parent, symbol, tint, color, text):
        bg = parent.cget("bg")
        row = tk.Frame(parent, bg=bg)
        row.pack(fill="x")

        chip = tk.Canvas(row, width=28, height=28, bg=bg, highlightthickness=0, bd=0)
        draw_round(chip, 0, 0, 28, 28, 8, fill=tint, outline="")
        chip.create_text(14, 14, text=symbol, fill=color, font=(SYMBOL_FONT, 11, "bold"))
        chip.pack(side="left")

        self._label(row, text, 12, "bold").pack(side="left", padx=(10, 0))
        return row

    # =========================================================
    # UI
    # =========================================================

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self._build_header()
        tk.Frame(self, bg=CARD_BORDER, height=1).grid(row=1, column=0, sticky="ew")
        self._build_main_area()

    def _build_header(self):
        header = tk.Frame(self, bg=CARD)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(1, weight=1)

        # ---------- left: logo + title ----------
        left = tk.Frame(header, bg=CARD)
        left.grid(row=0, column=0, sticky="w", padx=(24, 0), pady=14)

        logo = tk.Canvas(left, width=44, height=44, bg=CARD, highlightthickness=0, bd=0)
        draw_round(logo, 0, 0, 44, 44, 12, fill=ACCENT, outline="")
        logo.create_oval(12, 28, 18, 34, fill="#FFFFFF", outline="")
        for r in (9, 16, 23):
            logo.create_arc(
                15 - r, 31 - r, 15 + r, 31 + r, start=8, extent=74,
                style="arc", outline="#FFFFFF", width=2,
            )
        logo.pack(side="left")

        titles = tk.Frame(left, bg=CARD)
        titles.pack(side="left", padx=(14, 0))

        self._label(
            titles, "Morse IR communication studio", size=18, weight="bold",
        ).pack(anchor="w")
        self._label(
            titles,
            "Addressable multi-receiver optical communication  •  ESP32  •  Morse  •  Checksum",
            size=9, fg=MUTED,
        ).pack(anchor="w", pady=(2, 0))

        # ---------- right: connection controls ----------
        right = tk.Frame(header, bg=CARD)
        right.grid(row=0, column=2, sticky="e", padx=24, pady=12)

        row = tk.Frame(right, bg=CARD)
        row.pack(anchor="e")

        group = tk.Frame(row, bg=TRACK)
        group.pack(side="left")

        self._label(group, "TX ESP32", 9, "bold", fg=MUTED, bg=TRACK).pack(
            side="left", padx=(12, 8), pady=8
        )

        self.port_combo = ttk.Combobox(
            group,
            textvariable=self.port_var,
            state="readonly",
            width=10,
            style="Port.TCombobox",
        )
        self.port_combo.pack(side="left", padx=(0, 6), pady=8)

        self.refresh_btn = self._button(
            group, "Refresh", self._refresh_ports, bg="#E5E7EB", fg="#374151",
            hover="#D1D5DB", press="#C4C8D4",
        )
        self.refresh_btn.pack(side="left", padx=(0, 6), pady=8)

        self.connect_btn = self._button(
            group, "Connect", self._connect, bg=ACCENT, fg="#FFFFFF",
            hover=ACCENT_HOVER, press=ACCENT_PRESS,
        )
        self.connect_btn.pack(side="left", padx=(0, 6), pady=8)

        self.disconnect_btn = self._button(
            group, "Disconnect", self._disconnect, bg=RED_TINT, fg=RED_DARK,
            hover="#FECACA", press="#FCA5A5",
        )
        self.disconnect_btn.pack(side="left", padx=(0, 8), pady=8)
        self.disconnect_btn.config(state="disabled")

        # tk.Label-like pill that keeps the same name used by the logic
        self.connection_badge = Pill(
            row, textvariable=self.conn_status_var, fg=RED_DARK, bg=RED_TINT,
            font=(FONT, 10, "bold"), padx=14, pady=8, parent_bg=CARD,
            transform=lambda s: s.capitalize(),
        )
        self.connection_badge.pack(side="left", padx=(12, 0))
        self._set_connection_badge("offline")

        tk.Label(
            right,
            textvariable=self.conn_detail_var,
            font=(FONT, 9),
            fg=MUTED,
            bg=CARD,
            anchor="e",
        ).pack(anchor="e", pady=(6, 0))

    def _build_main_area(self):
        main = tk.Frame(self, bg=BG)
        main.grid(row=2, column=0, sticky="nsew", padx=22, pady=16)

        main.grid_columnconfigure(0, weight=0, minsize=330)
        main.grid_columnconfigure(1, weight=1)
        main.grid_rowconfigure(0, weight=1)

        left = tk.Frame(main, bg=BG, width=330)
        left.grid(row=0, column=0, sticky="nsw", padx=(0, 16))
        left.grid_propagate(False)

        right = tk.Frame(main, bg=BG)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(2, weight=1)

        self._build_message_card(left)
        self._build_receiver_card(left)
        self._build_quick_status_card(left)

        self._build_signal_card(right)
        self._build_middle_row(right)
        self._build_log_card(right)

    # -------------------- LEFT --------------------

    def _build_message_card(self, parent):
        card = self._card(parent)
        card.pack(fill="x", pady=(0, 14))
        body = card.inner

        self._card_title(body, "✎", ACCENT_TINT, ACCENT, "Message composer")
        self._label(
            body,
            "Type the text to send. Lowercase is converted automatically.",
            9,
            fg=MUTED,
            wraplength=280,
            justify="left",
        ).pack(anchor="w", pady=(8, 0))

        shell = tk.Frame(body, bg=INPUT_BORDER)
        shell.pack(fill="x", pady=(12, 4))

        self.message_entry = tk.Entry(
            shell,
            textvariable=self.message_var,
            font=(MONO, 14),
            bg=CARD,
            fg=TEXT,
            insertbackground=ACCENT,
            disabledbackground="#F9FAFB",
            disabledforeground=MUTED,
            relief="flat",
            bd=0,
        )
        self.message_entry.pack(fill="x", padx=2, pady=2, ipady=8, ipadx=6)
        self.message_entry.bind("<FocusIn>", lambda _e: shell.config(bg=ACCENT))
        self.message_entry.bind("<FocusOut>", lambda _e: shell.config(bg=INPUT_BORDER))

        tk.Label(
            body,
            textvariable=self.count_var,
            font=(FONT, 9),
            fg=MUTED,
            bg=CARD,
        ).pack(anchor="e")

        self.send_btn = RoundButton(
            body, "Transmit message", self._send, bg=ACCENT, fg="#FFFFFF",
            hover=ACCENT_HOVER, press=ACCENT_PRESS, font=(FONT, 12, "bold"),
            pady=12, parent_bg=CARD,
        )
        self.send_btn.pack(fill="x", pady=(10, 0))
        self.send_btn.config(state="disabled")

        # Phase 8 has its own packet-preparation / transmission window. The working
        # single-message transmit button and UART command remain unchanged.
        self.file_tool_btn = self._button(
            body, "Text-file tools (Phase 8)", self._phase8_open_file_tool,
            bg=CYAN_TINT, fg=CYAN_DARK, hover="#A5F3FC", press="#67E8F9",
            font=(FONT, 10, "bold"), pady=9,
        )
        self.file_tool_btn.pack(fill="x", pady=(10, 0))
        self._label(
            body, "File selection, integrity check and Phase 8 IR sending.",
            8, fg=MUTED, wraplength=280, justify="left",
        ).pack(anchor="w", pady=(5, 0))

    def _build_receiver_card(self, parent):
        card = self._card(parent)
        card.pack(fill="x", pady=(0, 14))
        body = card.inner

        self._card_title(body, "◎", IR_TINT, IR, "Destination receiver")
        self._label(
            body,
            "The IR signal is broadcast. Addressing decides which receiver accepts it.",
            9,
            fg=MUTED,
            wraplength=280,
            justify="left",
        ).pack(anchor="w", pady=(8, 0))

        track = tk.Frame(body, bg=TRACK)
        track.pack(fill="x", pady=(12, 0))

        self.rx1_card = self._receiver_choice(track, "RX1", "01")
        self.rx1_card.pack(side="left", fill="both", expand=True, padx=(3, 2), pady=3)

        self.rx2_card = self._receiver_choice(track, "RX2", "02")
        self.rx2_card.pack(side="left", fill="both", expand=True, padx=(2, 3), pady=3)

        self._refresh_receiver_choice()

    def _receiver_choice(self, parent, name, address):
        frame = tk.Frame(
            parent,
            bg=TRACK,
            highlightthickness=1,
            highlightbackground=TRACK,
            cursor="hand2",
        )

        n = self._label(frame, name, 14, "bold", bg=TRACK)
        n.pack(pady=(10, 0))

        a = self._label(
            frame,
            f"Address {address}",
            9,
            fg=MUTED,
            bg=TRACK,
        )
        a.pack(pady=(0, 10))

        frame.name_label = n
        frame.addr_label = a

        for w in (frame, n, a):
            w.bind("<Button-1>", lambda _e, x=address: self._select_receiver(x))

        return frame

    def _build_quick_status_card(self, parent):
        card = self._card(parent, expand=True)
        card.pack(fill="both", expand=True)
        body = card.inner

        self._card_title(body, "ⓘ", ACCENT_TINT, ACCENT, "Project status")

        rows = [
            ("UART link", "Ready"),
            ("Morse encoder", "A–Z / 0–9"),
            ("Checksum", "8-bit additive"),
            ("IR TX", "LED55C @ 940 nm"),
            ("RX addresses", "01 / 02"),
        ]

        for i, (k, v) in enumerate(rows):
            line = tk.Frame(body, bg=CARD)
            line.pack(fill="x", pady=(12 if i == 0 else 0, 0))

            inner = tk.Frame(line, bg=CARD)
            inner.pack(fill="x", pady=7)
            self._label(inner, k, 9, fg=MUTED).pack(side="left")
            self._label(inner, v, 9, "bold", fg=TEXT).pack(side="right")

            if i < len(rows) - 1:
                tk.Frame(line, bg=CARD_BORDER, height=1).pack(fill="x")

    # -------------------- RIGHT --------------------

    def _build_signal_card(self, parent):
        card = self._card(parent)
        card.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        body = card.inner

        top = self._card_title(body, "⚡", ACCENT_TINT, ACCENT, "Signal path")

        self.stage_names = [
            "Frame + checksum",
            "Morse",
            "GPIO17 + BC547",
            "LED55C IR",
        ]
        self.stage_vars = []
        self.stage_pills = []
        for name in reversed(self.stage_names):
            var = tk.StringVar(value=name)
            pill = Pill(
                top, textvariable=var, fg=MUTED, bg=TRACK,
                font=(FONT, 8, "bold"), padx=10, pady=4, parent_bg=CARD,
            )
            pill.pack(side="right", padx=(5, 0))
            self.stage_vars.insert(0, var)
            self.stage_pills.insert(0, pill)

        self.signal = SignalPath(body, height=150)
        self.signal.pack(fill="x", pady=(10, 0))

    def _build_middle_row(self, parent):
        row = tk.Frame(parent, bg=BG)
        row.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        row.grid_columnconfigure(0, weight=1)
        row.grid_columnconfigure(1, weight=0, minsize=340)

        self._build_preview_card(row)
        self._build_tx_status_card(row)

    def _build_preview_card(self, parent):
        card = self._card(parent)
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        body = card.inner

        self._card_title(body, "▣", CYAN_TINT, CYAN, "Live frame preview")
        self._label(
            body,
            "Exact address + message + checksum frame before Morse encoding.",
            9,
            fg=MUTED,
        ).pack(anchor="w", pady=(8, 0))

        bar = tk.Frame(body, bg=CARD)
        bar.pack(fill="x", pady=(12, 0))
        bar.grid_columnconfigure(1, weight=1)

        tk.Label(
            bar, textvariable=self.receiver_var, font=(MONO, 13, "bold"),
            bg=CYAN_TINT, fg=CYAN_DARK, padx=16, pady=10,
        ).grid(row=0, column=0, sticky="nsew")
        tk.Label(
            bar, textvariable=self.preview_message_var, font=(MONO, 13, "bold"),
            bg=ACCENT_MID, fg="#312E81", padx=16, pady=10, wraplength=420,
        ).grid(row=0, column=1, sticky="nsew")
        tk.Label(
            bar, textvariable=self.preview_checksum_var, font=(MONO, 13, "bold"),
            bg=AMBER_TINT, fg=AMBER_DARK, padx=16, pady=10,
        ).grid(row=0, column=2, sticky="nsew")

        self._label(bar, "Receiver", 8, fg=MUTED).grid(row=1, column=0, pady=(4, 0))
        self._label(bar, "Message", 8, fg=MUTED).grid(row=1, column=1, pady=(4, 0))
        self._label(bar, "Checksum", 8, fg=MUTED).grid(row=1, column=2, pady=(4, 0))

        final = tk.Frame(body, bg=CARD)
        final.pack(fill="x", pady=(8, 0))
        self._label(final, "Final frame", 9, fg=MUTED).pack(side="left")
        tk.Label(
            final, textvariable=self.preview_frame_var, font=(MONO, 11, "bold"),
            fg=TEXT, bg=CARD, wraplength=420, justify="left",
        ).pack(side="left", padx=(10, 0))

        wave_shell = tk.Frame(
            body, bg="#F9FAFB", highlightthickness=1, highlightbackground=CARD_BORDER
        )
        wave_shell.pack(fill="x", pady=(10, 0))
        self.waveform = Waveform(wave_shell, height=58)
        self.waveform.pack(fill="x")

    def _build_tx_status_card(self, parent):
        card = self._card(parent)
        card.grid(row=0, column=1, sticky="nsew")
        body = card.inner

        self._card_title(body, "◉", GREEN_TINT, GREEN_DARK, "Transmission status")

        content = tk.Frame(body, bg=CARD)
        content.pack(fill="x", pady=(14, 0))

        # same attribute name as before; start()/stop() now drive a progress ring
        self.progress = StatusRing(content, size=108)
        self.progress.pack(side="left")

        side = tk.Frame(content, bg=CARD)
        side.pack(side="left", fill="x", expand=True, padx=(16, 0))

        self.tx_badge = Pill(
            side, textvariable=self.tx_status_var, fg=ACCENT_DARK, bg=ACCENT_MID,
            font=(FONT, 9, "bold"), padx=13, pady=6, parent_bg=CARD,
            transform=lambda s: s.capitalize(),
        )
        self.tx_badge.pack(anchor="w")
        self._set_tx_badge("ready")

        tk.Label(
            side,
            textvariable=self.tx_detail_var,
            font=(FONT, 9),
            fg=MUTED,
            bg=CARD,
            anchor="w",
            justify="left",
            wraplength=170,
        ).pack(anchor="w", pady=(10, 0))

    def _build_log_card(self, parent):
        card = self._card(parent, expand=True)
        card.grid(row=2, column=0, sticky="nsew")
        body = card.inner

        top = self._card_title(body, ">_", TRACK, "#374151", "Live transmission log")
        self._button(
            top, "Clear", self._clear_log, bg=TRACK, fg="#374151",
            hover="#E5E7EB", press="#D1D5DB", pady=5,
        ).pack(side="right")

        shell = tk.Frame(body, bg=LOG_BG)
        shell.pack(fill="both", expand=True, pady=(12, 0))

        sb = ttk.Scrollbar(shell, style="Log.Vertical.TScrollbar", orient="vertical")
        sb.pack(side="right", fill="y", padx=(0, 4), pady=6)

        self.log = tk.Text(
            shell,
            bg=LOG_BG,
            fg="#E5E7EB",
            insertbackground="#FFFFFF",
            font=(MONO, 10),
            relief="flat",
            bd=0,
            wrap="word",
            height=6,
            highlightthickness=0,
            yscrollcommand=sb.set,
            state="disabled",
        )
        self.log.pack(side="left", fill="both", expand=True, padx=12, pady=10)
        sb.config(command=self.log.yview)

        self.log.tag_configure("good", foreground="#86EFAC")
        self.log.tag_configure("info", foreground="#67E8F9")
        self.log.tag_configure("warn", foreground="#FDE68A")
        self.log.tag_configure("bad", foreground="#F87171")
        self.log.tag_configure("dim", foreground="#A5B4FC")

        self._log("Studio ready.", "dim")
        self._log("Connect the TX ESP32 using the top bar.", "dim")

    # =========================================================
    # VISUAL-ONLY HELPERS (no effect on transmission logic)
    # =========================================================

    def _sync_signal_port(self):
        if self.conn_status_var.get() == "CONNECTED" and self.port_var.get():
            self.signal.set_port(self.port_var.get())
        else:
            self.signal.set_port("Not connected")

    def _refresh_waveform(self):
        frame = self.preview_frame_var.get()
        self.waveform.set_frame("" if frame in ("", "—") else frame)

    def _set_stages(self, states):
        for name, var, pill, state in zip(
            self.stage_names, self.stage_vars, self.stage_pills, states
        ):
            if state == "done":
                var.set("✓ " + name)
                pill.config(fg=GREEN_DARK, bg=GREEN_TINT)
            elif state == "active":
                var.set(name)
                pill.config(fg="#FFFFFF", bg=ACCENT)
            else:
                var.set(name)
                pill.config(fg=MUTED, bg=TRACK)

    def _visual_tx_start(self, frame):
        self._tx_total = max(1, len(frame.replace(" ", "")))
        self._tx_lines = 0
        self.waveform.arm_live()
        self.signal.set_led(None)
        self.signal.set_active(True, frame[:2])
        self._set_stages(["done", "active", "pending", "pending"])
        self.progress.set_target(0, ACCENT)

    def _visual_line(self, line):
        """Visual-only. Returns True if the line was a live LED event."""
        parts = line.strip().split()

        # live LED events from the ESP32:  "LED ON" / "LED OFF" [millis]
        if len(parts) >= 2 and parts[0].upper() == "LED" and parts[1].upper() in ("ON", "OFF"):
            if self.busy:
                level = 1 if parts[1].upper() == "ON" else 0
                ts = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
                self.waveform.add_event(ts, level)
                self.signal.set_led(bool(level))
            return True

        if not self.busy:
            return False
        if line.startswith("=") or line.startswith(
            ("Destination", "Message", "Checksum", "Final frame")
        ):
            return False
        if " = " in line:
            self._tx_lines += 1
            pct = min(self._tx_lines / self._tx_total, 1.0) * 95
            self.progress.set_target(pct, ACCENT)
            self._set_stages(["done", "active", "active", "active"])
        return False

    def _visual_tx_done(self):
        self.waveform.end_live()
        self.signal.set_led(None)
        self.signal.set_active(False)
        self._set_stages(["done", "done", "done", "done"])
        self.progress.set_target(100, GREEN)

    def _visual_tx_error(self):
        self.waveform.end_live()
        self.signal.set_led(None)
        self.signal.set_active(False)
        self._set_stages(["pending", "pending", "pending", "pending"])
        self.progress.set_target(self.progress.value, RED)

    def _visual_tx_ready(self):
        self._set_stages(["pending", "pending", "pending", "pending"])
        self.progress.reset()

    # =========================================================
    # PHASE 8 FILE TOOLS + OPT-IN TX FILE-PACKET SENDING
    # Original ordinary message UART/Morse transmission methods stay unchanged.
    # =========================================================

    def _phase8_open_file_tool(self):
        win = tk.Toplevel(self)
        if self.file_transfer_window is not None:
            try:
                if self.file_transfer_window.winfo_exists():
                    self.file_transfer_window.lift()
                    self.file_transfer_window.focus_set()
                    return
            except tk.TclError:
                pass
        win.title("Phase 8  |  Text-file packet studio")
        self.file_transfer_window = win
        win.protocol("WM_DELETE_WINDOW", lambda: self._phase8_close_file_tool(win))
        # Keep the dialog within the usable screen area (including laptop displays).
        dialog_width = min(1120, max(780, win.winfo_screenwidth() - 80))
        dialog_height = min(710, max(500, win.winfo_screenheight() - 120))
        win.geometry(f"{dialog_width}x{dialog_height}")
        win.minsize(780, 500)
        win.configure(bg=BG)
        win.transient(self)
        win.file_path = None
        win.packet_frames = []
        win.file_contents = ""
        win.file_verified = False
        win.path_var = tk.StringVar(value="No file selected")
        win.status_var = tk.StringVar(value="Select an ASCII .txt file to begin.")
        win.metrics_var = tk.StringVar(value="No packets generated")
        win.address = self.receiver_var.get()

        header = tk.Frame(win, bg=CARD, padx=24, pady=18)
        header.pack(fill="x")
        self._label(header, "Text-file packet studio", 18, "bold").pack(anchor="w")
        self._label(
            header,
            "Phase 8 · File packets, offline verification and TX Morse/IR transmission",
            10, fg=MUTED,
        ).pack(anchor="w", pady=(5, 0))
        info = tk.Frame(header, bg=AMBER_TINT, padx=12, pady=9)
        info.pack(fill="x", pady=(15, 0))
        self._label(
            info,
            "IR SEND REQUIRES PHASE 8 TX + TARGET RX FIRMWARE · Confirm on the target RX monitor/OLED.",
            9, "bold", fg=AMBER_DARK, bg=AMBER_TINT,
        ).pack(anchor="w")

        main = tk.Frame(win, bg=BG, padx=22, pady=18)
        main.pack(fill="both", expand=True)

        top = tk.Frame(main, bg=CARD, padx=15, pady=14)
        top.pack(fill="x")
        tk.Label(top, text="TARGET RECEIVER", fg=MUTED, bg=CARD,
                 font=(FONT, 9, "bold")).pack(anchor="w")
        self._label(top, f"RX{int(win.address)}  ·  Address {win.address}", 12,
                    "bold", fg=ACCENT).pack(anchor="w", pady=(2, 12))

        file_row = tk.Frame(top, bg=CARD)
        file_row.pack(fill="x")
        file_row.columnconfigure(0, weight=1)
        tk.Entry(
            file_row, textvariable=win.path_var, state="readonly", font=(FONT, 10),
            readonlybackground="#F9FAFB", fg=TEXT, relief="solid", bd=1,
        ).grid(row=0, column=0, sticky="ew", ipady=8, padx=(0, 10))
        win.browse_btn = self._button(
            file_row, "Browse .txt", lambda: self._phase8_browse_file(win),
            bg=ACCENT, fg="#FFFFFF", hover=ACCENT_HOVER, press=ACCENT_PRESS,
        )
        win.browse_btn.grid(row=0, column=1)

        self._label(top, "ASCII text · A–Z, 0–9 and spaces · 40 chars per packet · up to 999 packets",
                    9, fg=MUTED).pack(anchor="w", pady=(12, 0))
        tk.Label(top, textvariable=win.metrics_var, font=(FONT, 10, "bold"),
                 fg=CYAN_DARK, bg=CARD).pack(anchor="w", pady=(6, 0))

        # Reserve the action bar FIRST, pinned at the bottom. Previously the
        # expanding Text previews consumed the available height and clipped
        # the buttons even when the dialog was maximized.
        footer = tk.Frame(main, bg=BG)
        footer.pack(side="bottom", fill="x", pady=(10, 0))
        tk.Label(
            footer, textvariable=win.status_var, font=(FONT, 9), fg=CYAN_DARK,
            bg=BG, anchor="w", wraplength=930, justify="left",
        ).pack(fill="x", pady=(0, 10))
        commands = tk.Frame(footer, bg=BG)
        commands.pack(fill="x")
        win.verify_btn = self._button(
            commands, "Verify + reconstruct", lambda: self._phase8_verify_file(win),
            bg=GREEN_TINT, fg=GREEN_DARK, hover="#A7F3D0", press="#6EE7B7",
        )
        win.verify_btn.pack(side="left", padx=(0, 10))
        win.save_btn = self._button(
            commands, "Export packets", lambda: self._phase8_export_packets(win),
            bg=ACCENT, fg="#FFFFFF", hover=ACCENT_HOVER, press=ACCENT_PRESS,
        )
        win.save_btn.pack(side="left", padx=(0, 10))
        win.transmit_btn = self._button(
            commands, "Transmit file via IR", lambda: self._phase8_transmit_file(win),
            bg=CYAN_DARK, fg="#FFFFFF", hover=CYAN, press="#164E63",
        )
        win.transmit_btn.pack(side="left", padx=(0, 10))
        win.stop_btn = self._button(
            commands, "Stop after packet", lambda: self._phase8_request_stop(win),
            bg=AMBER_TINT, fg=AMBER_DARK, hover="#FDE68A", press="#FCD34D",
        )
        win.stop_btn.pack(side="left")
        self._button(
            commands, "Close", lambda: self._phase8_close_file_tool(win),
            bg=TRACK, fg=TEXT, hover="#E5E7EB",
        ).pack(side="right")
        win.verify_btn.config(state="disabled")
        win.save_btn.config(state="disabled")
        win.transmit_btn.config(state="disabled")
        win.stop_btn.config(state="disabled")

        panes = tk.Frame(main, bg=BG)
        panes.pack(side="top", fill="both", expand=True, pady=(12, 0))
        panes.columnconfigure(0, weight=1)
        panes.columnconfigure(1, weight=1)
        panes.rowconfigure(0, weight=1)

        left = tk.Frame(panes, bg=CARD, padx=12, pady=12)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        right = tk.Frame(panes, bg=CARD, padx=12, pady=12)
        right.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        self._label(left, "Normalized file content", 11, "bold").pack(anchor="w")
        self._label(right, "Numbered file packets", 11, "bold").pack(anchor="w")
        win.text_preview = tk.Text(
            left, wrap="word", bg="#F8FAFC", fg=TEXT,
            font=(MONO, 10), padx=10, pady=10, height=5, state="disabled", bd=0,
        )
        win.text_preview.pack(fill="both", expand=True, pady=(10, 0))
        win.packet_preview = tk.Text(
            right, wrap="word", bg=LOG_BG, fg="#CFFAFE",
            font=(MONO, 10), padx=10, pady=10, height=5, state="disabled", bd=0,
        )
        win.packet_preview.pack(fill="both", expand=True, pady=(10, 0))
        self._phase8_fill_text(win.text_preview, "Browse for sample_message.txt or another text file.")
        self._phase8_fill_text(win.packet_preview, "Packets will appear here after validation.")
        win.focus_set()

    @staticmethod
    def _phase8_fill_text(widget, content):
        widget.config(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content)
        widget.config(state="disabled")

    def _phase8_browse_file(self, win):
        selected = filedialog.askopenfilename(
            parent=win,
            title="Select a Morse IR text file",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not selected:
            return
        win.file_path = None
        win.packet_frames = []
        win.file_contents = ""
        win.file_verified = False
        win.path_var.set(selected)
        win.verify_btn.config(state="disabled")
        win.save_btn.config(state="disabled")
        win.transmit_btn.config(state="disabled")
        try:
            text, frames = phase8_prepare_packets(selected, win.address)
        except (OSError, UnicodeError, ValueError) as exc:
            win.metrics_var.set("File not ready")
            win.status_var.set(f"Invalid file: {exc}")
            self._phase8_fill_text(win.text_preview, "File cannot be prepared. Correct the file and browse again.")
            self._phase8_fill_text(win.packet_preview, "No valid packets generated.")
            messagebox.showerror("Cannot prepare file", str(exc), parent=win)
            return

        win.file_path = selected
        win.file_contents = text
        win.packet_frames = frames
        win.metrics_var.set(
            f"{len(text)} characters  |  {len(frames)} packet(s)  |  "
            f"RX{int(win.address)}"
        )
        self._phase8_fill_text(win.text_preview, text)
        self._phase8_fill_text(
            win.packet_preview,
            "\n\n".join(f"PACKET {i:03d} / {len(frames):03d}\n{packet}"
                          for i, packet in enumerate(frames, 1)),
        )
        win.verify_btn.config(state="normal")
        win.save_btn.config(state="normal")
        win.status_var.set(
            "Packets generated and previewed locally. Verify before export. "
            "No data has been sent to an ESP32."
        )
        self._log(f"Phase 8: prepared {len(frames)} local file packet(s) for receiver {win.address}.", "info")

    def _phase8_verify_file(self, win):
        if not win.packet_frames:
            return
        try:
            output = phase8_verify_packets(win.packet_frames, win.address)
            if output != win.file_contents:
                raise ValueError("Reconstructed text differs from the input file")
        except (ValueError, UnicodeError) as exc:
            win.status_var.set(f"Local integrity check FAILED: {exc}")
            messagebox.showerror("Verification failed", str(exc), parent=win)
            return
        win.file_verified = True
        win.transmit_btn.config(state="normal" if win.address in ("01", "02") else "disabled")
        win.status_var.set(
            f"VERIFIED: all {len(win.packet_frames)} packets passed; "
            "reconstructed text matches. "
            + f"RX{int(win.address)} file transmission available with Phase 8 TX/RX firmware."
        )
        self._log("Phase 8: local packet checksum and reconstruction verification PASSED.", "good")
        messagebox.showinfo(
            "Offline verification passed",
            f"{len(win.packet_frames)} packet(s) verified.\n"
            "Original and reconstructed normalized text match.\n\n"
            "This check was offline; no IR transmission was performed by verification.",
            parent=win,
        )

    def _phase8_export_packets(self, win):
        if not win.packet_frames:
            return
        try:
            output = phase8_verify_packets(win.packet_frames, win.address)
            if output != win.file_contents:
                raise ValueError("File integrity check failed")
        except (ValueError, UnicodeError) as exc:
            messagebox.showerror("Export blocked", str(exc), parent=win)
            return
        output_name = filedialog.asksaveasfilename(
            parent=win,
            title="Save locally generated file packets",
            initialfile="generated_packets.txt",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt")],
        )
        if not output_name:
            return
        try:
            Path(output_name).write_text("\n".join(win.packet_frames) + "\n", encoding="ascii")
        except (OSError, UnicodeError) as exc:
            messagebox.showerror("Save failed", str(exc), parent=win)
            return
        win.status_var.set(f"Packets exported to {output_name}. No IR transfer performed.")
        self._log(f"Phase 8: exported {len(win.packet_frames)} packet(s) to disk.", "good")

    # =========================================================
    # PHASE 8 - FILE TX: SEPARATE WORKER; NEVER ALTER NORMAL MESSAGE PROTOCOL
    # =========================================================

    def _phase8_close_file_tool(self, win):
        if self.file_transfer_active:
            messagebox.showwarning(
                "File transmission active",
                "The ESP32 may still be transmitting the current Morse packet. "
                "Choose 'Stop after packet' and wait until the current packet ends.",
                parent=win,
            )
            return
        self.file_transfer_window = None
        win.destroy()

    def _phase8_request_stop(self, win):
        if self.file_transfer_active:
            self.file_stop_event.set()
            win.status_var.set("Stop requested. The CURRENT IR packet will finish before stopping.")
            win.stop_btn.config(state="disabled")
            self._log("Phase 8: stop requested; completing the current packet first.", "warn")

    def _phase8_transmit_file(self, win):
        if self.busy:
            messagebox.showwarning("Transmitter busy", "Finish the current operation first.", parent=win)
            return
        if win.address not in ("01", "02"):
            messagebox.showwarning(
                "Invalid receiver address",
                "Select RX1 (01) or RX2 (02) before sending.",
                parent=win,
            )
            return
        if not win.file_verified or not win.packet_frames:
            messagebox.showwarning("Verification required", "Verify + reconstruct the packets first.", parent=win)
            return
        if not self.ser or not self.ser.is_open:
            messagebox.showwarning(
                "TX ESP32 not connected",
                "Connect the Phase 8 TX ESP32 through the main GUI first.",
                parent=win,
            )
            return
        try:
            reconstructed = phase8_verify_packets(win.packet_frames, win.address)
            if reconstructed != win.file_contents:
                raise ValueError("Original and reconstructed text differ")
        except (ValueError, UnicodeError) as exc:
            messagebox.showerror("File verification failed", str(exc), parent=win)
            return
        frames = tuple(win.packet_frames)
        approximate_seconds = sum(phase8_estimate_morse_seconds(f) for f in frames)
        approximate_seconds += FILE_INTER_PACKET_GAP_SECONDS * max(0, len(frames) - 1)
        approximate_minutes = approximate_seconds / 60.0
        if not messagebox.askyesno(
            "Begin wireless file transmission?",
            f"Send {len(frames)} numbered Morse packets to RX{int(win.address)} ({win.address})?\n\n"
            f"Required: Phase 8 TX and Phase 8 RX{int(win.address)} firmware flashed and powered.\n"
            f"Estimated IR sending time: about {approximate_minutes:.1f} minutes "
            "(timing estimate only).\n\n"
            "The GUI can confirm that the TX ESP32 finished transmitting, "
            f"but CANNOT confirm RX{int(win.address)} received all packets: there is NO return/ACK channel.\n"
            f"Check the RX{int(win.address)} serial monitor and OLED for FILE COMPLETE.\n\n"
            "Stop is available between packets; current Morse packet cannot be interrupted.\n\n"
            "Start transmission?",
            parent=win,
        ):
            return

        self.file_stop_event.clear()
        self.file_transfer_active = True
        self.busy = True
        win.transmit_btn.config(state="disabled")
        win.verify_btn.config(state="disabled")
        win.save_btn.config(state="disabled")
        win.browse_btn.config(state="disabled")
        win.stop_btn.config(state="normal")
        self.send_btn.config(state="disabled")
        self.disconnect_btn.config(state="disabled")
        self.message_entry.config(state="disabled")
        self.file_tool_btn.config(state="disabled")
        self.tx_status_var.set("FILE TX")
        self.tx_detail_var.set(f"Preparing {len(frames)} file packet(s) for RX{int(win.address)}")
        self._set_tx_badge("transmitting")
        win.status_var.set(f"TX STARTED: {len(frames)} packets. RX{int(win.address)} reception not confirmed.")
        self._log(f"Phase 8: sending {len(frames)} file packet(s) to RX{int(win.address)}. "
                  "Receiver has NO ACK channel.", "info")
        threading.Thread(target=self._phase8_file_worker, args=(frames,), daemon=True).start()

    def _phase8_file_worker(self, packets):
        """Serial operations in worker thread. Only UI thread touches tkinter."""
        count = len(packets)
        completed = 0
        try:
            for index, frame in enumerate(packets, start=1):
                if self.file_stop_event.is_set():
                    self.worker_queue.put(("file_tx_stopped", completed))
                    return
                self.worker_queue.put(("file_packet_begin", (index, count, frame)))
                self.ser.reset_input_buffer()
                self.ser.write(("FILE|" + frame + "\n").encode("ascii"))
                self.ser.flush()
                started = time.monotonic()
                timeout = phase8_packet_timeout_seconds(frame)
                saw_phase8_ready = False
                saw_started = False
                while time.monotonic() - started < timeout:
                    raw = self.ser.readline()
                    if not raw:
                        continue
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    self.worker_queue.put(("tx_line", line))
                    upper = line.upper()
                    if "PHASE 8 FILE PACKET REJECTED" in upper:
                        raise ValueError("TX rejected packet: " + line)
                    if ("INVALID ADDRESS" in upper or "INVALID FORMAT" in upper
                            or "INVALID CHARACTER" in upper):
                        raise ValueError(
                            "TX returned an invalid-command error. Check that Phase 8 TX firmware is flashed. "
                            + line
                        )
                    if "PHASE 8 FILE PACKET READY" in upper:
                        saw_phase8_ready = True
                    if "MORSE TRANSMISSION STARTED" in upper:
                        saw_started = True
                    if "MORSE TRANSMISSION COMPLETE" in upper:
                        if not (saw_phase8_ready and saw_started):
                            raise ValueError(
                                "TX did not confirm Phase 8 FILE packet mode; stop to avoid malformed frames."
                            )
                        break
                else:
                    raise TimeoutError(
                        f"TX timeout on packet {index}/{count}. "
                        "Long Morse packets need much more than 60 seconds."
                    )
                completed = index
                self.worker_queue.put(("file_packet_done", (completed, count)))
                if index < count:
                    self.worker_queue.put(("file_gap", (completed, count)))
                    if self.file_stop_event.wait(FILE_INTER_PACKET_GAP_SECONDS):
                        self.worker_queue.put(("file_tx_stopped", completed))
                        return
            self.worker_queue.put(("file_tx_done", completed))
        except Exception as exc:
            self.worker_queue.put(("file_tx_fail", (completed, str(exc))))

    def _phase8_file_packet_begin(self, index, count, frame):
        self._visual_tx_start(frame)
        self.tx_status_var.set("FILE TX")
        self.tx_detail_var.set(f"Transmitting file packet {index}/{count}")
        win = self.file_transfer_window
        if win is not None and win.winfo_exists():
            win.status_var.set(
                f"Transmitting packet {index}/{count} ({len(frame)} characters). "
                f"Waiting for TX ESP32 completion; RX{int(win.address)} not confirmed."
            )
        self._log(f"Phase 8: sending FILE| packet {index}/{count} (checksum already included).", "info")

    def _phase8_file_packet_done(self, completed, count):
        self._visual_tx_done()
        self._log(f"Phase 8: TX ESP32 completed IR packet {completed}/{count}.", "good")
        win = self.file_transfer_window
        target = f"RX{int(win.address)}" if win is not None and win.winfo_exists() else "target RX"
        self.tx_detail_var.set(f"TX ESP32 transmitted {completed}/{count}; {target} unconfirmed")
        if win is not None and win.winfo_exists():
            win.status_var.set(
                f"TX completed {completed}/{count} packets. "
                f"RX{int(win.address)} must verify reception separately."
            )

    def _phase8_file_finish(self, completed, state, error=""):
        self.file_transfer_active = False
        self.busy = False
        self.file_stop_event.clear()
        self.progress.stop()
        connected = bool(self.ser and self.ser.is_open)
        self.send_btn.config(state="normal" if connected else "disabled")
        self.disconnect_btn.config(state="normal" if connected else "disabled")
        self.message_entry.config(state="normal")
        self.file_tool_btn.config(state="normal")
        win = self.file_transfer_window
        if win is not None and win.winfo_exists():
            win.browse_btn.config(state="normal")
            win.verify_btn.config(state="normal" if win.packet_frames else "disabled")
            win.save_btn.config(state="normal" if win.packet_frames else "disabled")
            win.transmit_btn.config(
                state="normal" if win.file_verified and win.address in ("01", "02") else "disabled"
            )
            win.stop_btn.config(state="disabled")
        target = f"RX{int(win.address)}" if win is not None and win.winfo_exists() else "target RX"
        if state == "done":
            self.tx_status_var.set("COMPLETE")
            self._set_tx_badge("complete")
            detail = f"TX completed {completed} file packet(s). {target} reception NOT confirmed."
            self.tx_detail_var.set(detail)
            self._log(f"Phase 8: all file packets TRANSMITTED by TX. Verify {target} FILE COMPLETE separately.", "good")
            if win is not None and win.winfo_exists():
                win.status_var.set(detail + f" Check {target} OLED/monitor.")
                messagebox.showinfo(
                    "TX file transmission finished",
                    detail + f"\n\nLook for {target} FILE COMPLETE in the {target} monitor. "
                    "There is no receiver acknowledgement channel.",
                    parent=win,
                )
        elif state == "stopped":
            self.tx_status_var.set("STOPPED")
            self._set_tx_badge("ready")
            detail = f"Stopped after TX packet {completed}; {target} may hold an incomplete file."
            self.tx_detail_var.set(detail)
            self._visual_tx_error()
            self._log("Phase 8: file TX stopped at a packet boundary.", "warn")
            if win is not None and win.winfo_exists():
                win.status_var.set(detail)
        else:
            self.tx_status_var.set("ERROR")
            self._set_tx_badge("error")
            self.tx_detail_var.set(error)
            self._visual_tx_error()
            self._log(f"Phase 8: TX failed after {completed} packets: {error}", "bad")
            if win is not None and win.winfo_exists():
                win.status_var.set(f"TX failed after {completed} packets: {error}")
                messagebox.showerror("File TX failed", error, parent=win)

    # =========================================================
    # RECEIVER / PREVIEW
    # =========================================================

    def _select_receiver(self, address):
        self.receiver_var.set(address)
        self._refresh_receiver_choice()

    def _refresh_receiver_choice(self):
        selected = self.receiver_var.get()

        for card, addr in (
            (self.rx1_card, "01"),
            (self.rx2_card, "02"),
        ):
            if addr == selected:
                bg = CARD
                border = INPUT_BORDER
                name_fg, addr_fg = ACCENT, MUTED
            else:
                bg = TRACK
                border = TRACK
                name_fg, addr_fg = MUTED, FAINT

            card.config(bg=bg, highlightbackground=border)
            card.name_label.config(bg=bg, fg=name_fg)
            card.addr_label.config(bg=bg, fg=addr_fg)

    @staticmethod
    def _checksum(text):
        return sum(text.encode("ascii")) & 0xFF

    def _validate_message(self, raw):
        msg = raw.upper()

        if len(msg) > MAX_MESSAGE_LENGTH:
            return False, msg, "Message exceeds 80 characters."

        for ch in msg:
            if not (
                ch == " "
                or ("A" <= ch <= "Z")
                or ("0" <= ch <= "9")
            ):
                return False, msg, f"Unsupported character: {repr(ch)}"

        return True, msg, ""

    def _update_preview(self, *_):
        raw = self.message_var.get()
        self.count_var.set(f"{len(raw)} / {MAX_MESSAGE_LENGTH}")

        valid, msg, _ = self._validate_message(raw)

        if not raw:
            self.preview_message_var.set("—")
            self.preview_checksum_var.set("—")
            self.preview_frame_var.set("—")
            return

        if not valid:
            self.preview_message_var.set("INVALID")
            self.preview_checksum_var.set("—")
            self.preview_frame_var.set("—")
            return

        address = self.receiver_var.get()
        checksum = self._checksum(address + msg)

        self.preview_message_var.set(msg)
        self.preview_checksum_var.set(f"{checksum:03d}")
        self.preview_frame_var.set(f"{address}{msg}{checksum:03d}")

    # =========================================================
    # CONNECTION
    # =========================================================

    def _refresh_ports(self):
        ports = [p.device for p in list_ports.comports()]
        self.port_combo["values"] = ports

        if self.ser and self.ser.is_open:
            return

        if ports:
            if self.port_var.get() not in ports:
                self.port_var.set("COM15" if "COM15" in ports else ports[0])
            self.conn_detail_var.set("Available ports: " + ", ".join(ports))
        else:
            self.port_var.set("")
            self.conn_detail_var.set("No COM ports detected.")

    def _connect(self):
        if self.busy:
            return

        port = self.port_var.get().strip()

        if not port:
            messagebox.showerror(
                "No COM Port",
                "Connect the TX ESP32, click REFRESH, then select its COM port.",
            )
            return

        self.busy = True
        self.connect_btn.config(state="disabled")
        self.conn_status_var.set("CONNECTING")
        self.conn_detail_var.set(f"Opening {port} @ {BAUD_RATE} baud...")
        self._set_connection_badge("connecting")

        threading.Thread(
            target=self._connect_worker,
            args=(port,),
            daemon=True,
        ).start()

    def _connect_worker(self, port):
        try:
            ser = serial.Serial(
                port=port,
                baudrate=BAUD_RATE,
                timeout=0.20,
                write_timeout=2,
            )

            time.sleep(BOOT_WAIT_SECONDS)
            ser.reset_input_buffer()

            self.worker_queue.put(("connect_ok", (ser, port)))

        except Exception as exc:
            self.worker_queue.put(("connect_fail", str(exc)))

    def _finish_connect(self, ser, port):
        self.ser = ser
        self.busy = False

        self.conn_status_var.set("CONNECTED")
        self.conn_detail_var.set(f"{port}  •  {BAUD_RATE} baud  •  TX ESP32 ready")
        self._set_connection_badge("connected")

        self.connect_btn.config(state="disabled")
        self.disconnect_btn.config(state="normal")
        self.send_btn.config(state="normal")

        self._log(f"Connected to TX ESP32 on {port}.", "good")
        self.message_entry.focus_set()

    def _connect_failed(self, text):
        self.busy = False
        self.ser = None

        self.conn_status_var.set("OFFLINE")
        self.conn_detail_var.set("Connection failed.")
        self._set_connection_badge("offline")

        self.connect_btn.config(state="normal")
        self.disconnect_btn.config(state="disabled")
        self.send_btn.config(state="disabled")

        self._log(f"Connection failed: {text}", "bad")
        messagebox.showerror("Connection Failed", text)

    def _disconnect(self):
        if self.busy:
            return

        try:
            if self.ser and self.ser.is_open:
                self.ser.close()
        except Exception:
            pass

        self.ser = None

        self.conn_status_var.set("OFFLINE")
        self.conn_detail_var.set("Connect the TX ESP32 to begin.")
        self._set_connection_badge("offline")

        self.connect_btn.config(state="normal")
        self.disconnect_btn.config(state="disabled")
        self.send_btn.config(state="disabled")

        self._log("TX ESP32 disconnected.", "warn")

    # =========================================================
    # TRANSMISSION
    # =========================================================

    def _send(self):
        if self.busy:
            return

        if not self.ser or not self.ser.is_open:
            messagebox.showerror("Not Connected", "Connect the TX ESP32 first.")
            return

        raw = self.message_var.get().strip()

        if not raw:
            messagebox.showwarning("Empty Message", "Enter a message before transmitting.")
            return

        valid, msg, reason = self._validate_message(raw)

        if not valid:
            messagebox.showerror(
                "Invalid Message",
                reason + "\n\nUse only A-Z, 0-9 and spaces.",
            )
            return

        address = self.receiver_var.get()
        checksum = self._checksum(address + msg)
        frame = f"{address}{msg}{checksum:03d}"

        self.busy = True
        self.send_btn.config(state="disabled")
        self.disconnect_btn.config(state="disabled")
        self.message_entry.config(state="disabled")

        self.tx_status_var.set("TRANSMITTING")
        self.tx_detail_var.set(f"Sending frame: {frame}")
        self._set_tx_badge("transmitting")
        self.progress.start(9)
        self._visual_tx_start(frame)

        self._log("", "dim")
        self._log("────────────────────────────────────", "dim")
        self._log(f"Receiver : {address}", "info")
        self._log(f"Message  : {msg}", "info")
        self._log(f"Checksum : {checksum:03d}", "info")
        self._log(f"Frame    : {frame}", "info")

        threading.Thread(
            target=self._send_worker,
            args=(address, msg),
            daemon=True,
        ).start()

    def _send_worker(self, address, msg):
        try:
            command = f"{address}|{msg}\n"

            self.ser.reset_input_buffer()
            self.ser.write(command.encode("ascii"))
            self.ser.flush()

            start = time.time()
            complete = False

            while time.time() - start < RESPONSE_TIMEOUT_SECONDS:
                raw = self.ser.readline()

                if raw:
                    line = raw.decode("utf-8", errors="ignore").strip()

                    if line:
                        self.worker_queue.put(("tx_line", line))

                        if "MORSE TRANSMISSION COMPLETE" in line:
                            complete = True
                            break
                else:
                    time.sleep(0.02)

            if complete:
                self.worker_queue.put(("tx_done", None))
            else:
                self.worker_queue.put(
                    ("tx_fail", "Timed out waiting for ESP32 completion.")
                )

        except Exception as exc:
            self.worker_queue.put(("tx_fail", str(exc)))

    def _finish_transmission(self):
        self.busy = False
        self.progress.stop()

        self.tx_status_var.set("COMPLETE")
        self.tx_detail_var.set("ESP32 confirmed Morse/IR transmission complete.")
        self._set_tx_badge("complete")
        self._visual_tx_done()

        self.send_btn.config(
            state="normal" if self.ser and self.ser.is_open else "disabled"
        )
        self.disconnect_btn.config(
            state="normal" if self.ser and self.ser.is_open else "disabled"
        )
        self.message_entry.config(state="normal")
        self.message_entry.focus_set()

        self._log("Transmission completed successfully.", "good")

        self.after(2200, self._return_tx_ready)

    def _transmission_failed(self, text):
        self.busy = False
        self.progress.stop()

        self.tx_status_var.set("ERROR")
        self.tx_detail_var.set(text)
        self._set_tx_badge("error")
        self._visual_tx_error()

        self.send_btn.config(
            state="normal" if self.ser and self.ser.is_open else "disabled"
        )
        self.disconnect_btn.config(
            state="normal" if self.ser and self.ser.is_open else "disabled"
        )
        self.message_entry.config(state="normal")

        self._log(f"Transmission failed: {text}", "bad")

    def _return_tx_ready(self):
        if not self.busy:
            self.tx_status_var.set("READY")
            self.tx_detail_var.set("Ready for the next message.")
            self._set_tx_badge("ready")
            self._visual_tx_ready()

    # =========================================================
    # QUEUE / LOG
    # =========================================================

    def _poll_worker_queue(self):
        try:
            while True:
                event, payload = self.worker_queue.get_nowait()

                if event == "connect_ok":
                    ser, port = payload
                    self._finish_connect(ser, port)

                elif event == "connect_fail":
                    self._connect_failed(payload)

                elif event == "tx_line":
                    self._display_esp32_line(payload)

                elif event == "tx_done":
                    self._finish_transmission()

                elif event == "tx_fail":
                    self._transmission_failed(payload)

                elif event == "file_packet_begin":
                    self._phase8_file_packet_begin(*payload)
                elif event == "file_packet_done":
                    self._phase8_file_packet_done(*payload)
                elif event == "file_gap":
                    completed, total = payload
                    win = self.file_transfer_window
                    if win is not None and win.winfo_exists():
                        win.status_var.set(
                            f"TX completed {completed}/{total}. Waiting "
                            f"{FILE_INTER_PACKET_GAP_SECONDS:g}s for target RX frame/recovery. "
                            "This does not confirm RX acceptance."
                        )
                elif event == "file_tx_done":
                    self._phase8_file_finish(payload, "done")
                elif event == "file_tx_stopped":
                    self._phase8_file_finish(payload, "stopped")
                elif event == "file_tx_fail":
                    count, error = payload
                    self._phase8_file_finish(count, "failed", error)

        except queue.Empty:
            pass

        self.after(80, self._poll_worker_queue)

    def _display_esp32_line(self, line):
        if self._visual_line(line):
            return  # live LED ON/OFF events only drive the waveform, not the log
        low = line.lower()

        if line.startswith("="):
            return

        if "enter command" in low:
            return

        if "phase 7 frame ready" in low:
            self._log("ESP32: frame constructed.", "good")
            return

        if "morse transmission started" in low:
            self._log("ESP32: Morse/IR transmission started.", "good")
            return

        if "morse transmission complete" in low:
            self._log("ESP32: Morse/IR transmission complete.", "good")
            return

        if line.startswith(("Destination", "Message", "Checksum", "Final frame")):
            self._log("ESP32: " + line, "info")
            return

        if " = " in line:
            self._log(line, "dim")
            return

        if "invalid" in low or "unsupported" in low:
            self._log("ESP32: " + line, "bad")
            return

        self._log("ESP32: " + line, "dim")

    def _set_connection_badge(self, state):
        if state == "connected":
            self.connection_badge.config(
                fg=GREEN_DARK, bg=GREEN_TINT, dot=GREEN, dot_alt="#6EE7B7", pulse=True
            )
        elif state == "connecting":
            self.connection_badge.config(
                fg=AMBER_DARK, bg=AMBER_TINT, dot=AMBER, dot_alt="#FCD34D", pulse=True
            )
        else:
            self.connection_badge.config(
                fg=RED_DARK, bg=RED_TINT, dot=RED, dot_alt="#FCA5A5", pulse=False
            )

    def _set_tx_badge(self, state):
        mapping = {
            "ready": (ACCENT_DARK, ACCENT_MID),
            "transmitting": (AMBER_DARK, AMBER_TINT),
            "complete": (GREEN_DARK, GREEN_TINT),
            "error": (RED_DARK, RED_TINT),
        }
        fg, bg = mapping.get(state, mapping["ready"])
        self.tx_badge.config(fg=fg, bg=bg)

    def _log(self, text, tag="dim"):
        self.log.config(state="normal")
        self.log.insert("end", text + "\n", tag)
        self.log.see("end")
        self.log.config(state="disabled")

    def _clear_log(self):
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")
        self._log("Log cleared.", "dim")

    def _on_close(self):
        if self.file_transfer_active:
            messagebox.showwarning(
                "File TX in progress",
                "The ESP32 is still transmitting or waiting between Morse packets. "
                "Use 'Stop after packet' in the file tools window and then close.",
            )
            return
        try:
            if self.ser and self.ser.is_open:
                self.ser.close()
        except Exception:
            pass
        self.destroy()


if __name__ == "__main__":
    # Sharper text on Windows high-DPI screens (visual only).
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    app = MorseIRStudio()
    app.mainloop()
