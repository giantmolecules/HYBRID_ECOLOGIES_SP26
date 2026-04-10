#!/usr/bin/env python3
"""
ESPLog CSV Playback & OSC Streamer
Reads CSV files and streams data via OSC/UDP with real-time visualization
Optionally streams voltage as MIDI CC and/or Note messages

Requirements:
    pip3 install PyQt6 python-osc matplotlib mido python-rtmidi

Usage:
    python3 csv_osc_streamer.py

MIDI Notes:
    - On macOS, a virtual MIDI port named 'ESPLog MIDI' will appear automatically.
      In Ableton Live, enable it under Preferences > Link/Tempo/MIDI > MIDI Ports.
    - On Windows, install loopMIDI and create a virtual port first.
"""

import sys
import csv
from pathlib import Path
from collections import deque

from pythonosc.udp_client import SimpleUDPClient

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSpinBox, QDoubleSpinBox, QFileDialog,
    QMessageBox, QGroupBox, QCheckBox, QComboBox, QScrollArea
)
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QFont

import matplotlib
matplotlib.use('QtAgg')
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.animation import FuncAnimation
import numpy as np

try:
    import mido
    MIDO_AVAILABLE = True
except ImportError:
    MIDO_AVAILABLE = False


# MIDI note number → name helper
NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

def note_name(n):
    return f"{NOTE_NAMES[n % 12]}{(n // 12) - 1}"


NONE_OPTION = "(none)"


