#!/usr/bin/env python3
"""
ESPLog CSV Playback & OSC Streamer
Reads CSV files and streams data via OSC/UDP with real-time visualization

Requirements:
    pip3 install PyQt6 python-osc matplotlib

Usage:
    python3 csv_osc_streamer.py
"""

import sys
import csv
from pathlib import Path
from collections import deque

from pythonosc.udp_client import SimpleUDPClient

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSpinBox, QDoubleSpinBox, QFileDialog, 
    QMessageBox, QGroupBox, QCheckBox
)
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QFont

import matplotlib
matplotlib.use('QtAgg')
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.animation import FuncAnimation
import numpy as np


class CSVOSCStreamer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ESPLog CSV → OSC Streamer")
        self.resize(1200, 700)
        
        # Playback data
        self.csv_data = []
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
        
        # Build UI
        self.setup_ui()
        
        # Animation
        self.anim = FuncAnimation(
            self.figure,
            self.animate,
            interval=50,  # 20 FPS
            blit=False,
            cache_frame_data=False
        )
    
    def setup_ui(self):
        """Create the user interface"""
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        
        # Left panel - Controls
        controls = self.create_controls_panel()
        layout.addWidget(controls)
        
        # Right panel - Plot
        plot_panel = self.create_plot_panel()
        layout.addWidget(plot_panel)
    
    def create_controls_panel(self):
        """Create controls panel"""
        panel = QWidget()
        panel.setMaximumWidth(350)
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
        
        # File Selection
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
        
        # OSC Settings
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
        
        # Playback Settings
        playback_group = QGroupBox("Playback Settings")
        playback_layout = QVBoxLayout()
        
        playback_layout.addWidget(QLabel("Playback Rate (Hz):"))
        self.rate_input = QSpinBox()
        self.rate_input.setRange(1, 1000)
        self.rate_input.setValue(10)
        playback_layout.addWidget(self.rate_input)
        
        playback_group.setLayout(playback_layout)
        layout.addWidget(playback_group)
        
        # Mapping Settings
        map_group = QGroupBox("Value Mapping")
        map_layout = QVBoxLayout()
        
        # Input range (auto-detected from CSV)
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
        
        # Output range (user settable)
        map_layout.addWidget(QLabel("Output Range (mapped to):"))
        output_range_layout = QHBoxLayout()
        output_range_layout.addWidget(QLabel("Min:"))
        self.output_min_input = QDoubleSpinBox()
        self.output_min_input.setRange(-10, 10)
        self.output_min_input.setDecimals(3)
        self.output_min_input.setValue(0.0)
        output_range_layout.addWidget(self.output_min_input)
        output_range_layout.addWidget(QLabel("Max:"))
        self.output_max_input = QDoubleSpinBox()
        self.output_max_input.setRange(-10, 10)
        self.output_max_input.setDecimals(3)
        self.output_max_input.setValue(1.0)
        output_range_layout.addWidget(self.output_max_input)
        map_layout.addLayout(output_range_layout)
        
        # Auto-fill button
        self.auto_map_btn = QPushButton("Auto (1:1 mapping)")
        self.auto_map_btn.setEnabled(False)
        self.auto_map_btn.clicked.connect(self.auto_map)
        map_layout.addWidget(self.auto_map_btn)
        
        map_group.setLayout(map_layout)
        layout.addWidget(map_group)
        
        # Playback Control
        control_group = QGroupBox("Control")
        control_layout = QVBoxLayout()
        
        loop_layout = QHBoxLayout()
        loop_layout.addWidget(QLabel("Loop:"))
        from PyQt6.QtWidgets import QCheckBox
        self.loop_check = QCheckBox()
        self.loop_check.setChecked(True)
        loop_layout.addWidget(self.loop_check)
        loop_layout.addStretch()
        playback_layout.addLayout(loop_layout)
        
        playback_group.setLayout(playback_layout)
        layout.addWidget(playback_group)
        
        # Playback Control
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
        
        # Status
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
        return panel
    
    def create_plot_panel(self):
        """Create plot panel"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # Matplotlib figure
        self.figure = Figure(figsize=(8, 6))
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.ax = self.figure.add_subplot(111)
        self.ax.set_xlabel('Sample Number')
        self.ax.set_ylabel('Voltage (V)')
        self.ax.set_title('CSV Playback - Streaming Data')
        self.ax.grid(True, alpha=0.3)
        
        self.line, = self.ax.plot([], [], 'b-', linewidth=2, antialiased=True)
        self.ax.set_xlim(0, 100)
        self.ax.set_ylim(0, 5)
        
        # Add toolbar
        toolbar = NavigationToolbar2QT(self.canvas, panel)
        layout.addWidget(toolbar)
        layout.addWidget(self.canvas)
        
        return panel
    
    def load_csv(self):
        """Load CSV file"""
        filename, _ = QFileDialog.getOpenFileName(
            self, "Open CSV File", "", "CSV Files (*.csv)"
        )
        if not filename:
            return
        
        try:
            self.csv_data = []
            with open(filename, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Expected columns: timestamp, raw, voltage
                    self.csv_data.append({
                        'raw': int(row['raw']),
                        'voltage': float(row['voltage'])
                    })
            
            self.playback_index = 0
            self.play_btn.setEnabled(True)
            self.auto_map_btn.setEnabled(True)
            
            # Calculate input range (min/max voltage in CSV)
            voltages = [sample['voltage'] for sample in self.csv_data]
            self.input_min = min(voltages)
            self.input_max = max(voltages)
            
            self.input_min_label.setText(f"{self.input_min:.3f} V")
            self.input_max_label.setText(f"{self.input_max:.3f} V")
            
            self.file_label.setText(f"Loaded: {Path(filename).name}\n{len(self.csv_data)} samples")
            self.file_label.setStyleSheet("font-size: 10pt; color: green;")
            self.progress_label.setText(f"0 / {len(self.csv_data)} samples")
            
            print(f"Loaded {len(self.csv_data)} samples from CSV")
            print(f"Input range: {self.input_min:.3f}V to {self.input_max:.3f}V")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load CSV:\n{e}")
    
    def auto_map(self):
        """Auto-fill output range to match input range (1:1 mapping)"""
        self.output_min_input.setValue(self.input_min)
        self.output_max_input.setValue(self.input_max)
        print(f"Auto-mapped: output {self.input_min:.3f}V to {self.input_max:.3f}V")
    
    def map_value(self, value):
        """Map value from input range to output range"""
        # Linear mapping: y = (x - in_min) / (in_max - in_min) * (out_max - out_min) + out_min
        input_range = self.input_max - self.input_min
        output_range = self.output_max_input.value() - self.output_min_input.value()
        
        if input_range == 0:
            return self.output_min_input.value()
        
        normalized = (value - self.input_min) / input_range
        mapped = normalized * output_range + self.output_min_input.value()
        return mapped
    
    def toggle_playback(self):
        """Toggle playback on/off"""
        if not self.playback_active:
            self.start_playback()
        else:
            self.stop_playback()
    
    def start_playback(self):
        """Start streaming CSV data"""
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
        
        # Clear plot data
        self.time_data.clear()
        self.voltage_data.clear()
        
        # Set up timer
        interval_ms = int(1000 / self.rate_input.value())
        self.playback_timer = QTimer()
        self.playback_timer.timeout.connect(self.send_sample)
        self.playback_timer.start(interval_ms)
        
        print(f"Started playback at {self.rate_input.value()} Hz to {host}:{port}")
    
    def stop_playback(self):
        """Stop streaming"""
        if self.playback_timer:
            self.playback_timer.stop()
            self.playback_timer = None
        
        self.playback_active = False
        self.osc_client = None
        self.play_btn.setText("Start Playback")
        self.status_label.setText("Stopped")
        self.status_label.setStyleSheet("font-weight: bold; color: red;")
        
        print("Stopped playback")
    
    def send_sample(self):
        """Send one sample via OSC"""
        if self.playback_index >= len(self.csv_data):
            if self.loop_check.isChecked():
                # Loop back to start
                self.playback_index = 0
                print("Looping playback...")
            else:
                # Stop at end
                self.stop_playback()
                QMessageBox.information(self, "Playback Complete", "Reached end of CSV file")
                return
        
        sample = self.csv_data[self.playback_index]
        
        # Apply mapping to voltage
        mapped_voltage = self.map_value(sample['voltage'])
        
        # Send OSC messages
        try:
            self.osc_client.send_message("/adc/ch0/raw", [sample['raw'], self.playback_index])
            self.osc_client.send_message("/adc/ch0/voltage", [mapped_voltage, self.playback_index])
        except Exception as e:
            print(f"OSC send error: {e}")
            self.stop_playback()
            return
        
        # Add to plot (mapped)
        self.time_data.append(self.playback_index)
        self.voltage_data.append(mapped_voltage)
        
        self.playback_index += 1
        
        # Update progress
        if self.playback_index % 10 == 0:
            progress = (self.playback_index / len(self.csv_data)) * 100
            self.progress_label.setText(f"{self.playback_index} / {len(self.csv_data)} samples ({progress:.1f}%)")
    
    def clear_plot(self):
        """Clear plot data"""
        self.time_data.clear()
        self.voltage_data.clear()
        print("Plot cleared")
    
    def animate(self, frame):
        """Animation update"""
        if len(self.time_data) > 1:
            time_array = np.array(list(self.time_data)[-1000:])
            voltage_array = np.array(list(self.voltage_data)[-1000:])
            
            self.line.set_data(time_array, voltage_array)
            
            # Update X limits
            if len(time_array) > 1:
                self.ax.set_xlim(time_array[0], time_array[-1])
            
            # Auto Y scale
            if len(voltage_array) > 0:
                y_min = max(0, min(voltage_array) - 0.2)
                y_max = max(voltage_array) + 0.2
                self.ax.set_ylim(y_min, y_max)
        
        return self.line,
    
    def closeEvent(self, event):
        """Handle window close"""
        if self.playback_active:
            self.stop_playback()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    window = CSVOSCStreamer()
    window.show()
    
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
