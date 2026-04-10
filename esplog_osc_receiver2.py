#!/usr/bin/env python3
"""
ESPLog v2 - OSC/UDP Receiver
Single-channel data logger with filtering and threshold monitoring

Requirements:
    pip3 install PyQt6 python-osc matplotlib

Usage:
    python3 esplog_osc_receiver.py
"""

import sys
import csv
import time
from pathlib import Path
from datetime import datetime
from collections import deque

from pythonosc import dispatcher
from pythonosc import osc_server
from pythonosc.udp_client import SimpleUDPClient
import threading

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QCheckBox, QComboBox, QSpinBox,
    QDoubleSpinBox, QGroupBox, QFileDialog, QMessageBox
)
from PyQt6.QtCore import QTimer, Qt, pyqtSignal, QObject
from PyQt6.QtGui import QFont

import matplotlib
matplotlib.use('QtAgg')
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
import numpy as np


class OSCSignals(QObject):
    """Qt signals for thread-safe OSC callbacks"""
    new_data = pyqtSignal(int, float)  # raw, voltage
    

class ESPLogOSCReceiver(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ESPLog v2 - OSC/UDP Receiver")
        self.resize(1000, 700)
        
        # OSC server
        self.osc_server = None
        self.osc_thread = None
        self.running = False
        
        # Data buffers
        self.time_data = deque(maxlen=1000)
        self.voltage_data = deque(maxlen=1000)
        self.raw_data = deque(maxlen=1000)
        
        # Filter buffer
        self.filter_buffer = deque(maxlen=50)
        
        # CSV logging
        self.csv_file = None
        self.csv_writer = None
        self.csv_handle = None
        self.logging_active = False
        self.csv_row_count = 0
        
        # Statistics
        self.sample_count = 0
        self.start_time = None
        
        # Threshold state
        self.threshold_state = None
        
        # Signals
        self.signals = OSCSignals()
        self.signals.new_data.connect(self.handle_new_data)
        
        # Build UI
        self.setup_ui()
        
        # Update timer
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_display)
        self.update_timer.start(20)  # 50 Hz - smoother updates
    
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
        title = QLabel("Hybrid Ecologies")
        title.setFont(QFont("Georgia", 20, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        subtitle = QLabel("Spring 2026")
        subtitle.setFont(QFont("Georgia", 14))
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)
        
        desc = QLabel("OSC/UDP ESP32 Data Logger")
        desc.setFont(QFont("Georgia", 11))
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(desc)
        
        author = QLabel("Brett Ian Balogh, 2026")
        author.setFont(QFont("Georgia", 9))
        author.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(author)
        
        separator = QLabel()
        separator.setFixedHeight(1)
        separator.setStyleSheet("background-color: #CCC; margin: 10px;")
        layout.addWidget(separator)
        
        # OSC Settings
        osc_group = QGroupBox("OSC Settings")
        osc_layout = QVBoxLayout()
        
        osc_layout.addWidget(QLabel("Listen Port:"))
        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(8000)
        osc_layout.addWidget(self.port_input)
        
        self.start_btn = QPushButton("Start Listening")
        self.start_btn.setStyleSheet("background-color: #007AFF; color: white; font-weight: bold; padding: 10px;")
        self.start_btn.clicked.connect(self.toggle_listening)
        osc_layout.addWidget(self.start_btn)
        
        self.status_label = QLabel("Status: Stopped")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")
        osc_layout.addWidget(self.status_label)
        
        osc_group.setLayout(osc_layout)
        layout.addWidget(osc_group)
        
        # ESP32 Configuration
        esp_group = QGroupBox("ESP32 Sample Rate")
        esp_layout = QVBoxLayout()
        
        esp_layout.addWidget(QLabel("Note: This sets the ESP32 sending rate"))
        
        rate_layout = QHBoxLayout()
        rate_layout.addWidget(QLabel("Sample Rate:"))
        self.esp_rate_input = QSpinBox()
        self.esp_rate_input.setRange(1, 100)
        self.esp_rate_input.setValue(10)
        rate_layout.addWidget(self.esp_rate_input)
        rate_layout.addWidget(QLabel("Hz"))
        esp_layout.addLayout(rate_layout)
        
        self.rate_note = QLabel("(Set this before uploading Arduino code)")
        self.rate_note.setStyleSheet("color: gray; font-size: 9pt;")
        esp_layout.addWidget(self.rate_note)
        
        esp_group.setLayout(esp_layout)
        layout.addWidget(esp_group)
        
        # CSV Logging
        log_group = QGroupBox("CSV Logging")
        log_layout = QVBoxLayout()
        
        self.log_btn = QPushButton("Start Logging")
        self.log_btn.setStyleSheet("background-color: #007AFF; color: white; font-weight: bold; padding: 8px;")
        self.log_btn.setEnabled(False)
        self.log_btn.clicked.connect(self.toggle_logging)
        log_layout.addWidget(self.log_btn)
        
        self.row_counter_label = QLabel("Rows logged: 0")
        self.row_counter_label.setStyleSheet("font-size: 11pt;")
        log_layout.addWidget(self.row_counter_label)
        
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)
        
        # Filter Settings
        filter_group = QGroupBox("Low-Pass Filter")
        filter_layout = QVBoxLayout()
        
        self.filter_enable = QCheckBox("Enable Filter")
        filter_layout.addWidget(self.filter_enable)
        
        filter_layout.addWidget(QLabel("Window (samples):"))
        self.filter_window = QSpinBox()
        self.filter_window.setRange(2, 50)
        self.filter_window.setValue(5)
        filter_layout.addWidget(self.filter_window)
        
        filter_group.setLayout(filter_layout)
        layout.addWidget(filter_group)
        
        # Threshold Settings
        thresh_group = QGroupBox("Threshold Alert")
        thresh_layout = QVBoxLayout()
        
        self.thresh_enable = QCheckBox("Enable Threshold")
        thresh_layout.addWidget(self.thresh_enable)
        
        high_layout = QHBoxLayout()
        high_layout.addWidget(QLabel("High:"))
        self.thresh_high = QDoubleSpinBox()
        self.thresh_high.setRange(0, 10)
        self.thresh_high.setSingleStep(0.1)
        self.thresh_high.setDecimals(2)
        self.thresh_high.setValue(1.0)
        high_layout.addWidget(self.thresh_high)
        high_layout.addWidget(QLabel("V"))
        thresh_layout.addLayout(high_layout)
        
        low_layout = QHBoxLayout()
        low_layout.addWidget(QLabel("Low:"))
        self.thresh_low = QDoubleSpinBox()
        self.thresh_low.setRange(0, 10)
        self.thresh_low.setSingleStep(0.1)
        self.thresh_low.setDecimals(2)
        self.thresh_low.setValue(0.1)
        low_layout.addWidget(self.thresh_low)
        low_layout.addWidget(QLabel("V"))
        thresh_layout.addLayout(low_layout)
        
        self.thresh_indicator = QLabel("●")
        self.thresh_indicator.setStyleSheet("color: gray; font-size: 20pt;")
        self.thresh_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thresh_layout.addWidget(self.thresh_indicator)
        
        thresh_group.setLayout(thresh_layout)
        layout.addWidget(thresh_group)
        
        # Plot Settings
        plot_group = QGroupBox("Plot Settings")
        plot_layout = QVBoxLayout()
        
        self.autoscale_check = QCheckBox("Autoscale Y")
        self.autoscale_check.setChecked(True)
        plot_layout.addWidget(self.autoscale_check)
        
        plot_layout.addWidget(QLabel("Y Min:"))
        self.y_min_input = QDoubleSpinBox()
        self.y_min_input.setRange(-10, 10)
        self.y_min_input.setValue(0.0)
        plot_layout.addWidget(self.y_min_input)
        
        plot_layout.addWidget(QLabel("Y Max:"))
        self.y_max_input = QDoubleSpinBox()
        self.y_max_input.setRange(-10, 10)
        self.y_max_input.setValue(5.0)
        plot_layout.addWidget(self.y_max_input)
        
        plot_layout.addWidget(QLabel("Window (samples):"))
        self.window_input = QSpinBox()
        self.window_input.setRange(10, 1000)
        self.window_input.setValue(100)
        plot_layout.addWidget(self.window_input)
        
        plot_group.setLayout(plot_layout)
        layout.addWidget(plot_group)
        
        # Statistics
        stats_group = QGroupBox("Statistics")
        stats_layout = QVBoxLayout()
        
        self.samples_label = QLabel("Samples: 0")
        stats_layout.addWidget(self.samples_label)
        
        self.rate_label = QLabel("Rate: 0.0 Hz")
        stats_layout.addWidget(self.rate_label)
        
        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)
        
        layout.addStretch()
        return panel
    
    def create_plot_panel(self):
        """Create plot panel"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # Current reading
        reading_layout = QHBoxLayout()
        reading_layout.addWidget(QLabel("Current:"))
        self.current_reading = QLabel("0.000 V")
        self.current_reading.setFont(QFont("Monaco", 16, QFont.Weight.Bold))
        reading_layout.addWidget(self.current_reading)
        
        # Progress bar for voltage
        from PyQt6.QtWidgets import QProgressBar
        self.voltage_bar = QProgressBar()
        self.voltage_bar.setRange(0, 5000)  # 0-5V in millivolts
        self.voltage_bar.setValue(0)
        self.voltage_bar.setTextVisible(False)
        self.voltage_bar.setMaximumHeight(20)
        self.voltage_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid grey;
                border-radius: 5px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #007AFF;
                width: 1px;
            }
        """)
        reading_layout.addWidget(self.voltage_bar)
        
        # Threshold indicator
        self.reading_indicator = QLabel("●")
        self.reading_indicator.setStyleSheet("color: gray; font-size: 16pt;")
        reading_layout.addWidget(self.reading_indicator)
        
        reading_layout.addStretch()
        layout.addLayout(reading_layout)
        
        # Plot
        self.figure = Figure(figsize=(8, 6))
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.ax = self.figure.add_subplot(111)
        self.ax.set_xlabel('Time (s)')
        self.ax.set_ylabel('Voltage (V)')
        self.ax.set_title('Channel 0 - Real-Time Data')
        self.ax.grid(True, alpha=0.3)
        
        self.line, = self.ax.plot([], [], 'b-', linewidth=2, antialiased=True)
        
        # Threshold lines (dotted)
        self.thresh_high_line = self.ax.axhline(y=1.0, color='red', linestyle='--', linewidth=1.5, alpha=0.7, visible=False)
        self.thresh_low_line = self.ax.axhline(y=0.1, color='orange', linestyle='--', linewidth=1.5, alpha=0.7, visible=False)
        
        self.ax.set_xlim(0, 100)
        self.ax.set_ylim(0, 5)
        
        # Add matplotlib navigation toolbar
        from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT
        toolbar = NavigationToolbar2QT(self.canvas, panel)
        layout.addWidget(toolbar)
        layout.addWidget(self.canvas)
        
        return panel
    
    def toggle_listening(self):
        """Start/stop OSC listening"""
        if not self.running:
            self.start_listening()
        else:
            self.stop_listening()
    
    def start_listening(self):
        """Start OSC server"""
        port = self.port_input.value()
        
        # Create dispatcher
        disp = dispatcher.Dispatcher()
        disp.map("/adc/ch0/raw", self.osc_raw_handler)
        disp.map("/adc/ch0/voltage", self.osc_voltage_handler)
        
        # Create and start server
        try:
            self.osc_server = osc_server.ThreadingOSCUDPServer(("0.0.0.0", port), disp)
            self.osc_thread = threading.Thread(target=self.osc_server.serve_forever, daemon=True)
            self.osc_thread.start()
            
            self.running = True
            self.start_time = time.time()
            self.sample_count = 0
            
            self.start_btn.setText("Stop Listening")
            self.log_btn.setEnabled(True)
            self.status_label.setText(f"Status: Listening on port {port}")
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
            
            print(f"OSC server started on port {port}")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to start OSC server:\n{e}")
    
    def stop_listening(self):
        """Stop OSC server"""
        if self.osc_server:
            self.osc_server.shutdown()
            self.osc_server = None
        
        self.running = False
        self.start_btn.setText("Start Listening")
        self.log_btn.setEnabled(False)
        self.status_label.setText("Status: Stopped")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")
        
        if self.logging_active:
            self.stop_logging()
        
        print("OSC server stopped")
    
    def osc_raw_handler(self, address, *args):
        """OSC handler for raw value"""
        if args:
            self.current_raw = args[0]
    
    def osc_voltage_handler(self, address, *args):
        """OSC handler for voltage value"""
        if args:
            voltage = args[0]
            raw = getattr(self, 'current_raw', 0)
            self.signals.new_data.emit(raw, voltage)
    
    def handle_new_data(self, raw, voltage):
        """Handle new data (runs in main thread)"""
        # Apply filter
        self.filter_buffer.append(voltage)
        
        if self.filter_enable.isChecked() and len(self.filter_buffer) > 0:
            window = min(self.filter_window.value(), len(self.filter_buffer))
            recent = list(self.filter_buffer)[-window:]
            filtered_voltage = sum(recent) / len(recent)
        else:
            filtered_voltage = voltage
        
        # Update display
        self.current_reading.setText(f"{filtered_voltage:.3f} V")
        self.voltage_bar.setValue(int(min(filtered_voltage, 5.0) * 1000))
        
        # Add to plot buffer
        if self.start_time:
            elapsed = time.time() - self.start_time
            self.time_data.append(elapsed)
            self.voltage_data.append(filtered_voltage)
            self.raw_data.append(raw)
        
        # Check thresholds
        if self.thresh_enable.isChecked():
            self.check_threshold(filtered_voltage)
        else:
            self.thresh_indicator.setStyleSheet("color: gray; font-size: 20pt;")
            self.reading_indicator.setStyleSheet("color: gray; font-size: 16pt;")
        
        # Log to CSV
        if self.logging_active and self.csv_writer:
            timestamp = datetime.now().isoformat()
            self.csv_writer.writerow([timestamp, raw, filtered_voltage])
            self.csv_row_count += 1
            
            if self.csv_row_count % 10 == 0:
                self.row_counter_label.setText(f"Rows logged: {self.csv_row_count}")
                self.csv_handle.flush()
        
        self.sample_count += 1
    
    def check_threshold(self, voltage):
        """Check voltage threshold"""
        high = self.thresh_high.value()
        low = self.thresh_low.value()
        
        if voltage > high:
            new_state = 'high'
        elif voltage < low:
            new_state = 'low'
        else:
            new_state = 'normal'
        
        # Update indicator
        if new_state == 'high':
            self.thresh_indicator.setStyleSheet("color: red; font-size: 20pt;")
            self.reading_indicator.setStyleSheet("color: red; font-size: 16pt;")
        elif new_state == 'low':
            self.thresh_indicator.setStyleSheet("color: orange; font-size: 20pt;")
            self.reading_indicator.setStyleSheet("color: orange; font-size: 16pt;")
        else:
            self.thresh_indicator.setStyleSheet("color: green; font-size: 20pt;")
            self.reading_indicator.setStyleSheet("color: green; font-size: 16pt;")
        
        # Print alerts on state change
        if new_state != self.threshold_state:
            if new_state == 'high':
                print(f"[ALERT] HIGH: {voltage:.3f}V > {high:.3f}V")
            elif new_state == 'low':
                print(f"[ALERT] LOW: {voltage:.3f}V < {low:.3f}V")
            elif self.threshold_state is not None:
                print(f"[ALERT] NORMAL: {voltage:.3f}V")
            
            self.threshold_state = new_state
    
    def toggle_logging(self):
        """Toggle CSV logging"""
        if not self.logging_active:
            self.start_logging()
        else:
            self.stop_logging()
    
    def start_logging(self):
        """Start CSV logging"""
        filename, _ = QFileDialog.getSaveFileName(
            self, "Save CSV Log", "", "CSV Files (*.csv)"
        )
        if not filename:
            return
        
        self.csv_file = Path(filename)
        self.csv_handle = open(self.csv_file, 'w', newline='')
        self.csv_writer = csv.writer(self.csv_handle)
        
        # Write header
        self.csv_writer.writerow(['timestamp', 'raw', 'voltage'])
        
        self.logging_active = True
        self.csv_row_count = 0
        self.log_btn.setText("Stop Logging")
        self.row_counter_label.setText("Rows logged: 0")
    
    def stop_logging(self):
        """Stop CSV logging"""
        if self.csv_handle:
            self.csv_handle.close()
            self.csv_handle = None
            self.csv_writer = None
        
        self.logging_active = False
        self.log_btn.setText("Start Logging")
    
    def update_display(self):
        """Update plot and statistics"""
        # Update statistics
        if self.start_time and self.running:
            elapsed = time.time() - self.start_time
            rate = self.sample_count / elapsed if elapsed > 0 else 0
            self.samples_label.setText(f"Samples: {self.sample_count}")
            self.rate_label.setText(f"Rate: {rate:.1f} Hz")
        
        # Update threshold lines
        if self.thresh_enable.isChecked():
            self.thresh_high_line.set_ydata([self.thresh_high.value(), self.thresh_high.value()])
            self.thresh_low_line.set_ydata([self.thresh_low.value(), self.thresh_low.value()])
            self.thresh_high_line.set_visible(True)
            self.thresh_low_line.set_visible(True)
        else:
            self.thresh_high_line.set_visible(False)
            self.thresh_low_line.set_visible(False)
        
        # Update plot
        if len(self.time_data) > 10:
            window = min(self.window_input.value(), len(self.time_data))
            time_array = np.array(list(self.time_data)[-window:])
            voltage_array = np.array(list(self.voltage_data)[-window:])
            
            self.line.set_data(time_array, voltage_array)
            
            if len(time_array) > 1:
                self.ax.set_xlim(time_array[0], time_array[-1])
            
            # Y-axis scaling
            if self.autoscale_check.isChecked():
                if len(voltage_array) > 0:
                    y_min = max(0, min(voltage_array) - 0.2)
                    y_max = max(voltage_array) + 0.2
                    self.ax.set_ylim(y_min, y_max)
            else:
                self.ax.set_ylim(self.y_min_input.value(), self.y_max_input.value())
            
            try:
                self.canvas.draw()
            except:
                pass
    
    def closeEvent(self, event):
        """Handle window close"""
        if self.running:
            self.stop_listening()
        if self.logging_active:
            self.stop_logging()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    window = ESPLogOSCReceiver()
    window.show()
    
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
