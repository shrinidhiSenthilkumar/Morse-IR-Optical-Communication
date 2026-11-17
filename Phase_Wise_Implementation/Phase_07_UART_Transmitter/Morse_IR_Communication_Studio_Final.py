import tkinter as tk
from tkinter import ttk, messagebox
import threading
import queue
import time
import serial
from serial.tools import list_ports

BAUD_RATE = 115200
MAX_MESSAGE_LENGTH = 80
BOOT_WAIT_SECONDS = 2.5
RESPONSE_TIMEOUT_SECONDS = 60

# -------------------- Theme --------------------
BG = "#060b14"
HEADER = "#0a1322"
SURFACE = "#0f1b2d"
SURFACE_2 = "#0b1626"
SURFACE_3 = "#08111d"
BORDER = "#203149"

TEXT = "#f8fafc"
MUTED = "#8fa3bf"

ACCENT = "#27c2f3"
ACCENT_DARK = "#0c7596"
GREEN = "#22c55e"
AMBER = "#f59e0b"
RED = "#ef4444"

FONT = "Segoe UI"


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

        self._setup_style()
        self._build_ui()

        self.message_var.trace_add("write", self._update_preview)
        self.receiver_var.trace_add("write", self._update_preview)

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
            fieldbackground=SURFACE_3,
            background=SURFACE_3,
            foreground=TEXT,
            arrowcolor=TEXT,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            padding=8,
        )

        style.map(
            "Port.TCombobox",
            fieldbackground=[("readonly", SURFACE_3)],
            foreground=[("readonly", TEXT)],
            selectbackground=[("readonly", SURFACE_3)],
            selectforeground=[("readonly", TEXT)],
        )

        style.configure(
            "Tx.Horizontal.TProgressbar",
            troughcolor="#132239",
            background=ACCENT,
            bordercolor="#132239",
            lightcolor=ACCENT,
            darkcolor=ACCENT,
        )

    def _label(self, parent, text="", size=10, weight="normal", fg=TEXT, bg=None, **kwargs):
        return tk.Label(
            parent,
            text=text,
            font=(FONT, size, weight),
            fg=fg,
            bg=bg if bg else parent.cget("bg"),
            **kwargs
        )

    def _card(self, parent, bg=SURFACE):
        return tk.Frame(
            parent,
            bg=bg,
            highlightthickness=1,
            highlightbackground=BORDER,
        )

    def _button(self, parent, text, command, bg, fg=TEXT, width=None):
        return tk.Button(
            parent,
            text=text,
            command=command,
            font=(FONT, 9, "bold"),
            bg=bg,
            fg=fg,
            activebackground=bg,
            activeforeground=fg,
            disabledforeground="#64748b",
            relief="flat",
            bd=0,
            padx=14,
            pady=9,
            width=width,
            cursor="hand2",
        )

    # =========================================================
    # UI
    # =========================================================

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        self._build_header()
        self._build_connection_strip()
        self._build_signal_flow()
        self._build_main_area()

    def _build_header(self):
        header = tk.Frame(self, bg=HEADER, height=92)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.grid_columnconfigure(0, weight=1)

        title = tk.Frame(header, bg=HEADER)
        title.grid(row=0, column=0, sticky="w", padx=28, pady=16)

        self._label(
            title,
            "MORSE IR COMMUNICATION STUDIO",
            size=22,
            weight="bold",
            bg=HEADER,
        ).pack(anchor="w")

        self._label(
            title,
            "Addressable Multi-Receiver Optical Communication  •  ESP32  •  Morse  •  Checksum",
            size=10,
            fg=MUTED,
            bg=HEADER,
        ).pack(anchor="w", pady=(4, 0))

        self.connection_badge = tk.Label(
            header,
            textvariable=self.conn_status_var,
            font=(FONT, 10, "bold"),
            fg="#fecaca",
            bg="#7f1d1d",
            padx=18,
            pady=9,
        )
        self.connection_badge.grid(row=0, column=1, sticky="e", padx=28)

    def _build_connection_strip(self):
        strip = self._card(self)
        strip.grid(row=1, column=0, sticky="ew", padx=22, pady=(14, 0))
        strip.grid_columnconfigure(6, weight=1)

        self._label(strip, "TX ESP32", 10, "bold").grid(
            row=0, column=0, padx=(16, 12), pady=12, sticky="w"
        )

        self.port_combo = ttk.Combobox(
            strip,
            textvariable=self.port_var,
            state="readonly",
            width=12,
            style="Port.TCombobox",
        )
        self.port_combo.grid(row=0, column=1, padx=(0, 8), pady=12)

        self.refresh_btn = self._button(strip, "REFRESH", self._refresh_ports, "#26364d")
        self.refresh_btn.grid(row=0, column=2, padx=(0, 8), pady=12)

        self.connect_btn = self._button(strip, "CONNECT", self._connect, ACCENT_DARK)
        self.connect_btn.grid(row=0, column=3, padx=(0, 8), pady=12)

        self.disconnect_btn = self._button(strip, "DISCONNECT", self._disconnect, "#3b4658")
        self.disconnect_btn.grid(row=0, column=4, padx=(0, 12), pady=12)
        self.disconnect_btn.config(state="disabled")

        tk.Label(
            strip,
            textvariable=self.conn_detail_var,
            font=(FONT, 9),
            fg=MUTED,
            bg=SURFACE,
            anchor="e",
        ).grid(row=0, column=6, sticky="ew", padx=(10, 16))

    def _build_signal_flow(self):
        flow = self._card(self)
        flow.grid(row=2, column=0, sticky="ew", padx=22, pady=(12, 0))

        inner = tk.Frame(flow, bg=SURFACE)
        inner.pack(fill="x", padx=16, pady=12)

        self._label(inner, "SIGNAL FLOW", 9, "bold").pack(side="left", padx=(0, 16))

        steps = [
            "PYTHON GUI",
            "TX ESP32",
            "FRAME + CHECKSUM",
            "MORSE",
            "GPIO17 + BC547",
            "LED55C IR",
        ]

        for i, step in enumerate(steps):
            pill = tk.Label(
                inner,
                text=step,
                font=(FONT, 8, "bold"),
                fg="#dbeafe",
                bg="#13253d",
                padx=10,
                pady=5,
            )
            pill.pack(side="left")

            if i < len(steps) - 1:
                self._label(inner, "→", 11, "bold", fg=ACCENT).pack(
                    side="left", padx=7
                )

    def _build_main_area(self):
        main = tk.Frame(self, bg=BG)
        main.grid(row=3, column=0, sticky="nsew", padx=22, pady=16)

        main.grid_columnconfigure(0, weight=0, minsize=420)
        main.grid_columnconfigure(1, weight=1)
        main.grid_rowconfigure(0, weight=1)

        left = tk.Frame(main, bg=BG, width=420)
        left.grid(row=0, column=0, sticky="nsw", padx=(0, 16))
        left.grid_propagate(False)

        right = tk.Frame(main, bg=BG)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(2, weight=1)

        self._build_message_card(left)
        self._build_receiver_card(left)
        self._build_quick_status_card(left)

        self._build_preview_card(right)
        self._build_tx_status_card(right)
        self._build_log_card(right)

    # -------------------- LEFT --------------------

    def _build_message_card(self, parent):
        card = self._card(parent)
        card.pack(fill="x", pady=(0, 14))

        body = tk.Frame(card, bg=SURFACE)
        body.pack(fill="x", padx=18, pady=18)

        self._label(body, "MESSAGE COMPOSER", 12, "bold").pack(anchor="w")
        self._label(
            body,
            "Type the text to send. Lowercase is converted automatically.",
            9,
            fg=MUTED,
            wraplength=360,
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

        shell = tk.Frame(
            body,
            bg=SURFACE_3,
            highlightthickness=1,
            highlightbackground="#31445f",
        )
        shell.pack(fill="x", pady=(14, 6))

        self.message_entry = tk.Entry(
            shell,
            textvariable=self.message_var,
            font=("Consolas", 14),
            bg=SURFACE_3,
            fg=TEXT,
            insertbackground=ACCENT,
            relief="flat",
            bd=0,
        )
        self.message_entry.pack(fill="x", padx=12, pady=13)

        tk.Label(
            body,
            textvariable=self.count_var,
            font=(FONT, 9),
            fg=MUTED,
            bg=SURFACE,
        ).pack(anchor="e")

        self.send_btn = tk.Button(
            body,
            text="TRANSMIT MESSAGE",
            command=self._send,
            font=(FONT, 12, "bold"),
            bg=ACCENT,
            fg="#062033",
            activebackground="#5bd7f5",
            activeforeground="#062033",
            disabledforeground="#536979",
            relief="flat",
            bd=0,
            pady=13,
            cursor="hand2",
        )
        self.send_btn.pack(fill="x", pady=(14, 0))
        self.send_btn.config(state="disabled")

    def _build_receiver_card(self, parent):
        card = self._card(parent)
        card.pack(fill="x", pady=(0, 14))

        body = tk.Frame(card, bg=SURFACE)
        body.pack(fill="x", padx=18, pady=18)

        self._label(body, "DESTINATION RECEIVER", 12, "bold").pack(anchor="w")
        self._label(
            body,
            "The IR signal is broadcast. Addressing decides which receiver accepts it.",
            9,
            fg=MUTED,
            wraplength=360,
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

        row = tk.Frame(body, bg=SURFACE)
        row.pack(fill="x", pady=(14, 0))

        self.rx1_card = self._receiver_choice(row, "RX1", "01")
        self.rx1_card.pack(side="left", fill="both", expand=True, padx=(0, 6))

        self.rx2_card = self._receiver_choice(row, "RX2", "02")
        self.rx2_card.pack(side="left", fill="both", expand=True, padx=(6, 0))

        self._refresh_receiver_choice()

    def _receiver_choice(self, parent, name, address):
        frame = tk.Frame(
            parent,
            bg=SURFACE_2,
            highlightthickness=2,
            highlightbackground="#334155",
            cursor="hand2",
        )

        n = self._label(frame, name, 15, "bold", bg=SURFACE_2)
        n.pack(pady=(14, 2))

        a = self._label(
            frame,
            f"Address {address}",
            9,
            fg=MUTED,
            bg=SURFACE_2,
        )
        a.pack(pady=(0, 14))

        for w in (frame, n, a):
            w.bind("<Button-1>", lambda _e, x=address: self._select_receiver(x))

        return frame

    def _build_quick_status_card(self, parent):
        card = self._card(parent)
        card.pack(fill="both", expand=True)

        body = tk.Frame(card, bg=SURFACE)
        body.pack(fill="both", expand=True, padx=18, pady=18)

        self._label(body, "PROJECT STATUS", 12, "bold").pack(anchor="w")

        rows = [
            ("UART LINK", "Ready"),
            ("MORSE ENCODER", "A–Z / 0–9"),
            ("CHECKSUM", "8-bit additive"),
            ("IR TX", "LED55C @ 940 nm"),
            ("RX ADDRESSES", "01 / 02"),
        ]

        for k, v in rows:
            line = tk.Frame(body, bg=SURFACE)
            line.pack(fill="x", pady=7)

            self._label(line, k, 8, "bold", fg=MUTED).pack(side="left")
            self._label(line, v, 9, "bold", fg=TEXT).pack(side="right")

    # -------------------- RIGHT --------------------

    def _build_preview_card(self, parent):
        card = self._card(parent)
        card.grid(row=0, column=0, sticky="ew", pady=(0, 14))

        body = tk.Frame(card, bg=SURFACE)
        body.pack(fill="both", padx=18, pady=18)

        self._label(body, "LIVE FRAME PREVIEW", 12, "bold").pack(anchor="w")
        self._label(
            body,
            "Exact address + message + checksum frame before Morse encoding.",
            9,
            fg=MUTED,
        ).pack(anchor="w", pady=(4, 0))

        grid = tk.Frame(body, bg=SURFACE)
        grid.pack(fill="x", pady=(14, 0))

        self._preview_tile(grid, 0, "RECEIVER", self.receiver_var, 1)
        self._preview_tile(grid, 1, "MESSAGE", self.preview_message_var, 2)
        self._preview_tile(grid, 2, "CHECKSUM", self.preview_checksum_var, 1)
        self._preview_tile(grid, 3, "FINAL FRAME", self.preview_frame_var, 3)

    def _preview_tile(self, parent, col, title, var, weight):
        parent.grid_columnconfigure(col, weight=weight)

        box = tk.Frame(
            parent,
            bg=SURFACE_3,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        box.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 6, 0))

        self._label(
            box,
            title,
            8,
            "bold",
            fg=MUTED,
            bg=SURFACE_3,
        ).pack(anchor="w", padx=12, pady=(10, 3))

        tk.Label(
            box,
            textvariable=var,
            font=("Consolas", 11, "bold"),
            fg=TEXT,
            bg=SURFACE_3,
            justify="left",
            wraplength=420,
        ).pack(anchor="w", padx=12, pady=(0, 11))

    def _build_tx_status_card(self, parent):
        card = self._card(parent)
        card.grid(row=1, column=0, sticky="ew", pady=(0, 14))

        body = tk.Frame(card, bg=SURFACE)
        body.pack(fill="x", padx=18, pady=16)

        top = tk.Frame(body, bg=SURFACE)
        top.pack(fill="x")

        self._label(top, "TRANSMISSION STATUS", 12, "bold").pack(side="left")

        self.tx_badge = tk.Label(
            top,
            textvariable=self.tx_status_var,
            font=(FONT, 9, "bold"),
            fg="#bae6fd",
            bg="#0c4a6e",
            padx=13,
            pady=6,
        )
        self.tx_badge.pack(side="right")

        tk.Label(
            body,
            textvariable=self.tx_detail_var,
            font=(FONT, 9),
            fg=MUTED,
            bg=SURFACE,
            anchor="w",
        ).pack(fill="x", pady=(7, 10))

        self.progress = ttk.Progressbar(
            body,
            style="Tx.Horizontal.TProgressbar",
            orient="horizontal",
            mode="indeterminate",
        )
        self.progress.pack(fill="x")

    def _build_log_card(self, parent):
        card = self._card(parent)
        card.grid(row=2, column=0, sticky="nsew")

        body = tk.Frame(card, bg=SURFACE)
        body.pack(fill="both", expand=True, padx=18, pady=16)

        top = tk.Frame(body, bg=SURFACE)
        top.pack(fill="x")

        self._label(top, "LIVE TRANSMISSION LOG", 12, "bold").pack(side="left")
        self._button(top, "CLEAR", self._clear_log, "#26364d").pack(side="right")

        shell = tk.Frame(
            body,
            bg="#040a12",
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        shell.pack(fill="both", expand=True, pady=(12, 0))

        sb = tk.Scrollbar(shell)
        sb.pack(side="right", fill="y")

        self.log = tk.Text(
            shell,
            bg="#040a12",
            fg="#cbd5e1",
            insertbackground=TEXT,
            font=("Consolas", 10),
            relief="flat",
            bd=0,
            wrap="word",
            yscrollcommand=sb.set,
            state="disabled",
        )
        self.log.pack(fill="both", expand=True, padx=10, pady=10)
        sb.config(command=self.log.yview)

        self.log.tag_configure("good", foreground="#86efac")
        self.log.tag_configure("info", foreground="#7dd3fc")
        self.log.tag_configure("warn", foreground="#fde68a")
        self.log.tag_configure("bad", foreground="#fca5a5")
        self.log.tag_configure("dim", foreground="#64748b")

        self._log("Studio ready.", "dim")
        self._log("Connect the TX ESP32 using the top bar.", "dim")

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
                bg = "#0b3142"
                border = ACCENT
            else:
                bg = SURFACE_2
                border = "#334155"

            card.config(bg=bg, highlightbackground=border)
            for child in card.winfo_children():
                child.config(bg=bg)

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

        except queue.Empty:
            pass

        self.after(80, self._poll_worker_queue)

    def _display_esp32_line(self, line):
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
            self.connection_badge.config(fg="#bbf7d0", bg="#14532d")
        elif state == "connecting":
            self.connection_badge.config(fg="#fde68a", bg="#713f12")
        else:
            self.connection_badge.config(fg="#fecaca", bg="#7f1d1d")

    def _set_tx_badge(self, state):
        mapping = {
            "ready": ("#bae6fd", "#0c4a6e"),
            "transmitting": ("#fef3c7", "#78350f"),
            "complete": ("#bbf7d0", "#14532d"),
            "error": ("#fecaca", "#7f1d1d"),
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
        try:
            if self.ser and self.ser.is_open:
                self.ser.close()
        except Exception:
            pass
        self.destroy()


if __name__ == "__main__":
    app = MorseIRStudio()
    app.mainloop()
