"""Morse IR Receiver Studio — project presentation and live PC monitor.

Standalone Tkinter + optional pyserial application. Read-only serial monitoring;
no changes to TX, RX1 or RX2 firmware and no acknowledgement link is implied.

Run: python Morse_IR_Receiver_Studio_FINAL.py
Offline: python Morse_IR_Receiver_Studio_FINAL.py --demo
Tests: python Morse_IR_Receiver_Studio_FINAL.py --selftest
"""
from __future__ import annotations

import argparse
import csv
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import queue
import re
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Optional

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None
    list_ports = None

BAUD_RATE = 115200
BG = '#F3F6FB'
SURFACE = '#FFFFFF'
INK = '#13233F'
SUBTLE = '#64748B'
BORDER = '#DFE6F2'
NAVY = '#0D1D33'
BLUE = '#1D4ED8'
BLUE_LIGHT = '#EAF1FF'
TEAL = '#087D91'
TEAL_LIGHT = '#E1F6FA'
AMBER = '#B36A18'
AMBER_LIGHT = '#FFF3DE'
RED = '#B83D51'
RED_LIGHT = '#FFF0F1'
MONO = 'Consolas'
FONT = 'Segoe UI'
MAX_LOG_ROWS = 1200
RECEIVED_FILES_ROOT = Path(__file__).resolve().parent / 'received_files'


