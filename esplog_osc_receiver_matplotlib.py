#!/usr/bin/env python3
"""
ESPLog v2 - OSC/UDP Receiver (Fast Matplotlib with Blitting)
Uses FuncAnimation with blitting for smooth, efficient plotting

Requirements:
    pip3 install PyQt6 python-osc matplotlib scipy

Usage:
    python3 esplog_osc_receiver_matplotlib.py
"""

import sys
import csv
import time
from pathlib import Path
from datetime import datetime
from collections import deque
import socket

from pythonosc import dispatcher
from pythonosc import osc_server
from pythonosc.udp_client import SimpleUDPClient
import threading

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QCheckBox, QComboBox, QSpinBox,
    QDoubleSpinBox, QGroupBox, QFileDialog, QMessageBox, QScrollArea,
    QProgressBar
)
from PyQt6.QtCore import QTimer, Qt, pyqtSignal, QObject
from PyQt6.QtGui import QFont

import matplotlib
matplotlib.use('QtAgg')
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.animation import FuncAnimation
import numpy as np
from scipy import interpolate


class OSCSignals(QObject):
    """Qt signals for thread-safe OSC callbacks"""
    new_data = pyqtSignal(int, float)  # raw, voltage
    

class ESPLogOSCReceiver(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ESPLog v2 - OSC/UDP Receiver (Fast Matplotlib)")
        self.resize(1200, 700)
        
        # OSC server
        self.osc_server = None
        self.osc_thread = None
        self.running = False
        
        # Data buffers
        self.time_data = deque(maxlen=10000)
        self.voltage_data = deque(maxlen=10000)
        self.raw_data = deque(maxlen=10000)
        
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
        
        # Animation flag
        self.animation_running = False
        
        # Signals
        self.signals = OSCSignals()
        self.signals.new_data.connect(self.handle_new_data)
        
        # Build UI
        self.setup_ui()
    
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
    
    def get_local_ip(self):
        """Get the local IP address of this computer"""
        try:
            # Create a socket to determine local IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))  # Connect to Google DNS (doesn't actually send data)
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "Unable to detect"
        
    def create_controls_panel(self):
        """Create controls panel"""
        # Create scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMaximumWidth(350)
        
        # Create panel widget
        panel = QWidget()
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
        
        # Computer IP Address display
        ip_label = QLabel(f"Computer IP: {self.get_local_ip()}")
        ip_label.setFont(QFont("Georgia", 14, QFont.Weight.Bold))
        ip_label.setStyleSheet("color: #007AFF; padding: 8px; background-color: #F0F0F0; border-radius: 5px;")
        ip_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(ip_label)
        
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
        
        self.clear_btn = QPushButton("Clear Plot")
        self.clear_btn.setStyleSheet("background-color: #FF9500; color: white; font-weight: bold; padding: 8px;")
        self.clear_btn.clicked.connect(self.clear_plot)
        osc_layout.addWidget(self.clear_btn)
        
        self.status_label = QLabel("Status: Stopped")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")
        osc_layout.addWidget(self.status_label)
        
        self.debug_check = QCheckBox("Debug Mode")
        osc_layout.addWidget(self.debug_check)
        
        osc_group.setLayout(osc_layout)
        layout.addWidget(osc_group)
        
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
        
        # ESP32 Configuration
        esp_group = QGroupBox("ESP32 Configuration")
        esp_layout = QVBoxLayout()
        
        esp_layout.addWidget(QLabel("ESP32 IP Address:"))
        self.esp32_ip_input = QLineEdit()
        self.esp32_ip_input.setPlaceholderText("e.g., 192.168.1.100")
        esp_layout.addWidget(self.esp32_ip_input)
        
        esp_layout.addWidget(QLabel("Mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Single-Ended", "Differential"])
        esp_layout.addWidget(self.mode_combo)
        
        esp_layout.addWidget(QLabel("Gain:"))
        self.gain_combo = QComboBox()
        self.gain_combo.addItems([
            "TWOTHIRDS (±6.144V)",
            "ONE (±4.096V)",
            "TWO (±2.048V)",
            "FOUR (±1.024V)",
            "EIGHT (±0.512V)",
            "SIXTEEN (±0.256V)"
        ])
        self.gain_combo.setCurrentIndex(1)  # Default to ONE
        esp_layout.addWidget(self.gain_combo)
        
        esp_layout.addWidget(QLabel("Sample Rate (Hz):"))
        self.sample_rate_input = QSpinBox()
        self.sample_rate_input.setRange(1, 1000)
        self.sample_rate_input.setValue(10)
        esp_layout.addWidget(self.sample_rate_input)
        
        # Serial Debug checkbox
        debug_layout = QHBoxLayout()
        debug_layout.addWidget(QLabel("Serial Debug:"))
        self.serial_debug_check = QCheckBox()
        self.serial_debug_check.setChecked(False)
        debug_layout.addWidget(self.serial_debug_check)
        debug_layout.addStretch()
        esp_layout.addLayout(debug_layout)
        
        self.apply_config_btn = QPushButton("Apply Configuration")
        self.apply_config_btn.setStyleSheet("background-color: #007AFF; color: white; font-weight: bold; padding: 8px;")
        self.apply_config_btn.clicked.connect(self.apply_esp32_config)
        self.apply_config_btn.setEnabled(False)
        esp_layout.addWidget(self.apply_config_btn)
        
        esp_note = QLabel("Click Apply to send config to ESP32")
        esp_note.setStyleSheet("color: gray; font-size: 9pt;")
        esp_layout.addWidget(esp_note)
        
        esp_group.setLayout(esp_layout)
        layout.addWidget(esp_group)
        
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
        
        self.interpolate_check = QCheckBox("Interpolate Curve")
        self.interpolate_check.setChecked(False)
        plot_layout.addWidget(self.interpolate_check)
        
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
        self.window_input.setRange(10, 10000)
        self.window_input.setValue(1000)
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
        
        # Set panel as scroll area widget
        scroll.setWidget(panel)
        
        return scroll
    
    def create_plot_panel(self):
        """Create plot panel with Matplotlib animation"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # Current reading with progress bar
        reading_layout = QHBoxLayout()
        reading_layout.addWidget(QLabel("Current:"))
        self.current_reading = QLabel("0.000 V")
        self.current_reading.setFont(QFont("Monaco", 16, QFont.Weight.Bold))
        reading_layout.addWidget(self.current_reading)
        
        # Progress bar
        self.voltage_bar = QProgressBar()
        self.voltage_bar.setRange(0, 5000)
        self.voltage_bar.setValue(0)
        self.voltage_bar.setTextVisible(False)
        self.voltage_bar.setMaximumHeight(20)
        self.voltage_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid grey;
                border-radius: 5px;
            }
            QProgressBar::chunk {
                background-color: #007AFF;
            }
        """)
        reading_layout.addWidget(self.voltage_bar)
        
        # Indicator
        self.reading_indicator = QLabel("●")
        self.reading_indicator.setStyleSheet("color: gray; font-size: 16pt;")
        reading_layout.addWidget(self.reading_indicator)
        
        reading_layout.addStretch()
        layout.addLayout(reading_layout)
        
        # Matplotlib figure
        self.figure = Figure(figsize=(8, 6))
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.ax = self.figure.add_subplot(111)
        self.ax.set_xlabel('Sample Number')
        self.ax.set_ylabel('Voltage (V)')
        self.ax.set_title('Channel 0 - Real-Time Data')
        self.ax.grid(True, alpha=0.3)
        
        # Create line object (will be updated by animation)
        self.line, = self.ax.plot([], [], 'b-', linewidth=2, antialiased=True, animated=True)
        
        # Threshold lines (animated for blitting)
        self.thresh_high_line = self.ax.axhline(y=1.0, color='red', linestyle='--', linewidth=1.5, alpha=0.7, visible=False, animated=True)
        self.thresh_low_line = self.ax.axhline(y=0.1, color='orange', linestyle='--', linewidth=1.5, alpha=0.7, visible=False, animated=True)
        
        self.ax.set_xlim(0, 10)
        self.ax.set_ylim(0, 5)
        
        # Add matplotlib navigation toolbar
        toolbar = NavigationToolbar2QT(self.canvas, panel)
        layout.addWidget(toolbar)
        layout.addWidget(self.canvas)
        
        # Set up animation with blitting
        self.anim = FuncAnimation(
            self.figure, 
            self.animate,
            interval=16,  # ~60 FPS (was 33ms/30fps)
            blit=True,    # Use blitting for speed!
            cache_frame_data=False
        )
        
        return panel
    
    def animate(self, frame):
        """Animation update function with blitting"""
        if not self.running or len(self.time_data) < 2:
            return self.line, self.thresh_high_line, self.thresh_low_line
        
        # Get data
        window = min(self.window_input.value(), len(self.time_data))
        time_array = np.array(list(self.time_data)[-window:])
        voltage_array = np.array(list(self.voltage_data)[-window:])
        
        # Apply interpolation if enabled
        if self.interpolate_check.isChecked() and len(time_array) > 10:
            try:
                f = interpolate.interp1d(time_array, voltage_array, kind='cubic')
                time_smooth = np.linspace(time_array[0], time_array[-1], len(time_array) * 10)
                voltage_smooth = f(time_smooth)
                self.line.set_data(time_smooth, voltage_smooth)
            except:
                self.line.set_data(time_array, voltage_array)
        else:
            self.line.set_data(time_array, voltage_array)
        
        # Update X limits
        if len(time_array) > 1:
            self.ax.set_xlim(time_array[0], time_array[-1])
        
        # Update Y limits
        if self.autoscale_check.isChecked():
            if len(voltage_array) > 0:
                y_min = max(0, min(voltage_array) - 0.2)
                y_max = max(voltage_array) + 0.2
                self.ax.set_ylim(y_min, y_max)
        else:
            self.ax.set_ylim(self.y_min_input.value(), self.y_max_input.value())
        
        # Update threshold lines
        if self.thresh_enable.isChecked():
            self.thresh_high_line.set_ydata([self.thresh_high.value(), self.thresh_high.value()])
            self.thresh_low_line.set_ydata([self.thresh_low.value(), self.thresh_low.value()])
            self.thresh_high_line.set_visible(True)
            self.thresh_low_line.set_visible(True)
        else:
            self.thresh_high_line.set_visible(False)
            self.thresh_low_line.set_visible(False)
        
        # Update statistics
        if self.start_time:
            elapsed = time.time() - self.start_time
            rate = self.sample_count / elapsed if elapsed > 0 else 0
            self.samples_label.setText(f"Samples: {self.sample_count}")
            self.rate_label.setText(f"Rate: {rate:.1f} Hz")
        
        return self.line, self.thresh_high_line, self.thresh_low_line
    
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
            self.apply_config_btn.setEnabled(True)
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
        self.apply_config_btn.setEnabled(False)
        self.status_label.setText("Status: Stopped")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")
        
        if self.logging_active:
            self.stop_logging()
        
        print("OSC server stopped")
    
    def clear_plot(self):
        """Clear all plot data"""
        self.time_data.clear()
        self.voltage_data.clear()
        self.raw_data.clear()
        self.filter_buffer.clear()
        self.sample_count = 0
        
        # Reset ESP32 timing
        if hasattr(self, 'current_sample_counter'):
            delattr(self, 'current_sample_counter')
        if hasattr(self, 'esp32_first_time'):
            delattr(self, 'esp32_first_time')
        
        # Reset start time if running
        if self.running:
            self.start_time = time.time()
        
        print("Plot cleared")
    
    def osc_raw_handler(self, address, *args):
        """OSC handler for raw value"""
        if len(args) >= 2:
            self.current_raw = args[0]
            self.current_raw_sample = args[1]
        elif len(args) >= 1:
            self.current_raw = args[0]
    
    def osc_voltage_handler(self, address, *args):
        """OSC handler for voltage value"""
        if len(args) >= 2:
            voltage = args[0]
            sample_counter = args[1]
            raw = getattr(self, 'current_raw', 0)
            
            # Store the sample counter directly
            self.current_sample_counter = sample_counter
            
            # Emit signal with data
            self.signals.new_data.emit(raw, voltage)
            
        elif len(args) >= 1:
            # Fallback for old format
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
        
        # Add to plot buffer using sample counter as X-axis
        if hasattr(self, 'current_sample_counter'):
            x_value = self.current_sample_counter
            timestamp_source = "Sample Counter"
        elif self.start_time:
            x_value = time.time() - self.start_time
            timestamp_source = "Python"
        else:
            x_value = self.sample_count
            timestamp_source = "Count"
        
        if self.debug_check.isChecked() and self.sample_count % 10 == 0:
            print(f"Sample {self.sample_count}: X={x_value}, Source={timestamp_source}, Voltage={filtered_voltage:.3f}V")
        
        self.time_data.append(x_value)
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
        
        # Update indicators
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
    
    def apply_esp32_config(self):
        """Send configuration to ESP32 via OSC"""
        esp32_ip = self.esp32_ip_input.text().strip()
        if not esp32_ip:
            QMessageBox.warning(self, "No IP Address", "Please enter ESP32 IP address")
            return
        
        try:
            # Create OSC client to send to ESP32
            config_client = SimpleUDPClient(esp32_ip, 9000)  # ESP32 listens on port 9000
            
            # Get mode
            mode = "single" if self.mode_combo.currentIndex() == 0 else "differential"
            
            # Get gain
            gain_map = ["TWOTHIRDS", "ONE", "TWO", "FOUR", "EIGHT", "SIXTEEN"]
            gain = gain_map[self.gain_combo.currentIndex()]
            
            # Get sample rate
            sample_rate = self.sample_rate_input.value()
            
            # Get serial debug state
            serial_debug = 1 if self.serial_debug_check.isChecked() else 0
            
            # Send config messages
            config_client.send_message("/config/mode", mode)
            config_client.send_message("/config/gain", gain)
            config_client.send_message("/config/samplerate", sample_rate)
            config_client.send_message("/config/serialdebug", serial_debug)
            
            debug_status = "ON" if serial_debug else "OFF"
            print(f"Sent config to {esp32_ip}: mode={mode}, gain={gain}, rate={sample_rate}Hz, debug={debug_status}")
            QMessageBox.information(self, "Configuration Sent", 
                f"Configuration sent to ESP32:\nMode: {mode}\nGain: {gain}\nSample Rate: {sample_rate} Hz\nSerial Debug: {debug_status}")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to send configuration:\n{e}")
    
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