class CSVOSCStreamer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ESPLog CSV → OSC Streamer")
        self.resize(1200, 700)

        # Playback data
        self.csv_data = []
        self.csv_headers = []
        self.playback_index = 0
        self.playback_active = False
        self.playback_timer = None
        self.osc_client = None

        # Input range (from CSV)
        self.input_min = 0.0
        self.input_max = 1.0

        # Plot data
        self.time_data = deque(maxlen=1000)
        self.voltage_data = deque(maxlen=1000)

        # MIDI state
        self.midi_port = None
        self.midi_note_active = None
        self.midi_thresh_note_on = False

        # Build UI
        self.setup_ui()

        # Animation
        self.anim = FuncAnimation(
            self.figure,
            self.animate,
            interval=50,
            blit=False,
            cache_frame_data=False
        )

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.addWidget(self.create_controls_panel())
        layout.addWidget(self.create_plot_panel())

    def create_controls_panel(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMaximumWidth(350)

        panel = QWidget()
        layout = QVBoxLayout(panel)

        # Header
        title = QLabel("CSV → OSC Streamer")
        title.setFont(QFont("Georgia", 20, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("Hybrid Ecologies - Spring 2026")
        subtitle.setFont(QFont("Georgia", 12))
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        separator = QLabel()
        separator.setFixedHeight(1)
        separator.setStyleSheet("background-color: #CCC; margin: 10px;")
        layout.addWidget(separator)

        # ── File Selection ────────────────────────────────────────
        file_group = QGroupBox("CSV File")
        file_layout = QVBoxLayout()

        self.load_btn = QPushButton("Load CSV File")
        self.load_btn.setStyleSheet("background-color: #34C759; color: white; font-weight: bold; padding: 10px;")
        self.load_btn.clicked.connect(self.load_csv)
        file_layout.addWidget(self.load_btn)

        self.file_label = QLabel("No file loaded")
        self.file_label.setStyleSheet("font-size: 10pt; color: gray;")
        self.file_label.setWordWrap(True)
        file_layout.addWidget(self.file_label)

        file_group.setLayout(file_layout)
        layout.addWidget(file_group)

        # ── Column Mapping ────────────────────────────────────────
        map_col_group = QGroupBox("Column Mapping")
        map_col_layout = QVBoxLayout()

        map_col_layout.addWidget(QLabel("Raw column:"))
        self.raw_col_combo = QComboBox()
        self.raw_col_combo.addItem(NONE_OPTION)
        self.raw_col_combo.setEnabled(False)
        self.raw_col_combo.currentIndexChanged.connect(self.on_mapping_changed)
        map_col_layout.addWidget(self.raw_col_combo)

        map_col_layout.addWidget(QLabel("Voltage column:"))
        self.voltage_col_combo = QComboBox()
        self.voltage_col_combo.addItem(NONE_OPTION)
        self.voltage_col_combo.setEnabled(False)
        self.voltage_col_combo.currentIndexChanged.connect(self.on_mapping_changed)
        map_col_layout.addWidget(self.voltage_col_combo)

        self.mapping_note = QLabel("")
        self.mapping_note.setStyleSheet("color: gray; font-size: 9pt;")
        self.mapping_note.setWordWrap(True)
        map_col_layout.addWidget(self.mapping_note)

        map_col_group.setLayout(map_col_layout)
        layout.addWidget(map_col_group)

        # ── OSC Output ────────────────────────────────────────────
        osc_group = QGroupBox("OSC Output")
        osc_layout = QVBoxLayout()

        osc_layout.addWidget(QLabel("Destination IP:"))
        self.host_input = QLineEdit()
        self.host_input.setText("127.0.0.1")
        osc_layout.addWidget(self.host_input)

        osc_layout.addWidget(QLabel("Port:"))
        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(8001)
        osc_layout.addWidget(self.port_input)

        osc_group.setLayout(osc_layout)
        layout.addWidget(osc_group)

        # ── Playback Settings ─────────────────────────────────────
        playback_group = QGroupBox("Playback Settings")
        playback_layout = QVBoxLayout()

        playback_layout.addWidget(QLabel("Playback Rate (Hz):"))
        self.rate_input = QSpinBox()
        self.rate_input.setRange(1, 1000)
        self.rate_input.setValue(10)
        playback_layout.addWidget(self.rate_input)

        loop_layout = QHBoxLayout()
        loop_layout.addWidget(QLabel("Loop:"))
        self.loop_check = QCheckBox()
        self.loop_check.setChecked(True)
        loop_layout.addWidget(self.loop_check)
        loop_layout.addStretch()
        playback_layout.addLayout(loop_layout)

        playback_group.setLayout(playback_layout)
        layout.addWidget(playback_group)

        # ── Value Mapping ─────────────────────────────────────────
        map_group = QGroupBox("Value Mapping")
        map_layout = QVBoxLayout()

        map_layout.addWidget(QLabel("Input Range (from CSV):"))
        input_range_layout = QHBoxLayout()
        input_range_layout.addWidget(QLabel("Min:"))
        self.input_min_label = QLabel("--")
        self.input_min_label.setStyleSheet("font-weight: bold;")
        input_range_layout.addWidget(self.input_min_label)
        input_range_layout.addWidget(QLabel("Max:"))
        self.input_max_label = QLabel("--")
        self.input_max_label.setStyleSheet("font-weight: bold;")
        input_range_layout.addWidget(self.input_max_label)
        input_range_layout.addStretch()
        map_layout.addLayout(input_range_layout)

        map_layout.addWidget(QLabel("Output Range (mapped to):"))
        output_range_layout = QHBoxLayout()
        output_range_layout.addWidget(QLabel("Min:"))
        self.output_min_input = QDoubleSpinBox()
        self.output_min_input.setRange(-100000, 100000)
        self.output_min_input.setDecimals(3)
        self.output_min_input.setValue(0.0)
        output_range_layout.addWidget(self.output_min_input)
        output_range_layout.addWidget(QLabel("Max:"))
        self.output_max_input = QDoubleSpinBox()
        self.output_max_input.setRange(-100000, 100000)
        self.output_max_input.setDecimals(3)
        self.output_max_input.setValue(1.0)
        output_range_layout.addWidget(self.output_max_input)
        map_layout.addLayout(output_range_layout)

        self.auto_map_btn = QPushButton("Auto (1:1 mapping)")
        self.auto_map_btn.setEnabled(False)
        self.auto_map_btn.clicked.connect(self.auto_map)
        map_layout.addWidget(self.auto_map_btn)

        map_group.setLayout(map_layout)
        layout.addWidget(map_group)

        # ── MIDI Output ───────────────────────────────────────────
        layout.addWidget(self._create_midi_group())

        # ── Control ───────────────────────────────────────────────
        control_group = QGroupBox("Control")
        control_layout = QVBoxLayout()

        self.play_btn = QPushButton("Start Playback")
        self.play_btn.setStyleSheet("background-color: #007AFF; color: white; font-weight: bold; padding: 10px;")
        self.play_btn.setEnabled(False)
        self.play_btn.clicked.connect(self.toggle_playback)
        control_layout.addWidget(self.play_btn)

        self.clear_btn = QPushButton("Clear Plot")
        self.clear_btn.setStyleSheet("background-color: #FF9500; color: white; font-weight: bold; padding: 8px;")
        self.clear_btn.clicked.connect(self.clear_plot)
        control_layout.addWidget(self.clear_btn)

        control_group.setLayout(control_layout)
        layout.addWidget(control_group)

        # ── Status ────────────────────────────────────────────────
        status_group = QGroupBox("Status")
        status_layout = QVBoxLayout()

        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("font-weight: bold; color: gray;")
        status_layout.addWidget(self.status_label)

        self.progress_label = QLabel("0 / 0 samples")
        status_layout.addWidget(self.progress_label)

        status_group.setLayout(status_layout)
        layout.addWidget(status_group)

        layout.addStretch()
        scroll.setWidget(panel)
        return scroll

    def create_plot_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)

        self.figure = Figure(figsize=(8, 6))
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.ax = self.figure.add_subplot(111)
        self.ax.set_xlabel('Sample Number')
        self.ax.set_ylabel('Value')
        self.ax.set_title('CSV Playback - Streaming Data')
        self.ax.grid(True, alpha=0.3)

        self.line, = self.ax.plot([], [], 'b-', linewidth=2, antialiased=True)
        self.ax.set_xlim(0, 100)
        self.ax.set_ylim(0, 5)

        toolbar = NavigationToolbar2QT(self.canvas, panel)
        layout.addWidget(toolbar)
        layout.addWidget(self.canvas)

        return panel

    # ── CSV loading ───────────────────────────────────────────────

    def load_csv(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Open CSV File", "", "CSV Files (*.csv)"
        )
        if not filename:
            return

        try:
            rows = []
            with open(filename, 'r') as f:
                reader = csv.DictReader(f)
                self.csv_headers = list(reader.fieldnames or [])
                for row in reader:
                    rows.append(dict(row))

            if not rows:
                QMessageBox.warning(self, "Empty File", "CSV file contains no data rows.")
                return

            self.csv_raw_rows = rows
            self.playback_index = 0

            # Populate column mapping dropdowns
            for combo in (self.raw_col_combo, self.voltage_col_combo):
                combo.blockSignals(True)
                combo.clear()
                combo.addItem(NONE_OPTION)
                for h in self.csv_headers:
                    combo.addItem(h)
                combo.setEnabled(True)
                combo.blockSignals(False)

            # Auto-select sensible defaults
            self._auto_select_columns()

            self.file_label.setText(f"Loaded: {Path(filename).name}\n{len(rows)} samples")
            self.file_label.setStyleSheet("font-size: 10pt; color: green;")
            self.progress_label.setText(f"0 / {len(rows)} samples")

            print(f"Loaded {len(rows)} samples, headers: {self.csv_headers}")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load CSV:\n{e}")

    def _auto_select_columns(self):
        """Try to pick sensible defaults based on header names."""
        headers_lower = [h.lower() for h in self.csv_headers]

        # Voltage column
        for candidate in ('voltage', 'volt', 'v'):
            if candidate in headers_lower:
                self.voltage_col_combo.setCurrentIndex(headers_lower.index(candidate) + 1)
                break

        # Raw column
        for candidate in ('raw', 'adc', 'value', 'val'):
            if candidate in headers_lower:
                self.raw_col_combo.setCurrentIndex(headers_lower.index(candidate) + 1)
                break

        self.on_mapping_changed()

    def on_mapping_changed(self):
        """Rebuild csv_data and update UI whenever column selection changes."""
        if not hasattr(self, 'csv_raw_rows') or not self.csv_raw_rows:
            return

        raw_col = self.raw_col_combo.currentText()
        volt_col = self.voltage_col_combo.currentText()

        raw_selected = raw_col != NONE_OPTION
        volt_selected = volt_col != NONE_OPTION

        if not raw_selected and not volt_selected:
            self.mapping_note.setText("Select at least one column.")
            self.play_btn.setEnabled(False)
            self.auto_map_btn.setEnabled(False)
            return

        self.csv_data = []
        parse_errors = 0

        for row in self.csv_raw_rows:
            try:
                raw_val = int(float(row[raw_col])) if raw_selected else 0
                volt_val = float(row[volt_col]) if volt_selected else None
            except (ValueError, KeyError):
                parse_errors += 1
                continue

            self.csv_data.append({'raw': raw_val, 'voltage': volt_val})

        if not self.csv_data:
            self.mapping_note.setText("No valid rows parsed — check column selection.")
            self.play_btn.setEnabled(False)
            return

        # Determine input range from whichever column has real values
        if volt_selected:
            values = [s['voltage'] for s in self.csv_data if s['voltage'] is not None]
        else:
            values = [s['raw'] for s in self.csv_data]

        self.input_min = min(values)
        self.input_max = max(values)

        # If no voltage column, synthesise voltage from raw (scaled 0–3.3V)
        if not volt_selected:
            raw_range = self.input_max - self.input_min
            for s in self.csv_data:
                if raw_range > 0:
                    s['voltage'] = (s['raw'] - self.input_min) / raw_range * 3.3
                else:
                    s['voltage'] = 0.0
            self.mapping_note.setText(
                "No voltage column selected — voltage computed from raw (scaled 0–3.3V)."
            )
        elif not raw_selected:
            self.mapping_note.setText(
                "No raw column selected — raw will be sent as 0."
            )
        else:
            self.mapping_note.setText("")

        self.input_min_label.setText(f"{self.input_min:.3f}")
        self.input_max_label.setText(f"{self.input_max:.3f}")

        self.play_btn.setEnabled(True)
        self.auto_map_btn.setEnabled(True)
        self.progress_label.setText(f"0 / {len(self.csv_data)} samples")

        if parse_errors:
            print(f"Warning: {parse_errors} rows skipped due to parse errors")

        print(f"Mapped {len(self.csv_data)} rows — raw='{raw_col}', voltage='{volt_col}'")
        print(f"Input range: {self.input_min:.3f} to {self.input_max:.3f}")

    # ── Value mapping ─────────────────────────────────────────────

    def auto_map(self):
        self.output_min_input.setValue(self.input_min)
        self.output_max_input.setValue(self.input_max)
        print(f"Auto-mapped output to {self.input_min:.3f} – {self.input_max:.3f}")

    def map_value(self, value):
        input_range = self.input_max - self.input_min
        output_range = self.output_max_input.value() - self.output_min_input.value()

        if input_range == 0:
            return self.output_min_input.value()

        normalized = (value - self.input_min) / input_range
        return normalized * output_range + self.output_min_input.value()

    # ── Playback ──────────────────────────────────────────────────

    def toggle_playback(self):
        if not self.playback_active:
            self.start_playback()
        else:
            self.stop_playback()

    def start_playback(self):
        if not self.csv_data:
            return

        host = self.host_input.text().strip()
        port = self.port_input.value()

        try:
            self.osc_client = SimpleUDPClient(host, port)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to create OSC client:\n{e}")
            return

        self.playback_active = True
        self.playback_index = 0
        self.play_btn.setText("Stop Playback")
        self.status_label.setText(f"Streaming to {host}:{port}")
        self.status_label.setStyleSheet("font-weight: bold; color: green;")

        self.time_data.clear()
        self.voltage_data.clear()

        interval_ms = int(1000 / self.rate_input.value())
        self.playback_timer = QTimer()
        self.playback_timer.timeout.connect(self.send_sample)
        self.playback_timer.start(interval_ms)

        print(f"Started playback at {self.rate_input.value()} Hz to {host}:{port}")

    def stop_playback(self):
        if self.playback_timer:
            self.playback_timer.stop()
            self.playback_timer = None

        self.playback_active = False
        self.osc_client = None
        self._midi_all_notes_off()
        self.play_btn.setText("Start Playback")
        self.status_label.setText("Stopped")
        self.status_label.setStyleSheet("font-weight: bold; color: red;")

        print("Stopped playback")

    def send_sample(self):
        if self.playback_index >= len(self.csv_data):
            if self.loop_check.isChecked():
                self.playback_index = 0
                print("Looping playback...")
            else:
                self.stop_playback()
                QMessageBox.information(self, "Playback Complete", "Reached end of CSV file.")
                return

        sample = self.csv_data[self.playback_index]
        mapped_voltage = self.map_value(sample['voltage'])

        try:
            self.osc_client.send_message("/adc/ch0/raw",     [sample['raw'],   self.playback_index])
            self.osc_client.send_message("/adc/ch0/voltage", [mapped_voltage,  self.playback_index])
        except Exception as e:
            print(f"OSC send error: {e}")
            self.stop_playback()
            return

        self.time_data.append(self.playback_index)
        self.voltage_data.append(mapped_voltage)

        # MIDI
        if MIDO_AVAILABLE and self.midi_enable.isChecked():
            self._process_midi(mapped_voltage)

        self.playback_index += 1

        if self.playback_index % 10 == 0:
            progress = (self.playback_index / len(self.csv_data)) * 100
            self.progress_label.setText(
                f"{self.playback_index} / {len(self.csv_data)} samples ({progress:.1f}%)"
            )

    # ── Plot ──────────────────────────────────────────────────────

    def clear_plot(self):
        self.time_data.clear()
        self.voltage_data.clear()
        print("Plot cleared")

    def animate(self, frame):
        if len(self.time_data) > 1:
            time_array    = np.array(list(self.time_data)[-1000:])
            voltage_array = np.array(list(self.voltage_data)[-1000:])

            self.line.set_data(time_array, voltage_array)

            if len(time_array) > 1:
                self.ax.set_xlim(time_array[0], time_array[-1])

            if len(voltage_array) > 0:
                y_min = min(voltage_array) - 0.05 * abs(min(voltage_array) or 1)
                y_max = max(voltage_array) + 0.05 * abs(max(voltage_array) or 1)
                if y_min == y_max:
                    y_min -= 0.1
                    y_max += 0.1
                self.ax.set_ylim(y_min, y_max)

        return self.line,

    def closeEvent(self, event):
        if self.playback_active:
            self.stop_playback()
        self._midi_all_notes_off()
        if self.midi_port:
            self.midi_port.close()
        event.accept()


    # ── MIDI UI ───────────────────────────────────────────────────

    def _create_midi_group(self):
        """Build the MIDI Output controls group"""
        midi_group = QGroupBox("MIDI Output")
        midi_layout = QVBoxLayout()

        if not MIDO_AVAILABLE:
            warn = QLabel("mido / python-rtmidi not installed.\npip3 install mido python-rtmidi")
            warn.setStyleSheet("color: red; font-size: 9pt;")
            midi_layout.addWidget(warn)
            midi_group.setLayout(midi_layout)
            return midi_group

        self.midi_enable = QCheckBox("Enable MIDI")
        midi_layout.addWidget(self.midi_enable)

        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("Port name:"))
        self.midi_port_name = QLineEdit("ESPLog MIDI")
        port_row.addWidget(self.midi_port_name)
        midi_layout.addLayout(port_row)

        ch_row = QHBoxLayout()
        ch_row.addWidget(QLabel("Channel:"))
        self.midi_channel = QSpinBox()
        self.midi_channel.setRange(1, 16)
        self.midi_channel.setValue(1)
        ch_row.addWidget(self.midi_channel)
        ch_row.addStretch()
        midi_layout.addLayout(ch_row)

        self.midi_status_label = QLabel("MIDI: Inactive")
        self.midi_status_label.setStyleSheet("color: gray; font-weight: bold;")
        midi_layout.addWidget(self.midi_status_label)

        self.midi_enable.toggled.connect(self.toggle_midi_port)

        # ── CC sub-section ────────────────────────────────────────
        cc_group = QGroupBox("CC Output")
        cc_group.setCheckable(True)
        cc_group.setChecked(False)
        cc_layout = QVBoxLayout()

        cc_num_row = QHBoxLayout()
        cc_num_row.addWidget(QLabel("CC #:"))
        self.midi_cc_number = QSpinBox()
        self.midi_cc_number.setRange(0, 127)
        self.midi_cc_number.setValue(1)
        cc_num_row.addWidget(self.midi_cc_number)
        cc_num_row.addStretch()
        cc_layout.addLayout(cc_num_row)

        cc_vmin_row = QHBoxLayout()
        cc_vmin_row.addWidget(QLabel("V min:"))
        self.midi_cc_v_min = QDoubleSpinBox()
        self.midi_cc_v_min.setRange(-10, 10)
        self.midi_cc_v_min.setDecimals(3)
        self.midi_cc_v_min.setSingleStep(0.1)
        self.midi_cc_v_min.setValue(0.0)
        cc_vmin_row.addWidget(self.midi_cc_v_min)
        cc_layout.addLayout(cc_vmin_row)

        cc_vmax_row = QHBoxLayout()
        cc_vmax_row.addWidget(QLabel("V max:"))
        self.midi_cc_v_max = QDoubleSpinBox()
        self.midi_cc_v_max.setRange(-10, 10)
        self.midi_cc_v_max.setDecimals(3)
        self.midi_cc_v_max.setSingleStep(0.1)
        self.midi_cc_v_max.setValue(5.0)
        cc_vmax_row.addWidget(self.midi_cc_v_max)
        cc_layout.addLayout(cc_vmax_row)

        self.midi_cc_value_label = QLabel("CC value: —")
        self.midi_cc_value_label.setStyleSheet("font-size: 10pt; color: #555;")
        cc_layout.addWidget(self.midi_cc_value_label)

        cc_group.setLayout(cc_layout)
        midi_layout.addWidget(cc_group)
        self.midi_cc_group = cc_group

        # ── Note sub-section ──────────────────────────────────────
        note_group = QGroupBox("Note Output")
        note_group.setCheckable(True)
        note_group.setChecked(False)
        note_layout = QVBoxLayout()

        note_layout.addWidget(QLabel("Mode:"))
        self.midi_note_mode = QComboBox()
        self.midi_note_mode.addItems(["Threshold", "Pitch Mapping"])
        self.midi_note_mode.currentIndexChanged.connect(self._update_note_mode_ui)
        note_layout.addWidget(self.midi_note_mode)

        vel_row = QHBoxLayout()
        vel_row.addWidget(QLabel("Velocity:"))
        self.midi_velocity = QSpinBox()
        self.midi_velocity.setRange(1, 127)
        self.midi_velocity.setValue(100)
        vel_row.addWidget(self.midi_velocity)
        vel_row.addStretch()
        note_layout.addLayout(vel_row)

        # Threshold mode widgets
        self.thresh_note_widget = QWidget()
        tn_layout = QVBoxLayout(self.thresh_note_widget)
        tn_layout.setContentsMargins(0, 0, 0, 0)

        tn_note_row = QHBoxLayout()
        tn_note_row.addWidget(QLabel("Note:"))
        self.midi_thresh_note = QSpinBox()
        self.midi_thresh_note.setRange(0, 127)
        self.midi_thresh_note.setValue(60)
        self.midi_thresh_note.valueChanged.connect(self._update_thresh_note_label)
        tn_note_row.addWidget(self.midi_thresh_note)
        self.thresh_note_name_label = QLabel("C4")
        self.thresh_note_name_label.setStyleSheet("color: #555;")
        tn_note_row.addWidget(self.thresh_note_name_label)
        tn_note_row.addStretch()
        tn_layout.addLayout(tn_note_row)

        tn_high_row = QHBoxLayout()
        tn_high_row.addWidget(QLabel("High:"))
        self.thresh_high = QDoubleSpinBox()
        self.thresh_high.setRange(-10, 10)
        self.thresh_high.setSingleStep(0.1)
        self.thresh_high.setDecimals(3)
        self.thresh_high.setValue(1.0)
        tn_high_row.addWidget(self.thresh_high)
        tn_layout.addLayout(tn_high_row)

        tn_low_row = QHBoxLayout()
        tn_low_row.addWidget(QLabel("Low:"))
        self.thresh_low = QDoubleSpinBox()
        self.thresh_low.setRange(-10, 10)
        self.thresh_low.setSingleStep(0.1)
        self.thresh_low.setDecimals(3)
        self.thresh_low.setValue(0.1)
        tn_low_row.addWidget(self.thresh_low)
        tn_layout.addLayout(tn_low_row)

        tn_info = QLabel("Note ON when V > High,\nNote OFF when V < Low.")
        tn_info.setStyleSheet("color: gray; font-size: 8pt;")
        tn_layout.addWidget(tn_info)
        note_layout.addWidget(self.thresh_note_widget)

        # Pitch mapping mode widgets
        self.pitch_map_widget = QWidget()
        pm_layout = QVBoxLayout(self.pitch_map_widget)
        pm_layout.setContentsMargins(0, 0, 0, 0)

        pm_vmin_row = QHBoxLayout()
        pm_vmin_row.addWidget(QLabel("V min:"))
        self.midi_note_v_min = QDoubleSpinBox()
        self.midi_note_v_min.setRange(-10, 10)
        self.midi_note_v_min.setDecimals(3)
        self.midi_note_v_min.setSingleStep(0.1)
        self.midi_note_v_min.setValue(0.0)
        pm_vmin_row.addWidget(self.midi_note_v_min)
        pm_layout.addLayout(pm_vmin_row)

        pm_vmax_row = QHBoxLayout()
        pm_vmax_row.addWidget(QLabel("V max:"))
        self.midi_note_v_max = QDoubleSpinBox()
        self.midi_note_v_max.setRange(-10, 10)
        self.midi_note_v_max.setDecimals(3)
        self.midi_note_v_max.setSingleStep(0.1)
        self.midi_note_v_max.setValue(5.0)
        pm_vmax_row.addWidget(self.midi_note_v_max)
        pm_layout.addLayout(pm_vmax_row)

        pm_nlo_row = QHBoxLayout()
        pm_nlo_row.addWidget(QLabel("Note low:"))
        self.midi_note_low = QSpinBox()
        self.midi_note_low.setRange(0, 127)
        self.midi_note_low.setValue(36)
        self.midi_note_low.valueChanged.connect(self._update_pitch_note_labels)
        pm_nlo_row.addWidget(self.midi_note_low)
        self.pitch_note_low_label = QLabel("C2")
        self.pitch_note_low_label.setStyleSheet("color: #555;")
        pm_nlo_row.addWidget(self.pitch_note_low_label)
        pm_nlo_row.addStretch()
        pm_layout.addLayout(pm_nlo_row)

        pm_nhi_row = QHBoxLayout()
        pm_nhi_row.addWidget(QLabel("Note high:"))
        self.midi_note_high = QSpinBox()
        self.midi_note_high.setRange(0, 127)
        self.midi_note_high.setValue(84)
        self.midi_note_high.valueChanged.connect(self._update_pitch_note_labels)
        pm_nhi_row.addWidget(self.midi_note_high)
        self.pitch_note_high_label = QLabel("C6")
        self.pitch_note_high_label.setStyleSheet("color: #555;")
        pm_nhi_row.addWidget(self.pitch_note_high_label)
        pm_nhi_row.addStretch()
        pm_layout.addLayout(pm_nhi_row)

        self.midi_note_active_label = QLabel("Note: —")
        self.midi_note_active_label.setStyleSheet("font-size: 10pt; color: #555;")
        pm_layout.addWidget(self.midi_note_active_label)

        note_layout.addWidget(self.pitch_map_widget)
        note_group.setLayout(note_layout)
        midi_layout.addWidget(note_group)
        self.midi_note_group = note_group

        midi_group.setLayout(midi_layout)
        self._update_note_mode_ui()
        return midi_group

    def _update_thresh_note_label(self):
        self.thresh_note_name_label.setText(note_name(self.midi_thresh_note.value()))

    def _update_pitch_note_labels(self):
        self.pitch_note_low_label.setText(note_name(self.midi_note_low.value()))
        self.pitch_note_high_label.setText(note_name(self.midi_note_high.value()))

    def _update_note_mode_ui(self):
        thresh_mode = self.midi_note_mode.currentIndex() == 0
        self.thresh_note_widget.setVisible(thresh_mode)
        self.pitch_map_widget.setVisible(not thresh_mode)

    def toggle_midi_port(self, enabled):
        if not MIDO_AVAILABLE:
            return
        if enabled:
            port_name = self.midi_port_name.text().strip() or "ESPLog MIDI"
            try:
                self.midi_port = mido.open_output(port_name, virtual=True)
                self.midi_status_label.setText(f"MIDI: Active — {port_name}")
                self.midi_status_label.setStyleSheet("color: green; font-weight: bold;")
                print(f"[MIDI] Virtual port opened: '{port_name}'")
            except Exception as e:
                self.midi_enable.blockSignals(True)
                self.midi_enable.setChecked(False)
                self.midi_enable.blockSignals(False)
                self.midi_status_label.setText("MIDI: Error")
                self.midi_status_label.setStyleSheet("color: red; font-weight: bold;")
                QMessageBox.critical(self, "MIDI Error",
                    f"Could not open virtual MIDI port:\n{e}\n\nOn Windows, install loopMIDI first.")
        else:
            self._midi_all_notes_off()
            if self.midi_port:
                self.midi_port.close()
                self.midi_port = None
            self.midi_status_label.setText("MIDI: Inactive")
            self.midi_status_label.setStyleSheet("color: gray; font-weight: bold;")
            self.midi_cc_value_label.setText("CC value: —")
            self.midi_note_active_label.setText("Note: —")
            print("[MIDI] Port closed")

    def _midi_send(self, msg):
        if self.midi_port:
            try:
                self.midi_port.send(msg)
            except Exception as e:
                print(f"[MIDI] Send error: {e}")

    def _midi_all_notes_off(self):
        if not self.midi_port:
            return
        ch = self.midi_channel.value() - 1
        if self.midi_note_active is not None:
            self._midi_send(mido.Message('note_off', channel=ch, note=self.midi_note_active, velocity=0))
            self.midi_note_active = None
        if self.midi_thresh_note_on:
            note = self.midi_thresh_note.value()
            self._midi_send(mido.Message('note_off', channel=ch, note=note, velocity=0))
            self.midi_thresh_note_on = False

    def _process_midi(self, voltage):
        if not MIDO_AVAILABLE or not self.midi_port:
            return

        ch = self.midi_channel.value() - 1

        # CC
        if self.midi_cc_group.isChecked():
            v_min = self.midi_cc_v_min.value()
            v_max = self.midi_cc_v_max.value()
            if v_max != v_min:
                ratio = (voltage - v_min) / (v_max - v_min)
                cc_val = int(max(0, min(127, ratio * 127)))
            else:
                cc_val = 0
            cc_num = self.midi_cc_number.value()
            self._midi_send(mido.Message('control_change', channel=ch, control=cc_num, value=cc_val))
            self.midi_cc_value_label.setText(f"CC {cc_num}: {cc_val}")

        # Notes
        if self.midi_note_group.isChecked():
            velocity = self.midi_velocity.value()
            mode = self.midi_note_mode.currentIndex()

            if mode == 0:
                # Threshold mode
                high = self.thresh_high.value()
                low = self.thresh_low.value()
                note = self.midi_thresh_note.value()

                if voltage > high and not self.midi_thresh_note_on:
                    self._midi_send(mido.Message('note_on', channel=ch, note=note, velocity=velocity))
                    self.midi_thresh_note_on = True
                    print(f"[MIDI] Note ON {note_name(note)} ({note}) — {voltage:.3f} > {high:.3f}")
                elif voltage < low and self.midi_thresh_note_on:
                    self._midi_send(mido.Message('note_off', channel=ch, note=note, velocity=0))
                    self.midi_thresh_note_on = False
                    print(f"[MIDI] Note OFF {note_name(note)} ({note}) — {voltage:.3f} < {low:.3f}")

            else:
                # Pitch mapping mode
                v_min = self.midi_note_v_min.value()
                v_max = self.midi_note_v_max.value()
                n_low = self.midi_note_low.value()
                n_high = self.midi_note_high.value()

                if v_max != v_min and n_high != n_low:
                    ratio = (voltage - v_min) / (v_max - v_min)
                    new_note = int(max(n_low, min(n_high, n_low + ratio * (n_high - n_low))))
                else:
                    new_note = n_low

                if new_note != self.midi_note_active:
                    if self.midi_note_active is not None:
                        self._midi_send(mido.Message('note_off', channel=ch, note=self.midi_note_active, velocity=0))
                    self._midi_send(mido.Message('note_on', channel=ch, note=new_note, velocity=velocity))
                    self.midi_note_active = new_note
                    self.midi_note_active_label.setText(f"Note: {note_name(new_note)} ({new_note})")
                    print(f"[MIDI] Pitch → {note_name(new_note)} ({new_note}) — {voltage:.3f}")


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    window = CSVOSCStreamer()
    window.show()

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
