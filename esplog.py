#!/usr/bin/env python3
"""
ESPLog - Hybrid Ecologies ESP32 Data Logger and OSC Bridge
Serial + WiFi data acquisition with PyQt6 GUI

Requirements:
    pip3 install PyQt6 requests python-osc matplotlib pyserial

Usage:
    python3 esplog.py
"""

import sys
import json
import csv
import time
import threading
import queue
from pathlib import Path
from datetime import datetime
from collections import deque

import requests
from pythonosc import udp_client
import serial
import serial.tools.list_ports

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QLineEdit, QPushButton, QCheckBox, QComboBox, QSpinBox,
    QDoubleSpinBox, QGroupBox, QScrollArea, QFileDialog, QMessageBox,
    QRadioButton, QButtonGroup, QProgressBar, QSplitter
)
from PyQt6.QtCore import QTimer, Qt, pyqtSignal, QObject
from PyQt6.QtGui import QFont

import matplotlib
matplotlib.use('QtAgg')
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg, NavigationToolbar2QT
import numpy as np


class DataSignals(QObject):
    """Signals for thread-safe communication"""
    new_data = pyqtSignal(dict)
    connection_changed = pyqtSignal(bool)
    error_occurred = pyqtSignal(str)


class ADCClientGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ESPLog - Hybrid Ecologies Data Logger")
        self.resize(1400, 900)
        
        # Debug mode
        self.debug_mode = False
        
        # Config file
        self.config_file = Path.home() / ".esp32_adc_config.json"
        
        # Data acquisition state
        self.running = False
        self.connected = False
        self.logging_active = False
        self.streaming_active = True
        self.csv_file = None
        self.csv_writer = None
        self.csv_handle = None
        self.csv_base_name = None
        self.csv_row_count = 0
        
        # Connection mode
        self.connection_mode = 'wifi'  # 'wifi' or 'serial'
        self.serial_port = None
        
        # Statistics
        self.sample_count = 0
        self.error_count = 0
        self.start_time = None
        
        # Data buffers
        self.data_queue = queue.Queue()
        self.time_data = deque(maxlen=1000)
        self.ch0_data = deque(maxlen=1000)
        self.ch1_data = deque(maxlen=1000)
        self.ch2_data = deque(maxlen=1000)
        self.ch3_data = deque(maxlen=1000)
        
        # Filter buffers
        self.filter_buffers = [deque(maxlen=50) for _ in range(4)]
        
        # Threshold states
        self.threshold_states = [None, None, None, None]
        
        # Threading
        self.data_thread = None
        self.signals = DataSignals()
        self.signals.new_data.connect(self.handle_new_data)
        self.signals.connection_changed.connect(self.update_connection_status)
        
        # Default values
        self.default_values = {
            'sample_rate': 5,
            'osc_host': '127.0.0.1',
            'osc_port': 8000,
            'autoscale': True,
            'y_min': 0.0,
            'y_max': 5.0,
            'plot_window': 100,
            'show_channels': [True, True, True, True],
            'config_mode': 'simple',
            'adc_mode': 'single_ended',
            'adc_gain': 'ONE',
            'adc_data_rate': 1600,
            'thresholds': {f'ch{i}': {'enabled': False, 'high': 1.0, 'low': 0.1} for i in range(4)},
            'filters': {'use_filtered_output': False, **{f'ch{i}': {'enabled': False, 'window': 5} for i in range(4)}}
        }
        
        # Build UI
        self.setup_ui()
        
        # Load settings
        self.load_settings()
        
        # Setup update timer
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_display)
        self.update_timer.start(50)  # 20 Hz
        
        # Auto-save timer
        self.save_timer = QTimer()
        self.save_timer.timeout.connect(self.save_settings)
        self.save_timer.start(30000)  # Every 30 seconds
    
    def toggle_debug_mode(self):
        """Toggle debug output"""
        self.debug_mode = self.debug_check.isChecked()
        if self.debug_mode:
            print("DEBUG MODE ENABLED")
        else:
            print("DEBUG MODE DISABLED")
    
    def debug_print(self, message):
        """Print debug message if debug mode is enabled"""
        if self.debug_mode:
            print(message)
    
    def on_connection_mode_changed(self):
        """Handle connection mode switching"""
        if self.wifi_radio.isChecked():
            self.connection_mode = 'wifi'
            self.wifi_frame.show()
            self.serial_frame.hide()
        else:
            self.connection_mode = 'serial'
            self.wifi_frame.hide()
            self.serial_frame.show()
            self.refresh_serial_ports()
    
    def refresh_serial_ports(self):
        """Refresh the list of available serial ports"""
        self.serial_combo.clear()
        ports = serial.tools.list_ports.comports()
        
        if not ports:
            self.serial_combo.addItem("No ports found")
            self.serial_combo.setEnabled(False)
        else:
            self.serial_combo.setEnabled(True)
            for port in ports:
                # Show port name and description
                self.serial_combo.addItem(f"{port.device} - {port.description}", port.device)
    
    def setup_ui(self):
        """Create the user interface"""
        # Central widget with splitter
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)
        
        # Left panel - Controls (scrollable)
        controls = self.create_controls_panel()
        splitter.addWidget(controls)
        
        # Right panel - Status and Plot
        right_panel = self.create_right_panel()
        splitter.addWidget(right_panel)
        
        # Set splitter sizes (30% controls, 70% plot)
        splitter.setSizes([400, 1000])
    
    def create_controls_panel(self):
        """Create scrollable controls panel"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMaximumWidth(450)
        
        container = QWidget()
        layout = QVBoxLayout(container)
        
        # Header section
        header_frame = QWidget()
        header_layout = QVBoxLayout(header_frame)
        header_layout.setContentsMargins(10, 15, 10, 15)
        header_layout.setSpacing(5)
        
        # Main title
        title = QLabel("Hybrid Ecologies")
        title.setFont(QFont("Georgia", 24, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(title)
        
        # Subtitle
        subtitle = QLabel("Spring 2026")
        subtitle.setFont(QFont("Georgia", 18))
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(subtitle)
        
        # Description
        description = QLabel("Serial + WiFi ESP32 Data Logger and OSC streamer")
        description.setFont(QFont("Georgia", 14))
        description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        description.setWordWrap(True)
        description.setStyleSheet("margin-top: 5px;")
        header_layout.addWidget(description)
        
        # Author
        author = QLabel("Brett Ian Balogh, 2026")
        author.setFont(QFont("Georgia", 10))
        author.setAlignment(Qt.AlignmentFlag.AlignCenter)
        author.setStyleSheet("margin-top: 5px;")
        header_layout.addWidget(author)
        
        # Separator line
        separator = QLabel()
        separator.setFixedHeight(1)
        separator.setStyleSheet("background-color: #CCC; margin-top: 10px; margin-bottom: 10px;")
        header_layout.addWidget(separator)
        
        layout.addWidget(header_frame)
        
        # Connection
        conn_group = QGroupBox("Connection")
        conn_layout = QVBoxLayout()
        
        # Connection mode selection
        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("Mode:"))
        self.wifi_radio = QRadioButton("WiFi")
        self.serial_radio = QRadioButton("Serial")
        self.wifi_radio.setChecked(True)
        self.wifi_radio.toggled.connect(self.on_connection_mode_changed)
        mode_layout.addWidget(self.wifi_radio)
        mode_layout.addWidget(self.serial_radio)
        mode_layout.addStretch()
        conn_layout.addLayout(mode_layout)
        
        # WiFi settings
        self.wifi_frame = QWidget()
        wifi_layout = QVBoxLayout(self.wifi_frame)
        wifi_layout.setContentsMargins(0, 0, 0, 0)
        
        wifi_layout.addWidget(QLabel("ESP32 IP:"))
        self.ip_input = QLineEdit("192.168.1.47")
        wifi_layout.addWidget(self.ip_input)
        
        conn_layout.addWidget(self.wifi_frame)
        
        # Serial settings
        self.serial_frame = QWidget()
        serial_layout = QVBoxLayout(self.serial_frame)
        serial_layout.setContentsMargins(0, 0, 0, 0)
        
        port_layout = QHBoxLayout()
        port_layout.addWidget(QLabel("Serial Port:"))
        self.serial_combo = QComboBox()
        port_layout.addWidget(self.serial_combo)
        self.refresh_ports_btn = QPushButton("↻")
        self.refresh_ports_btn.setMaximumWidth(40)
        self.refresh_ports_btn.setToolTip("Refresh serial ports")
        self.refresh_ports_btn.clicked.connect(self.refresh_serial_ports)
        port_layout.addWidget(self.refresh_ports_btn)
        serial_layout.addLayout(port_layout)
        
        baud_layout = QHBoxLayout()
        baud_layout.addWidget(QLabel("Baud Rate:"))
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(['9600', '19200', '38400', '57600', '115200'])
        self.baud_combo.setCurrentText('115200')
        baud_layout.addWidget(self.baud_combo)
        serial_layout.addLayout(baud_layout)
        
        conn_layout.addWidget(self.serial_frame)
        self.serial_frame.hide()  # Hide initially
        
        # Sample rate (common to both modes)
        conn_layout.addWidget(QLabel("Sample Rate (Hz):"))
        self.rate_input = QSpinBox()
        self.rate_input.setRange(1, 200)
        self.rate_input.setValue(5)
        conn_layout.addWidget(self.rate_input)
        
        # Debug mode checkbox
        self.debug_check = QCheckBox("Debug Mode (show terminal output)")
        self.debug_check.setChecked(False)
        self.debug_check.stateChanged.connect(self.toggle_debug_mode)
        conn_layout.addWidget(self.debug_check)
        
        self.start_btn = QPushButton("Start")
        self.start_btn.setStyleSheet("background-color: #007AFF; color: white; font-weight: bold; padding: 10px;")
        self.start_btn.clicked.connect(self.toggle_running)
        conn_layout.addWidget(self.start_btn)
        
        conn_group.setLayout(conn_layout)
        layout.addWidget(conn_group)
        
        # OSC Settings
        osc_group = QGroupBox("OSC Settings")
        osc_layout = QVBoxLayout()
        
        osc_layout.addWidget(QLabel("OSC Host:"))
        self.osc_host_input = QLineEdit("127.0.0.1")
        osc_layout.addWidget(self.osc_host_input)
        
        osc_layout.addWidget(QLabel("OSC Port:"))
        self.osc_port_input = QSpinBox()
        self.osc_port_input.setRange(1, 65535)
        self.osc_port_input.setValue(8000)
        osc_layout.addWidget(self.osc_port_input)
        
        self.stream_btn = QPushButton("Stop Streaming")
        self.stream_btn.setStyleSheet("background-color: #007AFF; color: white; font-weight: bold; padding: 8px;")
        self.stream_btn.setEnabled(False)
        self.stream_btn.clicked.connect(self.toggle_streaming)
        osc_layout.addWidget(self.stream_btn)
        
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
        
        # Row counter
        self.row_counter_label = QLabel("Rows logged: 0")
        self.row_counter_label.setStyleSheet("color: gray; font-size: 11pt;")
        log_layout.addWidget(self.row_counter_label)
        
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)
        
        # ESP32 Configuration
        config_group = QGroupBox("ESP32 Configuration")
        config_layout = QVBoxLayout()
        
        mode_layout = QHBoxLayout()
        self.simple_radio = QRadioButton("Simple")
        self.advanced_radio = QRadioButton("Advanced")
        self.simple_radio.setChecked(True)
        mode_layout.addWidget(self.simple_radio)
        mode_layout.addWidget(self.advanced_radio)
        config_layout.addLayout(mode_layout)
        
        config_layout.addWidget(QLabel("Mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(['single_ended', 'differential'])
        config_layout.addWidget(self.mode_combo)
        
        config_layout.addWidget(QLabel("Gain:"))
        self.gain_combo = QComboBox()
        self.gain_combo.addItems(['TWOTHIRDS', 'ONE', 'TWO', 'FOUR', 'EIGHT', 'SIXTEEN'])
        self.gain_combo.setCurrentText('ONE')
        config_layout.addWidget(self.gain_combo)
        
        self.apply_config_btn = QPushButton("Apply Configuration")
        self.apply_config_btn.setStyleSheet("background-color: #007AFF; color: white; font-weight: bold; padding: 8px;")
        self.apply_config_btn.setEnabled(False)
        self.apply_config_btn.clicked.connect(self.apply_esp32_config)
        config_layout.addWidget(self.apply_config_btn)
        
        config_group.setLayout(config_layout)
        layout.addWidget(config_group)
        
        # Channel Visibility
        chan_group = QGroupBox("Channel Visibility")
        chan_layout = QVBoxLayout()
        
        self.ch_checks = []
        for i in range(4):
            check = QCheckBox(f"Channel {i}")
            check.setChecked(True)
            chan_layout.addWidget(check)
            self.ch_checks.append(check)
        
        chan_group.setLayout(chan_layout)
        layout.addWidget(chan_group)
        
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
        self.window_input.setRange(10, 10000)
        self.window_input.setValue(100)
        plot_layout.addWidget(self.window_input)
        
        plot_group.setLayout(plot_layout)
        layout.addWidget(plot_group)
        
        # Threshold Alerts
        thresh_group = QGroupBox("Threshold Alerts")
        thresh_layout = QVBoxLayout()
        
        self.thresh_enabled = []
        self.thresh_high = []
        self.thresh_low = []
        self.thresh_indicators = []
        
        for i in range(4):
            ch_box = QGroupBox(f"Channel {i}")
            ch_layout = QVBoxLayout()
            
            enable = QCheckBox("Enable")
            ch_layout.addWidget(enable)
            self.thresh_enabled.append(enable)
            
            high_layout = QHBoxLayout()
            high_layout.addWidget(QLabel("High:"))
            high_spin = QDoubleSpinBox()
            high_spin.setRange(0, 10)
            high_spin.setSingleStep(0.1)
            high_spin.setDecimals(2)
            high_spin.setValue(1.0)
            high_layout.addWidget(high_spin)
            high_layout.addWidget(QLabel("V"))
            ch_layout.addLayout(high_layout)
            self.thresh_high.append(high_spin)
            
            low_layout = QHBoxLayout()
            low_layout.addWidget(QLabel("Low:"))
            low_spin = QDoubleSpinBox()
            low_spin.setRange(0, 10)
            low_spin.setSingleStep(0.1)
            low_spin.setDecimals(2)
            low_spin.setValue(0.1)
            low_layout.addWidget(low_spin)
            low_layout.addWidget(QLabel("V"))
            ch_layout.addLayout(low_layout)
            self.thresh_low.append(low_spin)
            
            ch_box.setLayout(ch_layout)
            thresh_layout.addWidget(ch_box)
        
        thresh_group.setLayout(thresh_layout)
        layout.addWidget(thresh_group)
        
        # Low-Pass Filters
        filter_group = QGroupBox("Low-Pass Filters")
        filter_layout = QVBoxLayout()
        
        output_layout = QHBoxLayout()
        output_layout.addWidget(QLabel("Output:"))
        self.raw_radio = QRadioButton("Raw")
        self.filtered_radio = QRadioButton("Filtered")
        self.raw_radio.setChecked(True)
        output_layout.addWidget(self.raw_radio)
        output_layout.addWidget(self.filtered_radio)
        filter_layout.addLayout(output_layout)
        
        self.filter_enabled = []
        self.filter_window = []
        
        for i in range(4):
            ch_box = QGroupBox(f"Channel {i}")
            ch_layout = QVBoxLayout()
            
            enable = QCheckBox("Enable Filter")
            ch_layout.addWidget(enable)
            self.filter_enabled.append(enable)
            
            window_layout = QHBoxLayout()
            window_layout.addWidget(QLabel("Window:"))
            window_spin = QSpinBox()
            window_spin.setRange(2, 50)
            window_spin.setValue(5)
            window_layout.addWidget(window_spin)
            window_layout.addWidget(QLabel("samples"))
            ch_layout.addLayout(window_layout)
            self.filter_window.append(window_spin)
            
            ch_box.setLayout(ch_layout)
            filter_layout.addWidget(ch_box)
        
        filter_group.setLayout(filter_layout)
        layout.addWidget(filter_group)
        
        # Restore Defaults button at bottom of controls
        layout.addSpacing(10)
        
        restore_frame = QWidget()
        restore_layout = QVBoxLayout(restore_frame)
        restore_layout.setContentsMargins(0, 0, 0, 0)
        
        self.restore_btn = QPushButton("⟲ Restore Defaults")
        self.restore_btn.setStyleSheet("background-color: #FF9500; color: white; font-weight: bold; padding: 10px;")
        self.restore_btn.clicked.connect(self.restore_defaults)
        restore_layout.addWidget(self.restore_btn)
        
        hint_label = QLabel("(Sample rate: 5Hz, No filters, No alerts)")
        hint_label.setStyleSheet("color: gray; font-size: 9pt;")
        hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        restore_layout.addWidget(hint_label)
        
        layout.addWidget(restore_frame)
        
        layout.addStretch()
        scroll.setWidget(container)
        return scroll
    
    def create_right_panel(self):
        """Create status and plot panel"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Status
        status_group = QGroupBox("Status")
        status_layout = QVBoxLayout()
        
        self.connection_label = QLabel("Connection: Disconnected")
        self.connection_label.setStyleSheet("color: red; font-weight: bold;")
        status_layout.addWidget(self.connection_label)
        
        self.logging_label = QLabel("Logging: Off")
        self.logging_label.setStyleSheet("color: gray;")
        status_layout.addWidget(self.logging_label)
        
        self.streaming_label = QLabel("Streaming: Off")
        self.streaming_label.setStyleSheet("color: gray;")
        status_layout.addWidget(self.streaming_label)
        
        stats_layout = QHBoxLayout()
        self.samples_label = QLabel("Samples: 0")
        self.rate_label = QLabel("Rate: 0.0 Hz")
        stats_layout.addWidget(self.samples_label)
        stats_layout.addWidget(self.rate_label)
        status_layout.addLayout(stats_layout)
        
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)
        
        # Current Readings
        readings_group = QGroupBox("Current Readings")
        readings_layout = QVBoxLayout()
        
        self.reading_labels = []
        self.reading_indicators = []
        self.reading_progress = []
        
        for i in range(4):
            row = QHBoxLayout()
            row.addWidget(QLabel(f"Ch{i}:"))
            
            reading = QLabel("0.000 V")
            reading.setFont(QFont("Monaco", 10, QFont.Weight.Bold))
            row.addWidget(reading)
            self.reading_labels.append(reading)
            
            progress = QProgressBar()
            progress.setRange(0, 5000)
            progress.setValue(0)
            progress.setTextVisible(False)
            progress.setMaximumHeight(15)
            row.addWidget(progress)
            self.reading_progress.append(progress)
            
            indicator = QLabel("●")
            indicator.setStyleSheet("color: gray; font-size: 16pt;")
            row.addWidget(indicator)
            self.reading_indicators.append(indicator)
            
            readings_layout.addLayout(row)
        
        readings_group.setLayout(readings_layout)
        layout.addWidget(readings_group)
        
        # Plot
        plot_group = QGroupBox("Real-Time Plot")
        plot_layout = QVBoxLayout()
        
        self.figure = Figure(figsize=(8, 6))
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.ax = self.figure.add_subplot(111)
        self.ax.set_xlabel('Time (s)')
        self.ax.set_ylabel('Voltage (V)')
        self.ax.set_title('ADC Channels')
        self.ax.grid(True, alpha=0.3)
        
        # Create lines
        self.line0, = self.ax.plot([], [], 'b-', label='Channel 0', linewidth=1.5)
        self.line1, = self.ax.plot([], [], 'r-', label='Channel 1', linewidth=1.5)
        self.line2, = self.ax.plot([], [], 'g-', label='Channel 2', linewidth=1.5)
        self.line3, = self.ax.plot([], [], 'm-', label='Channel 3', linewidth=1.5)
        
        # Threshold lines
        self.threshold_high_lines = []
        self.threshold_low_lines = []
        colors = ['blue', 'red', 'green', 'magenta']
        for color in colors:
            high_line = self.ax.axhline(y=0, color=color, linestyle='--', linewidth=1, alpha=0.7, visible=False)
            low_line = self.ax.axhline(y=0, color=color, linestyle='--', linewidth=1, alpha=0.7, visible=False)
            self.threshold_high_lines.append(high_line)
            self.threshold_low_lines.append(low_line)
        
        self.ax.legend()
        
        toolbar = NavigationToolbar2QT(self.canvas, widget)
        plot_layout.addWidget(toolbar)
        plot_layout.addWidget(self.canvas)
        
        plot_group.setLayout(plot_layout)
        layout.addWidget(plot_group)
        
        return widget
    
    def toggle_running(self):
        """Start/stop data collection"""
        self.debug_print(f"toggle_running called, current running={self.running}")
        if not self.running:
            # Start
            self.running = True
            self.start_time = time.time()
            self.sample_count = 0
            self.error_count = 0
            
            self.start_btn.setText("Stop")
            self.log_btn.setEnabled(True)
            self.stream_btn.setEnabled(True)
            self.apply_config_btn.setEnabled(True)
            
            self.debug_print(f"Starting data thread, mode={self.connection_mode}")
            
            # Start data thread
            self.data_thread = threading.Thread(target=self.data_acquisition_loop, daemon=True)
            self.data_thread.start()
            
        else:
            # Stop
            self.debug_print("Stopping data collection")
            self.running = False
            self.start_btn.setText("Start")
            self.log_btn.setEnabled(False)
            self.stream_btn.setEnabled(False)
            self.apply_config_btn.setEnabled(False)
            
            if self.logging_active:
                self.stop_logging()
    
    def toggle_logging(self):
        """Toggle CSV logging"""
        if not self.logging_active:
            self.start_logging()
        else:
            self.stop_logging()
    
    def start_logging(self):
        """Start CSV logging"""
        if self.csv_base_name is None:
            filename, _ = QFileDialog.getSaveFileName(
                self, "Save CSV Log", "", "CSV Files (*.csv)"
            )
            if not filename:
                return
            self.csv_base_name = Path(filename).stem
        
        # Find next available index
        index = 0
        while True:
            if index == 0:
                csv_path = Path.cwd() / f"{self.csv_base_name}.csv"
            else:
                csv_path = Path.cwd() / f"{self.csv_base_name}_{index:03d}.csv"
            
            if not csv_path.exists():
                break
            index += 1
        
        self.csv_file = csv_path
        self.csv_handle = open(self.csv_file, 'w', newline='')
        self.csv_writer = csv.writer(self.csv_handle)
        
        # Write header
        header = ['timestamp_local', 'timestamp_esp32']
        for i in range(4):
            header.extend([f'ch{i}_raw', f'ch{i}_voltage'])
        self.csv_writer.writerow(header)
        
        self.logging_active = True
        self.log_btn.setText("Stop Logging")
        self.logging_label.setText(f"Logging: On ({self.csv_file.name})")
        self.logging_label.setStyleSheet("color: green; font-weight: bold;")
        
        # Reset row counter
        self.csv_row_count = 0
        self.row_counter_label.setText("Rows logged: 0")
    
    def stop_logging(self):
        """Stop CSV logging"""
        if self.csv_handle:
            self.csv_handle.close()
            self.csv_handle = None
            self.csv_writer = None
        
        self.logging_active = False
        self.log_btn.setText("Start Logging")
        self.logging_label.setText("Logging: Off")
        self.logging_label.setStyleSheet("color: gray;")
    
    def toggle_streaming(self):
        """Toggle OSC streaming"""
        self.streaming_active = not self.streaming_active
        
        if self.streaming_active:
            self.stream_btn.setText("Stop Streaming")
            self.streaming_label.setText("Streaming: On")
            self.streaming_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.stream_btn.setText("Start Streaming")
            self.streaming_label.setText("Streaming: Off")
            self.streaming_label.setStyleSheet("color: gray;")
    
    def apply_esp32_config(self):
        """Send configuration to ESP32"""
        config = {
            'mode': self.mode_combo.currentText(),
            'gain': self.gain_combo.currentText()
        }
        
        try:
            url = f"http://{self.ip_input.text()}/config"
            response = requests.post(url, json=config, timeout=5)
            response.raise_for_status()
            QMessageBox.information(self, "Success", "Configuration applied to ESP32")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to apply configuration:\n{e}")
    
    def data_acquisition_loop(self):
        """Background thread for data acquisition"""
        self.debug_print("data_acquisition_loop started")
        sample_interval = 1.0 / self.rate_input.value()
        self.debug_print(f"sample_interval={sample_interval}")
        
        # Setup OSC client
        osc_client = udp_client.SimpleUDPClient(
            self.osc_host_input.text(),
            self.osc_port_input.value()
        )
        
        # Connect based on mode
        self.debug_print(f"Connection mode = {self.connection_mode}")
        if self.connection_mode == 'wifi':
            url = f"http://{self.ip_input.text()}/data"
            self.debug_print(f"WiFi mode, URL = {url}")
            
            # Test WiFi connection
            try:
                self.debug_print("Testing WiFi connection...")
                response = requests.get(url, timeout=2)
                response.raise_for_status()
                self.debug_print("WiFi connection successful")
                self.signals.connection_changed.emit(True)
            except Exception as e:
                self.debug_print(f"WiFi connection failed: {e}")
                self.signals.connection_changed.emit(False)
                self.signals.error_occurred.emit(f"WiFi connection failed: {e}")
                self.running = False
                return
            
            # WiFi acquisition loop
            self.debug_print("Starting WiFi acquisition loop")
            next_sample_time = time.time()
            
            while self.running:
                current_time = time.time()
                
                if current_time < next_sample_time:
                    time.sleep(max(0, next_sample_time - current_time))
                    continue
                
                try:
                    response = requests.get(url, timeout=2)
                    response.raise_for_status()
                    data = response.json()
                    
                    self.process_data(data, osc_client)
                    
                except Exception as e:
                    self.error_count += 1
                    print(f"WiFi Error: {e}")
                
                next_sample_time += sample_interval
                
                if next_sample_time < current_time:
                    next_sample_time = current_time + sample_interval
        
        else:  # Serial mode
            self.debug_print("Serial mode")
            # Get selected port
            port_data = self.serial_combo.currentData()
            self.debug_print(f"Selected port data = {port_data}")
            if not port_data:
                self.debug_print("No serial port selected")
                self.signals.connection_changed.emit(False)
                self.signals.error_occurred.emit("No serial port selected")
                self.running = False
                return
            
            baud_rate = int(self.baud_combo.currentText())
            self.debug_print(f"Baud rate = {baud_rate}")
            
            # Open serial connection
            try:
                self.debug_print(f"Opening serial port {port_data}...")
                self.serial_port = serial.Serial(port_data, baud_rate, timeout=1)
                time.sleep(2)  # Wait for ESP32 to reset
                self.debug_print("Serial connection successful")
                self.signals.connection_changed.emit(True)
            except Exception as e:
                self.debug_print(f"Serial connection failed: {e}")
                self.signals.connection_changed.emit(False)
                self.signals.error_occurred.emit(f"Serial connection failed: {e}")
                self.running = False
                return
            
            # Serial acquisition loop
            self.debug_print("Starting serial acquisition loop")
            next_sample_time = time.time()
            line_buffer = ""
            
            while self.running:
                current_time = time.time()
                
                if current_time < next_sample_time:
                    time.sleep(max(0, next_sample_time - current_time))
                    continue
                
                try:
                    # Read line from serial
                    if self.serial_port.in_waiting > 0:
                        chunk = self.serial_port.read(self.serial_port.in_waiting).decode('utf-8', errors='ignore')
                        line_buffer += chunk
                        
                        # Process complete lines
                        while '\n' in line_buffer:
                            line, line_buffer = line_buffer.split('\n', 1)
                            line = line.strip()
                            
                            # Try to parse as JSON
                            if line.startswith('{'):
                                try:
                                    data = json.loads(line)
                                    if 'channels' in data:
                                        self.debug_print(f"Received JSON: {data}")
                                        self.process_data(data, osc_client)
                                except json.JSONDecodeError as e:
                                    self.debug_print(f"JSON decode error: {e}, line: {line}")
                                    pass  # Ignore malformed JSON
                    
                except Exception as e:
                    self.error_count += 1
                    print(f"Serial Error: {e}")
                
                next_sample_time += sample_interval
                
                if next_sample_time < current_time:
                    next_sample_time = current_time + sample_interval
            
            # Close serial port
            if self.serial_port:
                self.serial_port.close()
                self.serial_port = None
    
    def process_data(self, data, osc_client):
        """Process received data (common for WiFi and Serial)"""
        # Apply filters
        filtered_data = self.apply_filters(data)
        
        # Emit signal for UI update
        self.signals.new_data.emit(data)
        
        # Decide output mode
        use_filtered = self.filtered_radio.isChecked()
        output_data = filtered_data if use_filtered else data['channels']
        
        # Log to CSV
        if self.logging_active and self.csv_writer:
            timestamp_local = datetime.now().isoformat()
            timestamp_esp32 = data.get('timestamp', 0)
            
            row = [timestamp_local, timestamp_esp32]
            for i in range(4):
                if str(i) in output_data:
                    if use_filtered:
                        row.extend([output_data[str(i)]['raw'], output_data[str(i)]['filtered_voltage']])
                    else:
                        row.extend([output_data[str(i)]['raw'], output_data[str(i)]['voltage']])
                else:
                    row.extend([0, 0.0])
            
            self.csv_writer.writerow(row)
            self.csv_row_count += 1
            
            # Update row counter display every 10 rows to avoid UI lag
            if self.csv_row_count % 10 == 0:
                self.row_counter_label.setText(f"Rows logged: {self.csv_row_count}")
            
            if self.sample_count % 100 == 0:
                self.csv_handle.flush()
        
        # Send OSC
        if self.streaming_active:
            for ch_num in range(4):
                if str(ch_num) in output_data:
                    ch_data = output_data[str(ch_num)]
                    osc_client.send_message(f"/adc/ch{ch_num}/raw", ch_data['raw'])
                    
                    voltage = ch_data['filtered_voltage'] if use_filtered else ch_data['voltage']
                    osc_client.send_message(f"/adc/ch{ch_num}/voltage", voltage)
            
            # Check thresholds
            self.check_thresholds(filtered_data, osc_client)
        
        self.sample_count += 1
    
    def apply_filters(self, data):
        """Apply low-pass filters to channel data"""
        channels = data['channels']
        filtered_data = {}
        
        for i in range(4):
            if str(i) not in channels:
                continue
            
            # Ensure voltage and raw are numeric
            try:
                voltage = float(channels[str(i)]['voltage'])
                raw = int(channels[str(i)]['raw'])
            except (ValueError, TypeError, KeyError):
                continue
            
            # Add to filter buffer
            self.filter_buffers[i].append(voltage)
            
            # Calculate filtered value
            if self.filter_enabled[i].isChecked() and len(self.filter_buffers[i]) > 0:
                window = min(self.filter_window[i].value(), len(self.filter_buffers[i]))
                recent_samples = list(self.filter_buffers[i])[-window:]
                filtered_voltage = sum(recent_samples) / len(recent_samples)
            else:
                filtered_voltage = voltage
            
            filtered_data[str(i)] = {
                'raw': raw,
                'voltage': voltage,
                'filtered_voltage': filtered_voltage
            }
        
        return filtered_data
    
    def check_thresholds(self, data, osc_client):
        """Check voltage thresholds and send OSC alerts"""
        channels = data
        
        for i in range(4):
            if str(i) not in channels or not self.thresh_enabled[i].isChecked():
                continue
            
            try:
                voltage = channels[str(i)]['filtered_voltage'] if self.filter_enabled[i].isChecked() else channels[str(i)]['voltage']
                high_thresh = self.thresh_high[i].value()
                low_thresh = self.thresh_low[i].value()
            except (ValueError, KeyError):
                continue
            
            current_state = None
            
            if voltage > high_thresh:
                current_state = 'high'
            elif voltage < low_thresh:
                current_state = 'low'
            else:
                current_state = 'normal'
            
            # Send OSC alert if state changed
            if current_state != self.threshold_states[i]:
                if current_state == 'high':
                    osc_client.send_message(f"/adc/alert/ch{i}/high", [voltage, high_thresh])
                    print(f"[ALERT] Channel {i} HIGH: {voltage:.3f}V > {high_thresh:.3f}V")
                elif current_state == 'low':
                    osc_client.send_message(f"/adc/alert/ch{i}/low", [voltage, low_thresh])
                    print(f"[ALERT] Channel {i} LOW: {voltage:.3f}V < {low_thresh:.3f}V")
                elif self.threshold_states[i] is not None:
                    osc_client.send_message(f"/adc/alert/ch{i}/normal", voltage)
                    print(f"[ALERT] Channel {i} NORMAL: {voltage:.3f}V")
                
                self.threshold_states[i] = current_state
    
    def handle_new_data(self, data):
        """Handle new data from acquisition thread (runs in main thread)"""
        # Apply filters
        filtered_data = self.apply_filters(data)
        use_filtered = self.filtered_radio.isChecked()
        
        # Add to plot buffers
        if self.start_time:
            elapsed = time.time() - self.start_time
            self.time_data.append(elapsed)
            
            # Use filtered or raw based on toggle
            if use_filtered:
                self.ch0_data.append(float(filtered_data.get('0', {}).get('filtered_voltage', 0.0)))
                self.ch1_data.append(float(filtered_data.get('1', {}).get('filtered_voltage', 0.0)))
                self.ch2_data.append(float(filtered_data.get('2', {}).get('filtered_voltage', 0.0)))
                self.ch3_data.append(float(filtered_data.get('3', {}).get('filtered_voltage', 0.0)))
            else:
                channels = data.get('channels', {})
                try:
                    self.ch0_data.append(float(channels.get('0', {}).get('voltage', 0.0)))
                    self.ch1_data.append(float(channels.get('1', {}).get('voltage', 0.0)))
                    self.ch2_data.append(float(channels.get('2', {}).get('voltage', 0.0)))
                    self.ch3_data.append(float(channels.get('3', {}).get('voltage', 0.0)))
                except (ValueError, TypeError):
                    # If conversion fails, use 0.0
                    self.ch0_data.append(0.0)
                    self.ch1_data.append(0.0)
                    self.ch2_data.append(0.0)
                    self.ch3_data.append(0.0)
            
            # Update readings
            channels = data.get('channels', {})
            for i in range(4):
                if str(i) in channels:
                    try:
                        if use_filtered and str(i) in filtered_data:
                            voltage = filtered_data[str(i)]['filtered_voltage']
                        else:
                            voltage = channels[str(i)].get('voltage', 0.0)
                        
                        # Convert to float if it's a string (can happen with serial data)
                        voltage = float(voltage)
                    except (ValueError, TypeError, KeyError):
                        voltage = 0.0
                    
                    self.reading_labels[i].setText(f"{voltage:.3f} V")
                    self.reading_progress[i].setValue(int(min(voltage, 5.0) * 1000))
                    
                    # Update threshold indicator
                    if self.thresh_enabled[i].isChecked():
                        try:
                            high_thresh = self.thresh_high[i].value()
                            low_thresh = self.thresh_low[i].value()
                            
                            if voltage > high_thresh:
                                self.reading_indicators[i].setStyleSheet("color: red; font-size: 16pt;")
                            elif voltage < low_thresh:
                                self.reading_indicators[i].setStyleSheet("color: orange; font-size: 16pt;")
                            else:
                                self.reading_indicators[i].setStyleSheet("color: green; font-size: 16pt;")
                        except:
                            self.reading_indicators[i].setStyleSheet("color: gray; font-size: 16pt;")
                    else:
                        self.reading_indicators[i].setStyleSheet("color: gray; font-size: 16pt;")
                else:
                    self.reading_labels[i].setText("---")
                    self.reading_progress[i].setValue(0)
    
    def update_display(self):
        """Update plot and statistics"""
        # Update statistics
        if self.start_time and self.running:
            elapsed = time.time() - self.start_time
            rate = self.sample_count / elapsed if elapsed > 0 else 0
            self.samples_label.setText(f"Samples: {self.sample_count}")
            self.rate_label.setText(f"Rate: {rate:.1f} Hz")
        
        # Update plot
        if len(self.time_data) > 0:
            window = min(self.window_input.value(), len(self.time_data))
            time_array = np.array(list(self.time_data))[-window:]
            
            # Update lines
            if self.ch_checks[0].isChecked():
                ch0_array = np.array(list(self.ch0_data))[-window:]
                self.line0.set_data(time_array, ch0_array)
                self.line0.set_visible(True)
            else:
                self.line0.set_visible(False)
            
            if self.ch_checks[1].isChecked():
                ch1_array = np.array(list(self.ch1_data))[-window:]
                self.line1.set_data(time_array, ch1_array)
                self.line1.set_visible(True)
            else:
                self.line1.set_visible(False)
            
            if self.ch_checks[2].isChecked():
                ch2_array = np.array(list(self.ch2_data))[-window:]
                self.line2.set_data(time_array, ch2_array)
                self.line2.set_visible(True)
            else:
                self.line2.set_visible(False)
            
            if self.ch_checks[3].isChecked():
                ch3_array = np.array(list(self.ch3_data))[-window:]
                self.line3.set_data(time_array, ch3_array)
                self.line3.set_visible(True)
            else:
                self.line3.set_visible(False)
            
            # Update threshold lines
            for i in range(4):
                if self.thresh_enabled[i].isChecked():
                    try:
                        high_val = self.thresh_high[i].value()
                        low_val = self.thresh_low[i].value()
                        
                        self.threshold_high_lines[i].set_ydata([high_val, high_val])
                        self.threshold_low_lines[i].set_ydata([low_val, low_val])
                        self.threshold_high_lines[i].set_visible(True)
                        self.threshold_low_lines[i].set_visible(True)
                    except:
                        self.threshold_high_lines[i].set_visible(False)
                        self.threshold_low_lines[i].set_visible(False)
                else:
                    self.threshold_high_lines[i].set_visible(False)
                    self.threshold_low_lines[i].set_visible(False)
            
            # Update axes
            if len(time_array) > 1:
                self.ax.set_xlim(time_array[0], time_array[-1])
            
            if self.autoscale_check.isChecked():
                all_voltages = []
                if self.ch_checks[0].isChecked():
                    all_voltages.extend(list(self.ch0_data)[-window:])
                if self.ch_checks[1].isChecked():
                    all_voltages.extend(list(self.ch1_data)[-window:])
                if self.ch_checks[2].isChecked():
                    all_voltages.extend(list(self.ch2_data)[-window:])
                if self.ch_checks[3].isChecked():
                    all_voltages.extend(list(self.ch3_data)[-window:])
                
                if all_voltages:
                    y_min = min(all_voltages) - 0.1
                    y_max = max(all_voltages) + 0.1
                    self.ax.set_ylim(y_min, y_max)
            else:
                self.ax.set_ylim(self.y_min_input.value(), self.y_max_input.value())
            
            try:
                self.canvas.draw()
            except:
                pass
    
    def update_connection_status(self, connected):
        """Update connection status display"""
        self.connected = connected
        if connected:
            self.connection_label.setText("Connection: Connected")
            self.connection_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.connection_label.setText("Connection: Disconnected")
            self.connection_label.setStyleSheet("color: red; font-weight: bold;")
    
    def restore_defaults(self):
        """Restore all settings to defaults"""
        if self.running:
            QMessageBox.warning(self, "Cannot Restore", 
                              "Please stop data collection before restoring defaults.")
            return
        
        reply = QMessageBox.question(
            self, "Restore Defaults",
            "This will reset all settings to defaults:\n\n"
            "• Sample Rate: 5 Hz\n"
            "• ESP32: Simple mode, single-ended, gain ONE\n"
            "• All channels visible\n"
            "• Autoscale Y: On, Y: 0-5, Window: 100\n"
            "• No threshold alerts\n"
            "• No filters\n\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        # Apply defaults
        self.rate_input.setValue(5)
        self.mode_combo.setCurrentText('single_ended')
        self.gain_combo.setCurrentText('ONE')
        
        for i in range(4):
            self.ch_checks[i].setChecked(True)
        
        self.autoscale_check.setChecked(True)
        self.y_min_input.setValue(0.0)
        self.y_max_input.setValue(5.0)
        self.window_input.setValue(100)
        
        for i in range(4):
            self.thresh_enabled[i].setChecked(False)
            self.thresh_high[i].setValue(1.0)
            self.thresh_low[i].setValue(0.1)
        
        self.raw_radio.setChecked(True)
        for i in range(4):
            self.filter_enabled[i].setChecked(False)
            self.filter_window[i].setValue(5)
        
        self.save_settings()
        
        QMessageBox.information(self, "Defaults Restored",
                               "All settings restored to defaults and saved.")
    
    def load_settings(self):
        """Load settings from config file"""
        if not self.config_file.exists():
            return
        
        try:
            with open(self.config_file, 'r') as f:
                config = json.load(f)
            
            self.ip_input.setText(config.get('esp32_ip', '192.168.1.47'))
            self.rate_input.setValue(config.get('sample_rate', 5))
            self.osc_host_input.setText(config.get('osc_host', '127.0.0.1'))
            self.osc_port_input.setValue(config.get('osc_port', 8000))
            
            self.autoscale_check.setChecked(config.get('autoscale', True))
            self.y_min_input.setValue(config.get('y_min', 0.0))
            self.y_max_input.setValue(config.get('y_max', 5.0))
            self.window_input.setValue(config.get('plot_window', 100))
            
            show_channels = config.get('show_channels', [True, True, True, True])
            for i, show in enumerate(show_channels):
                if i < 4:
                    self.ch_checks[i].setChecked(show)
            
            self.mode_combo.setCurrentText(config.get('adc_mode', 'single_ended'))
            self.gain_combo.setCurrentText(config.get('adc_gain', 'ONE'))
            
            thresholds = config.get('thresholds', {})
            for i in range(4):
                ch_key = f'ch{i}'
                if ch_key in thresholds:
                    self.thresh_enabled[i].setChecked(thresholds[ch_key].get('enabled', False))
                    self.thresh_high[i].setValue(thresholds[ch_key].get('high', 1.0))
                    self.thresh_low[i].setValue(thresholds[ch_key].get('low', 0.1))
            
            filters = config.get('filters', {})
            use_filtered = filters.get('use_filtered_output', False)
            if use_filtered:
                self.filtered_radio.setChecked(True)
            else:
                self.raw_radio.setChecked(True)
            
            for i in range(4):
                ch_key = f'ch{i}'
                if ch_key in filters:
                    self.filter_enabled[i].setChecked(filters[ch_key].get('enabled', False))
                    self.filter_window[i].setValue(filters[ch_key].get('window', 5))
            
            print(f"Settings loaded from {self.config_file}")
            
        except Exception as e:
            print(f"Error loading settings: {e}")
    
    def save_settings(self):
        """Save settings to config file"""
        try:
            config = {
                'esp32_ip': self.ip_input.text(),
                'sample_rate': self.rate_input.value(),
                'osc_host': self.osc_host_input.text(),
                'osc_port': self.osc_port_input.value(),
                'autoscale': self.autoscale_check.isChecked(),
                'y_min': self.y_min_input.value(),
                'y_max': self.y_max_input.value(),
                'plot_window': self.window_input.value(),
                'show_channels': [check.isChecked() for check in self.ch_checks],
                'config_mode': 'simple',
                'adc_mode': self.mode_combo.currentText(),
                'adc_gain': self.gain_combo.currentText(),
                'adc_data_rate': 1600,
                'thresholds': {
                    f'ch{i}': {
                        'enabled': self.thresh_enabled[i].isChecked(),
                        'high': self.thresh_high[i].value(),
                        'low': self.thresh_low[i].value()
                    } for i in range(4)
                },
                'filters': {
                    'use_filtered_output': self.filtered_radio.isChecked(),
                    **{f'ch{i}': {
                        'enabled': self.filter_enabled[i].isChecked(),
                        'window': self.filter_window[i].value()
                    } for i in range(4)}
                }
            }
            
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=2)
            
            print(f"Settings saved to {self.config_file}")
            
        except Exception as e:
            print(f"Error saving settings: {e}")
    
    def closeEvent(self, event):
        """Handle window close"""
        if self.running:
            reply = QMessageBox.question(
                self, "Quit",
                "Data collection is running. Stop and quit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.running = False
                if self.logging_active:
                    self.stop_logging()
                time.sleep(0.5)
                self.save_settings()
                event.accept()
            else:
                event.ignore()
        else:
            self.save_settings()
            event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')  # Modern look on all platforms
    
    window = ADCClientGUI()
    window.show()
    
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