def save_received_file(directory: Path, rx: str, contents: str, stamp: Optional[str] = None) -> Path:
    """Save a validated RX text file without overwriting an earlier reception.

    This stores the *normalized received text* on the receiver-monitoring PC,
    not inside the ESP32 flash. Caller must first verify FILE_COMPLETE.
    """
    if rx not in ('RX1', 'RX2'):
        raise ValueError('Invalid receiver name')
    if not isinstance(contents, str) or not contents or len(contents) > 40000:
        raise ValueError('Invalid received text length')
    if any(char not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ' for char in contents):
        raise ValueError('File contains characters outside the current Morse protocol')
    folder = Path(directory) / rx
    folder.mkdir(parents=True, exist_ok=True)
    stamp = stamp or datetime.now().strftime('%Y%m%d_%H%M%S')
    for suffix in range(1, 10001):
        filename = f'{rx}_received_{stamp}_{suffix:03d}.txt'
        destination = folder / filename
        try:
            with destination.open('x', encoding='ascii', newline='') as output:
                output.write(contents)
            return destination
        except FileExistsError:
            continue
    raise OSError('Too many files with the same timestamp')


def open_local_text_file(filepath: Path):
    """Open an already-saved text document in the operating system's editor."""
    path = Path(filepath).resolve(strict=True)
    if path.suffix.lower() != '.txt' or not path.is_file():
        raise ValueError('Only existing .txt files can be opened')
    if sys.platform == 'win32':
        os.startfile(str(path))
    elif sys.platform == 'darwin':
        subprocess.Popen(['open', str(path)])
    else:
        subprocess.Popen(['xdg-open', str(path)])



def clock_stamp() -> str:
    return datetime.now().strftime('%H:%M:%S')


@dataclass
class Event:
    receiver: str
    kind: str
    summary: str
    status: str = 'info'
    timestamp: str = field(default_factory=clock_stamp)


@dataclass
class ReceiverState:
    name: str
    address: str
    connected: bool = False
    port: str = ''
    startup_confirmed: bool = False
    identity_mismatch: bool = False
    activity: str = 'OFFLINE'
    last_message: str = '—'
    last_checksum: str = '—'
    accepted_messages: int = 0
    rejected_addresses: int = 0
    checksum_errors: int = 0
    interruptions: int = 0
    recoveries: int = 0
    packet_accepted: int = 0
    packet_total: int = 0
    completed_files: int = 0
    file_text: str = ''
    file_verified: bool = False
    file_characters: int = 0
    file_packets: int = 0
    received_sequences: set = field(default_factory=set)
    frame: str = ''
    frame_address: str = ''
    frame_message: str = ''
    received_checksum: str = ''
    calculated_checksum: str = ''
    collecting_file: bool = False
    file_lines: list = field(default_factory=list)
    pending_file_text: Optional[str] = None
    announced_packets: Optional[int] = None
    announced_characters: Optional[int] = None


class ReceiverParser:
    """Parse the actual Phase 8 ESP-IDF monitor lines. No UART writing."""

    def __init__(self):
        self.states = {
            'RX1': ReceiverState('RX1', '01'),
            'RX2': ReceiverState('RX2', '02'),
        }

    def reset(self):
        self.__init__()

    def parse(self, selected_receiver: str, source_line: str) -> list[Event]:
        st = self.states[selected_receiver]
        line = source_line.rstrip('\r\n')
        out: list[Event] = []

        def push(kind, summary, status='info'):
            out.append(Event(st.name, kind, summary, status))

        # A boot log identifies the board. Warn rather than silently relabeling it.
        detected = re.search(r'PHASE\s+[68][A-Z]?\s*-\s*(RX[12])\s+(?:FILE\s+)?RECEIVER', line)
        if detected:
            st.startup_confirmed = True
            st.identity_mismatch = detected.group(1) != st.name
            if st.identity_mismatch:
                st.activity = 'WRONG COM PORT'
                push('PORT WARNING', f'Firmware identifies {detected.group(1)}, not {st.name}. Check COM assignment.', 'bad')
            else:
                st.activity = 'BOOTING'
                push('STARTUP', f'{st.name} receiver firmware detected')
            return out

        if st.identity_mismatch:
            return out

        if st.collecting_file:
            if line == f'{st.name} FILE TEXT END':
                st.collecting_file = False
                st.pending_file_text = '\n'.join(st.file_lines)
                st.file_lines.clear()
            else:
                st.file_lines.append(line)
            return out

        if line == f'{st.name} FILE TEXT BEGIN':
            st.collecting_file = True
            st.file_lines.clear()
            st.pending_file_text = None
            return out

        if re.search(rf'^{st.name} READY\s*-\s*WAITING FOR IR', line):
            st.activity = 'WAITING FOR IR'
            push('READY', 'Receiver ready; waiting for IR')
            return out

        m = re.match(rf'^{st.name} RECEIVED:\s*\[(.*)\]$', line)
        if m:
            st.frame = m.group(1)
            st.frame_address = st.frame[:2]
            st.frame_message = ''
            st.received_checksum = ''
            st.calculated_checksum = ''
            st.activity = 'VALIDATING FRAME'
            return out

        if line.startswith('Address: '):
            st.frame_address = line[9:].strip()
            return out
        if line.startswith('Message: '):
            st.frame_message = line[9:]
            return out
        if line.startswith('Received checksum: '):
            st.received_checksum = line.split(':', 1)[1].strip()
            return out
        if line.startswith('Calculated checksum: '):
            st.calculated_checksum = line.split(':', 1)[1].strip()
            return out

        if line == 'RESULT: WRONG ADDRESS - REJECTED':
            st.rejected_addresses += 1
            st.activity = 'WRONG ADDRESS — REJECTED'
            push('ADDRESS REJECTED', f'Frame addressed to {st.frame_address or "another receiver"} rejected; content hidden', 'warn')
            return out

        if line == 'RESULT: CHECKSUM OK - ACCEPTED':
            if st.frame_address == st.address:
                st.accepted_messages += 1
                st.last_message = st.frame_message or '(empty)'
                st.last_checksum = f'{st.received_checksum} / {st.calculated_checksum}'
                st.activity = 'MESSAGE ACCEPTED'
                push('MESSAGE ACCEPTED', f'Message: {st.last_message} · Checksum {st.last_checksum}', 'good')
            else:
                push('INVALID ACCEPT', 'Unexpected accepted frame with non-matching address', 'bad')
            return out

        if line in ('RESULT: CHECKSUM FAILED', 'RESULT: INVALID CHECKSUM FIELD'):
            st.checksum_errors += 1
            st.activity = 'INVALID FRAME'
            push('CHECKSUM ERROR', line.removeprefix('RESULT: '), 'bad')
            return out

        if line.startswith('RESULT: FILE PACKET REJECTED'):
            st.activity = 'FILE PACKET REJECTED'
            push('FILE REJECTED', line.replace('RESULT: ', ''), 'bad')
            return out

        m = re.match(rf'^{st.name} FILE PACKET (\d{{3}})/(\d{{3}}) ACCEPTED(?:; STORED \d+/\d+)?$', line)
        if m:
            seq, total = map(int, m.groups())
            if st.file_verified and seq == 1:
                st.received_sequences.clear()
                st.file_verified = False
                st.packet_accepted = 0
                st.packet_total = 0
                st.announced_packets = None
                st.announced_characters = None
                st.pending_file_text = None
            if st.packet_total != total and st.packet_total:
                st.received_sequences.clear()
            st.packet_total = total
            st.received_sequences.add(seq)
            st.packet_accepted = len(st.received_sequences)
            st.activity = 'RECEIVING FILE'
            push('FILE PACKET', f'Packet {seq}/{total} accepted · {st.packet_accepted}/{total} stored', 'good')
            return out

        m = re.match(rf'^{st.name} FILE COMPLETE: (\d+) PACKETS, (\d+) CHARACTERS$', line)
        if m:
            st.announced_packets, st.announced_characters = map(int, m.groups())
            st.activity = 'RECONSTRUCTING FILE'
            return out

        if line == f'{st.name}_EVENT:FILE_COMPLETE':
            text = st.pending_file_text
            count = st.announced_characters
            packets = st.announced_packets
            if (text is None or count is None or packets is None or
                    len(text) != count or st.packet_accepted != packets or
                    st.packet_total != packets):
                st.activity = 'FILE CONFIRMATION INCOMPLETE'
                push('FILE WARNING', 'Completion reported but PC could not verify text length and packet count', 'warn')
            else:
                st.file_text = text
                st.file_characters = count
                st.file_packets = packets
                st.file_verified = True
                st.completed_files += 1
                st.activity = 'FILE COMPLETE'
                push('FILE COMPLETE', f'{packets} packets · {count} characters · PC log consistency checked', 'good')
            st.announced_packets = None
            st.announced_characters = None
            st.pending_file_text = None
            return out

        if line.startswith(f'{st.name} FILE: DUPLICATE PACKET'):
            push('DUPLICATE', line.removeprefix(f'{st.name} FILE: '), 'warn')
            return out

        if ('PARTIAL TRANSFER DISCARDED' in line or
                'INCOMPLETE FILE ABORTED' in line) and line.startswith(st.name):
            st.received_sequences.clear()
            st.packet_accepted = 0
            st.packet_total = 0
            st.file_verified = False
            st.activity = 'TRANSFER ABORTED'
            push('FILE ABORTED', 'Incomplete transfer discarded', 'warn')
            return out

        if line == f'{st.name} SIGNAL INTERRUPTED':
            st.interruptions += 1
            st.activity = 'SIGNAL INTERRUPTED'
            push('INTERRUPTION', 'Corrupted or interrupted IR frame rejected', 'bad')
            return out

        if line == f'{st.name} AUTO RECOVERY COMPLETE':
            st.recoveries += 1
            st.activity = 'RECOVERED'
            push('RECOVERY', 'Automatic recovery complete', 'good')
            return out

        # Intentionally ignore 'Decoded:', raw frame and payload lines in the
        # event log. Rejected message contents must not appear as accepted data.
        return out


class SerialReader(threading.Thread):
    """Single reader owns one COM port; communicates with Tk only via queue."""

    def __init__(self, receiver, port, sink):
        super().__init__(daemon=True, name=f'{receiver}-{port}')
        self.receiver = receiver
        self.port = port
        self.sink = sink
        self.stop_flag = threading.Event()

    def run(self):
        if serial is None:
            self.sink.put(('problem', self.receiver, 'pyserial is not installed. Run: python -m pip install pyserial'))
            return
        try:
            with serial.Serial(self.port, BAUD_RATE, timeout=0.4) as device:
                self.sink.put(('connected', self.receiver, self.port))
                while not self.stop_flag.is_set():
                    raw = device.readline()
                    if raw:
                        line = raw.decode('utf-8', errors='replace').rstrip('\r\n')
                        self.sink.put(('line', self.receiver, line))
        except Exception as exc:
            if not self.stop_flag.is_set():
                self.sink.put(('problem', self.receiver, str(exc)))
        finally:
            self.sink.put(('stopped', self.receiver, self.port))

    def stop(self):
        self.stop_flag.set()


def make_demo_stream() -> list[tuple[str, str]]:
    """Realistic simulated log format from the actual Phase 8 firmware."""
    message = 'HELLO WORLD THIS IS OUR MORSE IR FILE TRANSFER PROJECT'
    stream = [
        ('RX1', 'PHASE 8 - RX1 FILE RECEIVER'),
        ('RX2', 'PHASE 8 - RX2 FILE RECEIVER'),
        ('RX1', 'RX1 READY - WAITING FOR IR'),
        ('RX2', 'RX2 READY - WAITING FOR IR'),
        ('RX1', 'RX1 RECEIVED: [02SOS087]'),
        ('RX1', 'Address: 02'),
        ('RX1', 'Message: SOS'),
        ('RX1', 'RESULT: WRONG ADDRESS - REJECTED'),
        ('RX2', 'RX2 RECEIVED: [02SOS087]'),
        ('RX2', 'Address: 02'),
        ('RX2', 'Message: SOS'),
        ('RX2', 'Received checksum: 087'),
        ('RX2', 'Calculated checksum: 087'),
        ('RX2', 'RESULT: CHECKSUM OK - ACCEPTED'),
        ('RX2', 'RX2 FILE PACKET 001/002 ACCEPTED; STORED 1/2'),
        ('RX2', 'RX2_EVENT:FILE_PACKET_OK'),
        ('RX2', 'RX2 FILE PACKET 002/002 ACCEPTED'),
        ('RX2', 'RX2 FILE COMPLETE: 2 PACKETS, 54 CHARACTERS'),
        ('RX2', 'RX2 FILE TEXT BEGIN'),
        ('RX2', message),
        ('RX2', 'RX2 FILE TEXT END'),
        ('RX2', 'RX2_EVENT:FILE_COMPLETE'),
        ('RX1', 'RX1 SIGNAL INTERRUPTED'),
        ('RX1', 'RX1 AUTO RECOVERY COMPLETE'),
    ]
    return stream


def selftest():
    p = ReceiverParser()
    for rx, line in make_demo_stream():
        p.parse(rx, line)
    r1, r2 = p.states['RX1'], p.states['RX2']
    assert r1.rejected_addresses == 1 and r1.accepted_messages == 0
    assert r1.interruptions == 1 and r1.recoveries == 1
    assert r1.file_text == ''
    assert r2.last_message == 'SOS' and r2.accepted_messages == 1
    assert r2.file_verified and r2.file_packets == 2 and r2.file_characters == 54
    assert r2.file_text == 'HELLO WORLD THIS IS OUR MORSE IR FILE TRANSFER PROJECT'
    assert r2.packet_accepted == 2
    assert not ReceiverParser().states['RX2'].file_verified

    p = ReceiverParser()
    for rx, line in [('RX2','PHASE 8 - RX1 FILE RECEIVER'),('RX2','RX2 READY - WAITING FOR IR')]:
        p.parse(rx,line)
    assert p.states['RX2'].identity_mismatch

    p = ReceiverParser()
    for rx, line in [('RX1','RX1 FILE PACKET 001/002 ACCEPTED; STORED 1/2'),
                     ('RX1','RX1 FILE COMPLETE: 2 PACKETS, 54 CHARACTERS'),
                     ('RX1','RX1 FILE TEXT BEGIN'), ('RX1','SHORT'),
                     ('RX1','RX1 FILE TEXT END'),('RX1','RX1_EVENT:FILE_COMPLETE')]:
        p.parse(rx,line)
    assert not p.states['RX1'].file_verified

    p = ReceiverParser()
    for line in ('RX1 RECEIVED: [01SOS999]', 'Address: 01', 'Message: SOS',
                 'RESULT: CHECKSUM FAILED', 'RX1 SIGNAL INTERRUPTED',
                 'RX1 AUTO RECOVERY COMPLETE'):
        p.parse('RX1', line)
    assert p.states['RX1'].checksum_errors == 1
    assert p.states['RX1'].interruptions == 1

    with tempfile.TemporaryDirectory() as temp_dir:
        first = save_received_file(Path(temp_dir), 'RX2', r2.file_text, '20261027_120000')
        second = save_received_file(Path(temp_dir), 'RX2', r2.file_text, '20261027_120000')
        assert first != second and first.suffix == '.txt' and second.suffix == '.txt'
        assert first.read_text(encoding='ascii') == r2.file_text
        assert first.parent.name == 'RX2'
        try:
            save_received_file(Path(temp_dir), '../RX1', r2.file_text)
        except ValueError:
            pass
        else:
            raise AssertionError('Path traversal receiver name not rejected')
    print('SELFTEST PASS: auto-save, unique filenames, file contents, safe paths')
    print('SELFTEST PASS: address filtering, valid message, packets, reconstructed file,')
    print('identity mismatch, incomplete file, checksum failure, interruption and recovery')


class ReceiverStudio(tk.Tk):
    def __init__(self, demo=False):
        super().__init__()
        self.title('Morse IR | Receiver Studio')
        self.geometry('1360x800')
        self.minsize(1100, 690)
        self.configure(bg=BG)
        self.parser = ReceiverParser()
        self.rx_queue = queue.Queue()
        self.readers: dict[str, SerialReader] = {}
        self.recorded_events: list[Event] = []
        self.demonstration = False
        self.display_receiver = tk.StringVar(value='RX2')
        self.port_vars = {'RX1': tk.StringVar(), 'RX2': tk.StringVar()}
        self.status_var = tk.StringVar(value='OFFLINE — Connect RX1 and/or RX2 to begin live monitoring')
        self.file_info_var = tk.StringVar(value='No verified reconstructed file')
        self.saved_file_paths: dict[str, list[Path]] = {'RX1': [], 'RX2': []}
        self._load_saved_files()
        self._style()
        self._build()
        self.refresh_ports()
        self.after(100, self._pump)
        self.protocol('WM_DELETE_WINDOW', self._close)
        if demo:
            self.after(300, self.load_demo)

    def _style(self):
        s = ttk.Style(self)
        try:
            s.theme_use('clam')
        except tk.TclError:
            pass
        s.configure('Port.TCombobox', padding=7, font=(FONT, 10),
                    fieldbackground=SURFACE, background=SURFACE,
                    foreground=INK, bordercolor=BORDER)
        s.map('Port.TCombobox', fieldbackground=[('readonly', SURFACE)])
        s.configure('Data.Treeview', background=SURFACE, fieldbackground=SURFACE,
                    foreground=INK, rowheight=29, borderwidth=0,
                    font=(FONT, 9))
        s.configure('Data.Treeview.Heading', background=BG, foreground=SUBTLE,
                    font=(FONT, 9, 'bold'), padding=8, relief='flat')
        s.map('Data.Treeview', background=[('selected', BLUE_LIGHT)],
              foreground=[('selected', INK)])
        s.configure('Blue.Horizontal.TProgressbar', troughcolor='#E8EDF6',
                    background=BLUE, thickness=9, bordercolor='#E8EDF6')
        s.configure('Teal.Horizontal.TProgressbar', troughcolor='#E8EDF6',
                    background=TEAL, thickness=9, bordercolor='#E8EDF6')

    def label(self, parent, text='', font=10, color=INK, bold=False, **kwargs):
        return tk.Label(parent, text=text, bg=parent.cget('bg'), fg=color,
                        font=(FONT, font, 'bold' if bold else 'normal'), **kwargs)

    def button(self, parent, text, command, primary=False, caution=False, size=10):
        bg = BLUE if primary else (RED_LIGHT if caution else BLUE_LIGHT)
        fg = 'white' if primary else (RED if caution else '#343EAD')
        return tk.Button(parent, text=text, command=command, bg=bg, fg=fg,
                         font=(FONT, size, 'bold'), relief='flat', bd=0,
                         activebackground='#DDE4FE' if not primary else '#383FBF',
                         activeforeground=fg, padx=14, pady=8, cursor='hand2')

    def section(self, parent, title, caption=None):
        outer = tk.Frame(parent, bg=SURFACE, highlightbackground=BORDER, highlightthickness=1)
        top = tk.Frame(outer, bg=SURFACE)
        top.pack(fill='x', padx=15, pady=(12, 5))
        self.label(top, title, 12, bold=True).pack(side='left')
        if caption:
            self.label(top, caption, 9, SUBTLE).pack(side='right')
        return outer, top

    def _build(self):
        header = tk.Frame(self, bg=SURFACE)
        header.pack(fill='x')
        left = tk.Frame(header, bg=SURFACE)
        left.pack(side='left', padx=22, pady=15)
        mark = tk.Label(left, text='◉', bg=BLUE, fg='white', font=(FONT, 24, 'bold'),
                        width=2, height=1)
        mark.pack(side='left', padx=(0, 13))
        title = tk.Frame(left, bg=SURFACE)
        title.pack(side='left')
        self.label(title, 'MORSE IR  /  RECEIVER STUDIO', 19, bold=True).pack(anchor='w')
        self.label(title, 'Dual-receiver monitoring   /   Message validation   /   Automatic .txt saving',
                   9, SUBTLE).pack(anchor='w', pady=(3, 0))
        right = tk.Frame(header, bg=SURFACE)
        right.pack(side='right', padx=20)
        self.button(right, 'Import log', self.import_log).pack(side='left', padx=4)
        self.button(right, 'Export CSV', self.export_history).pack(side='left', padx=4)
        self.button(right, 'Reset offline', self.reset_offline_view).pack(side='left', padx=4)

        wrapper = tk.Frame(self, bg=BG)
        wrapper.pack(fill='both', expand=True, padx=20, pady=(10, 8))
        banner = tk.Frame(wrapper, bg=BLUE_LIGHT)
        banner.pack(fill='x', pady=(0, 10))
        self.banner_label = tk.Label(banner, textvariable=self.status_var, bg=BLUE_LIGHT,
                                     fg='#343EAD', font=(FONT, 10, 'bold'), anchor='w')
        self.banner_label.pack(fill='x', padx=14, pady=8)

        connection, _ = self.section(wrapper, 'Connect your receivers',
                                     'Connect available receivers independently · 115200 baud')
        connection.pack(fill='x', pady=(0, 11))
        self.button(connection.winfo_children()[0], 'Refresh COM ports', self.refresh_ports, size=9).pack(side='right', padx=8)
        slots = tk.Frame(connection, bg=SURFACE)
        slots.pack(fill='x', padx=15, pady=(2, 12))
        self.connection_badges = {}
        for rx in ('RX1', 'RX2'):
            panel = tk.Frame(slots, bg=BG)
            panel.pack(side='left', fill='x', expand=True, padx=(0, 10) if rx == 'RX1' else (0, 0))
            self.label(panel, f'{rx}  /  Address {self.parser.states[rx].address}', 10, bold=True).pack(side='left', padx=(10, 10))
            combo = ttk.Combobox(panel, textvariable=self.port_vars[rx], width=12,
                                 state='readonly', style='Port.TCombobox')
            combo.pack(side='left', padx=(0, 6), pady=7)
            self.button(panel, 'Connect', lambda r=rx: self.connect_receiver(r), primary=True, size=9).pack(side='left', padx=3)
            self.button(panel, 'Disconnect', lambda r=rx: self.disconnect_receiver(r), size=9).pack(side='left', padx=3)
            badge = self.label(panel, 'OFFLINE', 9, SUBTLE, bold=True)
            badge.pack(side='right', padx=(4, 10))
            self.connection_badges[rx] = badge
        # Refresh control lives in the section header to avoid wasting vertical space.

        cards = tk.Frame(wrapper, bg=BG)
        cards.pack(fill='x', pady=(0, 11))
        self.card_fields = {}
        for rx in ('RX1', 'RX2'):
            card = tk.Frame(cards, bg=SURFACE, highlightbackground=BORDER, highlightthickness=1)
            card.pack(side='left', fill='both', expand=True,
                      padx=(0, 8) if rx == 'RX1' else (8, 0))
            hdr = tk.Frame(card, bg=SURFACE)
            hdr.pack(fill='x', padx=16, pady=(13, 5))
            self.label(hdr, f'{rx}  /  ADDRESS {self.parser.states[rx].address}', 12, bold=True).pack(side='left')
            stat = self.label(hdr, 'OFFLINE', 9, SUBTLE, bold=True)
            stat.pack(side='right')
            last = self.label(card, 'Last accepted message: —', 10, SUBTLE, anchor='w', wraplength=470, justify='left')
            last.pack(fill='x', padx=16, pady=2)
            info = self.label(card, 'Messages 0  ·  Rejected 0  ·  Errors 0', 9, SUBTLE, anchor='w')
            info.pack(fill='x', padx=16, pady=(5, 8))
            progress_line = tk.Frame(card, bg=SURFACE)
            progress_line.pack(fill='x', padx=16)
            self.label(progress_line, 'File packet reception', 9, SUBTLE).pack(side='left')
            progress_label = self.label(progress_line, '0 / 0', 9, SUBTLE, bold=True)
            progress_label.pack(side='right')
            pbar = ttk.Progressbar(card, mode='determinate', maximum=100, value=0,
                                   style='Blue.Horizontal.TProgressbar' if rx == 'RX1' else 'Teal.Horizontal.TProgressbar')
            pbar.pack(fill='x', padx=16, pady=(6, 13))
            self.card_fields[rx] = dict(status=stat, last=last, info=info,
                                        progress_label=progress_label, progress=pbar)

        middle = tk.Frame(wrapper, bg=BG)
        middle.pack(fill='both', expand=True)
        middle.grid_columnconfigure(0, weight=5)
        middle.grid_columnconfigure(1, weight=6)
        middle.grid_rowconfigure(0, weight=1)

        left_frame, left_top = self.section(middle, 'Received text file', 'Validated and ready to open')
        left_frame.grid(row=0, column=0, sticky='nsew', padx=(0, 8))
        switch = tk.Frame(left_frame, bg=SURFACE)
        switch.pack(fill='x', padx=15, pady=(3, 6))
        self.label(switch, 'Show file from:', 9, SUBTLE).pack(side='left')
        for rx in ('RX1', 'RX2'):
            tk.Radiobutton(switch, text=rx, variable=self.display_receiver, value=rx,
                           command=self._show_file, bg=SURFACE, activebackground=SURFACE,
                           fg=INK, font=(FONT, 9, 'bold'), selectcolor=SURFACE).pack(side='left', padx=7)
        self.button(switch, 'Browse saved files', self.show_saved_files, size=9).pack(side='right', padx=(5, 0))
        self.button(switch, 'Open latest .txt', self.open_latest_file, size=9).pack(side='right', padx=(5, 0))
        self.button(switch, 'Save copy...', self.save_file, primary=True, size=9).pack(side='right')
        inf = self.label(left_frame, textvariable=self.file_info_var, font=9, color=SUBTLE, anchor='w')
        inf.pack(fill='x', padx=15, pady=(1, 8))
        file_box = tk.Frame(left_frame, bg='#F9FBFF', highlightbackground=BORDER, highlightthickness=1)
        file_box.pack(fill='both', expand=True, padx=15, pady=(0, 12))
        self.file_text = tk.Text(file_box, wrap='word', font=(MONO, 11), bg='#F9FBFF',
                                 fg=INK, relief='flat', bd=0, padx=13, pady=12, state='disabled')
        self.file_text.pack(fill='both', expand=True)

        right_frame, right_top = self.section(middle, 'Activity & diagnostics', 'Live UART events and errors')
        right_frame.grid(row=0, column=1, sticky='nsew', padx=(8, 0))
        # One compact panel with two tabs: fits comfortably on 720px screens.
        notebook = ttk.Notebook(right_frame)
        notebook.pack(fill='both', expand=True, padx=14, pady=(2, 12))
        history_container = tk.Frame(notebook, bg=SURFACE)
        notebook.add(history_container, text='  Event history  ')
        hist_scroller = ttk.Scrollbar(history_container, orient='vertical')
        hist_scroller.pack(side='right', fill='y')
        self.history = ttk.Treeview(history_container, columns=('time','receiver','event','detail'),
                                    show='headings', style='Data.Treeview',
                                    yscrollcommand=hist_scroller.set, height=7)
        for col,title,w,anchor in [('time','Time',77,'w'),('receiver','RX',58,'w'),
                                    ('event','Event',125,'w'),('detail','Details',290,'w')]:
            self.history.heading(col, text=title)
            self.history.column(col, width=w, minwidth=w, stretch=(col=='detail'), anchor=anchor)
        self.history.pack(side='left', fill='both', expand=True)
        hist_scroller.config(command=self.history.yview)
        self.history.tag_configure('good', foreground=TEAL)
        self.history.tag_configure('warn', foreground=AMBER)
        self.history.tag_configure('bad', foreground=RED)
        self.history.tag_configure('info', foreground=INK)
        console_area = tk.Frame(notebook, bg=NAVY)
        notebook.add(console_area, text='  Event console  ')
        self.console = tk.Text(console_area, height=7, bg=NAVY, fg='#CBD5E7',
                               wrap='word', font=(MONO, 9), relief='flat', bd=0,
                               padx=12, pady=9, state='disabled')
        self.console.pack(fill='both', expand=True)

        footer = tk.Frame(wrapper, bg=BG)
        footer.pack(fill='x', pady=(7, 0))
        self.label(footer, 'Verified live files auto-save to received_files/RX1 or RX2  ·  Double-click to open',
                   9, SUBTLE).pack(side='left')
        self.label(footer, 'No return acknowledgement  ·  Receiver status confirms delivery',
                   9, AMBER).pack(side='right')
        self._redraw_all()

    def _banner(self, text, mode=None):
        self.status_var.set(text)
        if mode == 'demo':
            self.banner_label.config(bg=AMBER_LIGHT, fg=AMBER)
            self.banner_label.master.config(bg=AMBER_LIGHT)
        elif mode == 'live':
            self.banner_label.config(bg=TEAL_LIGHT, fg=TEAL)
            self.banner_label.master.config(bg=TEAL_LIGHT)
        else:
            self.banner_label.config(bg=BLUE_LIGHT, fg='#343EAD')
            self.banner_label.master.config(bg=BLUE_LIGHT)

    def _event(self, event: Event):
        self.recorded_events.append(event)
        if len(self.recorded_events) > MAX_LOG_ROWS:
            self.recorded_events.pop(0)
            items = self.history.get_children()
            if items:
                self.history.delete(items[0])
        self.history.insert('', 'end', values=(event.timestamp, event.receiver,
                                             event.kind, event.summary), tags=(event.status,))
        self.history.yview_moveto(1.0)
        self.console.configure(state='normal')
        self.console.insert('end', f'[{event.timestamp}] {event.receiver} | {event.kind}: {event.summary}\n')
        if int(self.console.index('end-1c').split('.')[0]) > 280:
            self.console.delete('1.0', '70.0')
        self.console.see('end')
        self.console.configure(state='disabled')

    def _feed_line(self, rx, line):
        evs = self.parser.parse(rx, line)
        for e in evs:
            self._event(e)
            if (e.kind == 'FILE COMPLETE' and not self.demonstration
                    and self.parser.states[rx].connected):
                self._auto_save_completed_file(rx)
        self._redraw_card(rx)
        if self.display_receiver.get() == rx and (evs or line.endswith('FILE TEXT END')):
            self._show_file()

    def _redraw_card(self, rx):
        st = self.parser.states[rx]
        f = self.card_fields[rx]
        f['status'].config(text=st.activity, fg=(RED if st.identity_mismatch or 'ERROR' in st.activity
                         else TEAL if 'COMPLETE' in st.activity or 'ACCEPTED' in st.activity
                         else AMBER if 'REJECTED' in st.activity or 'INTERRUPTED' in st.activity
                         else SUBTLE))
        msg = st.last_message.replace('\n', ' ')
        if len(msg) > 64:
            msg = msg[:61] + '...'
        f['last'].config(text=f'Last accepted message: {msg}')
        f['info'].config(text=(f'Messages {st.accepted_messages}  ·  Address rejects {st.rejected_addresses}'
                               f'  ·  Checksum errors {st.checksum_errors}  ·  Files {st.completed_files}'))
        f['progress_label'].config(text=f'{st.packet_accepted} / {st.packet_total}')
        f['progress'].config(value=(100*st.packet_accepted/st.packet_total if st.packet_total else 0))
        connection = 'CONNECTED' if st.connected else 'OFFLINE'
        self.connection_badges[rx].config(text=connection, fg=TEAL if st.connected else SUBTLE)

    def _redraw_all(self):
        for rx in ('RX1','RX2'):
            self._redraw_card(rx)
        self._show_file()

    def _show_file(self):
        rx = self.display_receiver.get()
        st = self.parser.states[rx]
        if st.file_verified:
            text = st.file_text
            source = 'DEMO · ' if self.demonstration else 'LIVE · '
            self.file_info_var.set(f'{source}{rx} · {st.file_packets} packets · {st.file_characters} characters · Validated by receiver; live transfers auto-save on PC')
        else:
            text = (f'No completed, verified file for {rx}.\n\n'
                    'Live mode: connect receiver via USB and transmit a file.\n'
                    'Offline: import a receiver log, or connect RX1/RX2 for live reception.')
            self.file_info_var.set(f'{rx} · No verified reconstructed file')
        self.file_text.configure(state='normal')
        self.file_text.delete('1.0', 'end')
        self.file_text.insert('1.0', text)
        self.file_text.configure(state='disabled')

    def _pump(self):
        try:
            for _ in range(300):
                typ, rx, payload = self.rx_queue.get_nowait()
                if typ == 'line':
                    self._feed_line(rx, payload)
                elif typ == 'connected':
                    st = self.parser.states[rx]
                    st.connected, st.port, st.activity = True, payload, 'CONNECTED — AWAITING IR'
                    self._event(Event(rx, 'CONNECTED', f'Serial monitor connected on {payload}', 'good'))
                    self._redraw_card(rx)
                    self._banner('LIVE MONITORING — Connected to actual ESP32 serial data', 'live')
                elif typ == 'problem':
                    self.parser.states[rx].activity = 'SERIAL ERROR'
                    self._event(Event(rx, 'SERIAL ERROR', payload, 'bad'))
                    self._redraw_card(rx)
                elif typ == 'stopped':
                    st = self.parser.states[rx]
                    st.connected = False
                    if st.activity != 'SERIAL ERROR':
                        st.activity = 'OFFLINE'
                    self.readers.pop(rx, None)
                    self._redraw_card(rx)
        except queue.Empty:
            pass
        self.after(100, self._pump)

    def refresh_ports(self):
        ports = []
        if list_ports is not None:
            try:
                ports = sorted(p.device for p in list_ports.comports())
            except Exception:
                ports = []
        for rx, var in self.port_vars.items():
            combo = None
            # Traverse by the bound StringVar; do not use unsupported widget internals.
            def visit(parent):
                nonlocal combo
                for w in parent.winfo_children():
                    if isinstance(w, ttk.Combobox) and str(w.cget('textvariable')) == str(var):
                        combo = w
                    visit(w)
            visit(self)
            if combo:
                combo['values'] = ports
                if var.get() not in ports:
                    var.set(ports[0] if len(ports) == 1 else '')
        if serial is None:
            self._banner('OFFLINE — Install pyserial for live COM monitoring: python -m pip install pyserial')

    def connect_receiver(self, rx):
        if self.demonstration:
            messagebox.showinfo('Demo mode', 'Clear the demo before connecting a live receiver.'); return
        port = self.port_vars[rx].get().strip()
        if not port:
            messagebox.showwarning('Select COM port', f'Select the COM port for {rx}, then connect.'); return
        if rx in self.readers:
            messagebox.showinfo('Already connected', f'{rx} is already connecting or connected.'); return
        if any(t.port == port for t in self.readers.values()):
            messagebox.showerror('COM port busy', 'The same COM port cannot be used for both receivers.'); return
        if serial is None:
            messagebox.showerror('pyserial not installed', 'Run: python -m pip install pyserial'); return
        worker = SerialReader(rx, port, self.rx_queue)
        self.readers[rx] = worker
        self.parser.states[rx].activity = 'CONNECTING'
        worker.start()
        self._redraw_card(rx)

    def disconnect_receiver(self, rx):
        worker = self.readers.get(rx)
        if worker:
            worker.stop()
            self.parser.states[rx].activity = 'DISCONNECTING'
            self._redraw_card(rx)

    def _clear_history_only(self):
        self.recorded_events.clear()
        self.history.delete(*self.history.get_children())
        self.console.config(state='normal')
        self.console.delete('1.0', 'end')
        self.console.config(state='disabled')

    def clear_view(self):
        self._clear_history_only()
        self._event(Event('SYSTEM','CLEARED','Event view cleared; receiver state and saved file unchanged'))

    def reset_offline_view(self):
        if self.readers:
            messagebox.showwarning('Live connection', 'Disconnect receivers before resetting the monitor.')
            return
        self.demonstration = False
        self.parser.reset()
        self._clear_history_only()
        self._banner('OFFLINE — Ready for a live RX1/RX2 COM connection')
        self._redraw_all()

    def load_demo(self):
        if self.readers:
            messagebox.showwarning('Live connection', 'Disconnect live receiver COM ports before loading demo data.'); return
        self.demonstration = True
        self.parser.reset()
        self._clear_history_only()
        self._banner('DEMO MODE — Simulated firmware log events; no ESP32 data is being received', 'demo')
        for rx, line in make_demo_stream():
            self._feed_line(rx, line)
        self._redraw_all()

    def import_log(self):
        if self.readers:
            messagebox.showwarning('Live connection', 'Disconnect live receivers before importing a log.'); return
        path = filedialog.askopenfilename(title='Open ESP-IDF receiver monitor text log',
                                          filetypes=[('Log files','*.txt *.log'), ('All files','*.*')])
        if not path:
            return
        assigned = self.display_receiver.get()
        try:
            lines = Path(path).read_text(encoding='utf-8-sig', errors='replace').splitlines()
            if len(lines) > 100000:
                raise ValueError('Log exceeds 100,000 lines; select a smaller log.')
        except (OSError, ValueError) as exc:
            messagebox.showerror('Import failed', str(exc)); return
        inferred = re.search(r'(RX[12])', '\n'.join(lines[:150]), flags=re.I)
        if inferred:
            assigned = inferred.group(1).upper()
        self.demonstration = True
        self.parser.reset()
        self._clear_history_only()
        self._banner(f'IMPORTED LOG — {Path(path).name} · offline replay (not live data)', 'demo')
        for line in lines:
            self._feed_line(assigned, line)
        self.display_receiver.set(assigned)
        self._redraw_all()
        self._event(Event('SYSTEM','LOG IMPORT',f'{len(lines)} lines loaded from {Path(path).name}'))

    def _load_saved_files(self):
        """Discover previous saves so they remain clickable after app restart."""
        for rx in ('RX1', 'RX2'):
            folder = RECEIVED_FILES_ROOT / rx
            try:
                files = [p for p in folder.glob('*.txt') if p.is_file()]
                self.saved_file_paths[rx] = sorted(files, reverse=True)
            except OSError:
                self.saved_file_paths[rx] = []

    def _auto_save_completed_file(self, rx):
        """Called only on verified FILE COMPLETE events from live serial."""
        st = self.parser.states[rx]
        if not st.file_verified or not st.file_text:
            return
        try:
            path = save_received_file(RECEIVED_FILES_ROOT, rx, st.file_text)
        except (OSError, UnicodeError, ValueError) as exc:
            self._event(Event(rx, 'SAVE ERROR', f'Automatic file saving failed: {exc}', 'bad'))
            return
        self.saved_file_paths[rx].insert(0, path)
        self._event(Event(rx, 'FILE AUTO SAVED', f'{path.name} · {st.file_characters} chars', 'good'))
        if self.display_receiver.get() == rx:
            self._show_file()

    def open_latest_file(self):
        rx = self.display_receiver.get()
        self._load_saved_files()
        paths = self.saved_file_paths[rx]
        if not paths:
            messagebox.showinfo('No saved file', f'No saved .txt files yet for {rx}. In live mode, completed files save automatically.')
            return
        self._open_saved_path(paths[0])

    def _open_saved_path(self, path):
        try:
            resolved = Path(path).resolve(strict=True)
            root = RECEIVED_FILES_ROOT.resolve()
            if root not in resolved.parents or resolved.suffix.lower() != '.txt':
                raise ValueError('File is outside the saved-receptions directory')
            open_local_text_file(resolved)
        except (OSError, ValueError) as exc:
            messagebox.showerror('Cannot open text file', str(exc))

    def show_saved_files(self):
        """List every completed receiver-side PC file; double-click to open."""
        self._load_saved_files()
        dialog = tk.Toplevel(self)
        dialog.title('Received text files — double-click to open')
        dialog.geometry('760x450')
        dialog.minsize(540, 320)
        dialog.configure(bg=BG)
        header = tk.Frame(dialog, bg=SURFACE)
        header.pack(fill='x')
        self.label(header, 'Saved receiver text files', 15, bold=True).pack(side='left', padx=17, pady=14)
        self.label(header, 'Double-click a file to open it', 9, SUBTLE).pack(side='right', padx=17)
        body = tk.Frame(dialog, bg=SURFACE)
        body.pack(fill='both', expand=True, padx=15, pady=12)
        columns = ('rx', 'file', 'directory')
        tree = ttk.Treeview(body, columns=columns, show='headings', style='Data.Treeview')
        for name, title, width in [('rx','Receiver',92),('file','Text file',300),('directory','Storage folder',280)]:
            tree.heading(name, text=title)
            tree.column(name, width=width, minwidth=75, stretch=(name != 'rx'))
        bar = ttk.Scrollbar(body, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=bar.set)
        bar.pack(side='right', fill='y')
        tree.pack(side='left', fill='both', expand=True)
        index: dict[str, Path] = {}
        for rx in ('RX1', 'RX2'):
            for p in self.saved_file_paths[rx]:
                iid = tree.insert('', 'end', values=(rx, p.name, str(p.parent)))
                index[iid] = p
        def open_selected(event=None):
            chosen = tree.selection()
            if chosen:
                self._open_saved_path(index[chosen[0]])
        tree.bind('<Double-1>', open_selected)
        footer = tk.Frame(dialog, bg=BG)
        footer.pack(fill='x', padx=15, pady=(0, 12))
        self.button(footer, 'Open selected .txt', open_selected, primary=True).pack(side='left')
        self.button(footer, 'Close', dialog.destroy).pack(side='right')
        dialog.transient(self)

    def save_file(self):
        rx = self.display_receiver.get()
        st = self.parser.states[rx]
        if not st.file_verified:
            messagebox.showwarning('No verified file', f'{rx} has no completed file verified in its monitor logs.'); return
        target = filedialog.asksaveasfilename(title='Save reconstructed text',
                         defaultextension='.txt', initialfile=f'{rx.lower()}_received_file.txt',
                         filetypes=[('Text files','*.txt')])
        if not target:
            return
        try:
            Path(target).write_text(st.file_text, encoding='ascii', newline='')
        except (OSError, UnicodeError) as exc:
            messagebox.showerror('Save failed', str(exc)); return
        self._event(Event(rx,'FILE SAVED',f'Verified text saved to {Path(target).name}', 'good'))
        messagebox.showinfo('File saved', f'Saved {st.file_characters} characters to:\n{target}')

    def export_history(self):
        if not self.recorded_events:
            messagebox.showinfo('Empty history', 'No events to export.'); return
        path = filedialog.asksaveasfilename(title='Export receiver event history',
                         defaultextension='.csv', initialfile='receiver_event_history.csv',
                         filetypes=[('CSV files','*.csv')])
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8-sig', newline='') as fh:
                writer = csv.writer(fh)
                writer.writerow(['Time','Receiver','Event','Details','Status'])
                writer.writerows((e.timestamp,e.receiver,e.kind,e.summary,e.status) for e in self.recorded_events)
        except OSError as exc:
            messagebox.showerror('Export failed', str(exc)); return
        messagebox.showinfo('History saved', f'Exported {len(self.recorded_events)} events.')

    def _close(self):
        for w in self.readers.values():
            w.stop()
        self.destroy()


def enable_windows_dpi_awareness():
    """Avoid bitmap-blurred Tk text on Windows with 125%/150% display scaling.

    Mirror the already-working transmitter GUI's system-DPI-aware mode.
    Must be called before the very first Tk() window is created.
    Purely visual: packet parsing, serial I/O and received-file logic unchanged.
    """
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        # This matches the transmitter's successful high-DPI initialization.
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        # SetProcessDpiAwareness may be unavailable on older Windows versions,
        # or disallowed if another library has already set DPI awareness.
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def main():
    enable_windows_dpi_awareness()
    ap = argparse.ArgumentParser()
    ap.add_argument('--demo', action='store_true', help='Launch simulated demo log; hardware not required')
    ap.add_argument('--selftest', action='store_true', help='Run protocol log parser regression tests')
    opts = ap.parse_args()
    if opts.selftest:
        selftest()
        return
    app = ReceiverStudio(demo=opts.demo)
    app.mainloop()


if __name__ == '__main__':
    main()
