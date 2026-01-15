# ESPLog - Hybrid Ecologies Data Logger

**Spring 2026 | School of the Art Institute of Chicago**  
*Serial + WiFi ESP32 Data Logger and OSC Streamer*

Brett Ian Balogh, 2026

---

## Overview

ESPLog is a dual-mode (WiFi + Serial) data acquisition system for bioart and physical computing projects. It captures analog sensor data from plants, fungi, and other living systems using an ESP32 microcontroller with an ADS1015 ADC, then streams the data via OSC and logs it to CSV files.

**Key Features:**
- 🌐 **Dual connectivity**: WiFi HTTP polling or USB Serial streaming
- 📊 **Real-time plotting**: Live visualization of 4 analog channels
- 🎵 **OSC streaming**: Direct integration with Max/MSP, PureData, TouchDesigner
- 💾 **CSV logging**: Timestamped data recording with auto-indexing
- 🔧 **Configurable ADC**: Single-ended or differential modes, adjustable gain
- 🎛️ **Threshold alerts**: Visual and OSC notifications for voltage thresholds
- 🔀 **Low-pass filters**: Built-in signal smoothing with adjustable window
- 🖥️ **Native GUI**: PyQt6 interface with proper macOS integration

---

## Hardware Requirements

### Required Components
- **ESP32 Feather V2** (Adafruit or compatible)
- **ADS1015 12-bit ADC** (I2C breakout board)
- **USB cable** (for serial communication and power)
- **Electrodes** (Ag/AgCl recommended for bioelectrical signals)
- **Jumper wires** for connections

### Optional
- WiFi network (for wireless operation)
- External power supply (if not using USB)

### Wiring Diagram

#### I2C Connection (ESP32 to ADS1015)
```
ESP32 Feather V2          ADS1015
-----------------         --------
3.3V          ─────────►  VDD
GND           ─────────►  GND
SDA (GPIO 23) ─────────►  SDA
SCL (GPIO 22) ─────────►  SCL
                          ADDR ──► GND (for address 0x48)
```

#### Sensor Connections (ADS1015)
```
Single-Ended Mode:
  A0 ──► Sensor Channel 0
  A1 ──► Sensor Channel 1
  A2 ──► Sensor Channel 2
  A3 ──► Sensor Channel 3
  GND ──► Common ground for all sensors

Differential Mode:
  A0-A1 ──► Differential pair 1
  A2-A3 ──► Differential pair 2
```

---

## Software Installation

### 1. Arduino Setup

#### Install Arduino IDE
Download from: https://www.arduino.cc/en/software

#### Install ESP32 Board Support
1. Open Arduino IDE
2. Go to **File → Preferences**
3. Add to "Additional Board Manager URLs":
   ```
   https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
   ```
4. Go to **Tools → Board → Boards Manager**
5. Search for "ESP32" and install "esp32 by Espressif Systems"

#### Install Required Libraries
Go to **Sketch → Include Library → Manage Libraries** and install:
- `Adafruit ADS1X15` (for ADC communication)
- `ArduinoJson` (for JSON formatting)

**Built-in libraries** (no installation needed):
- `WiFi.h`
- `WebServer.h`
- `Wire.h`

### 2. Python GUI Setup

#### Install Python
Download Python 3.9+ from: https://www.python.org/downloads/

**macOS Installation:**
1. Download the macOS installer
2. Run the installer
3. Make sure "Install pip" is checked
4. Add Python to PATH when prompted

#### Verify Installation
```bash
python3 --version
pip3 --version
```

#### Install Python Dependencies
```bash
pip3 install PyQt6 requests python-osc matplotlib pyserial
```

**What each package does:**
- `PyQt6` - GUI framework
- `requests` - WiFi HTTP communication
- `python-osc` - OSC protocol for Max/MSP/PureData
- `matplotlib` - Real-time plotting
- `pyserial` - USB Serial communication

---

## Quick Start

### Step 1: Upload Arduino Code

1. Open `esplog.ino` in Arduino IDE
2. **Configure WiFi** (lines 26-27):
   ```cpp
   const char* ssid = "YOUR_WIFI_SSID";
   const char* password = "YOUR_WIFI_PASSWORD";
   ```
3. Select **Tools → Board → ESP32 Feather V2**
4. Select **Tools → Port** (choose your ESP32's serial port)
5. Click **Upload** ✓

### Step 2: Find ESP32 IP Address

1. Open **Tools → Serial Monitor** (115200 baud)
2. Reset ESP32 (press RST button)
3. Note the IP address displayed:
   ```
   ESPLog - Hybrid Ecologies Data Logger Starting...
   WiFi connected!
   IP address: 192.168.1.47
   ```

### Step 3: Run Python GUI

**WiFi Mode:**
```bash
python3 esplog.py
```
1. Select **WiFi** radio button
2. Enter ESP32 IP address
3. Set sample rate (5 Hz recommended)
4. Click **Start**

**Serial Mode:**
```bash
python3 esplog.py
```
1. **Close Arduino Serial Monitor** (important!)
2. Select **Serial** radio button
3. Click refresh button (↻) to scan ports
4. Select ESP32's serial port
5. Set baud rate to **115200**
6. Click **Start**

---

## Features Guide

### Connection Modes

#### WiFi Mode
- HTTP polling from ESP32 web server
- Sample rate: 1-30 Hz typical
- No cable required after setup
- ESP32 and computer must be on same network

#### Serial Mode
- Direct USB communication
- Sample rate: 1-200 Hz
- More reliable for long recordings
- Works without WiFi

### Real-Time Plotting
- View up to 4 channels simultaneously
- Toggle channel visibility
- Autoscale or fixed Y-axis range
- Adjustable time window (10-10,000 samples)
- Matplotlib navigation toolbar (zoom, pan, save)

### CSV Logging
1. Click **Start Logging**
2. Choose filename and location
3. Data saved with timestamps
4. Auto-indexing prevents overwriting (`file.csv`, `file_001.csv`, etc.)
5. Row counter shows progress
6. File format:
   ```csv
   timestamp_local,timestamp_esp32,ch0_raw,ch0_voltage,ch1_raw,ch1_voltage,...
   ```

### OSC Streaming
- Real-time data to Max/MSP, PureData, TouchDesigner
- Default port: 8000
- Configurable host and port

**OSC Messages:**
```
/adc/ch0/raw <int>           # Raw ADC value (0-2047)
/adc/ch0/voltage <float>     # Voltage (V)
/adc/ch1/raw <int>
/adc/ch1/voltage <float>
... (ch2, ch3)

# Threshold alerts (when enabled)
/adc/alert/ch0/high <float> <float>    # Current voltage, threshold
/adc/alert/ch0/low <float> <float>
/adc/alert/ch0/normal <float>
```

**Max/MSP Example:**
```
[udpreceive 8000]
|
[OSC-route /adc]
|
[route ch0 ch1 ch2 ch3]
```

### Threshold Alerts
1. Enable per-channel thresholds
2. Set high and low voltage limits
3. Visual indicators:
   - 🔴 Red: Above high threshold
   - 🟠 Orange: Below low threshold
   - 🟢 Green: Normal range
4. OSC alerts sent on state changes

### Low-Pass Filters
- Moving average filter
- Configurable window (2-50 samples)
- Toggle between raw and filtered output
- Filters apply to plot, CSV, and OSC

### ESP32 Configuration
- **Mode**: Single-ended (4 channels) or Differential (2 pairs)
- **Gain**: TWOTHIRDS, ONE, TWO, FOUR, EIGHT, SIXTEEN
  - Higher gain = smaller voltage range, more resolution
  - Gain ONE: ±4.096V range (default)
- **Data Rate**: 128-3300 SPS (default: 1600 SPS)

### Restore Defaults
Orange button resets all settings:
- Sample rate: 5 Hz
- ESP32: Simple mode, single-ended, gain ONE
- All channels visible
- Autoscale: On
- Y-axis: 0-5V
- Window: 100 samples
- No thresholds, no filters

---

## Troubleshooting

### ESP32 Issues

**Problem:** "Failed to initialize ADS1015!"
- Check I2C wiring (SDA, SCL, VDD, GND)
- Verify ADS1015 ADDR pin connected to GND
- Try different I2C address in code

**Problem:** Can't find ESP32 IP address
- Check WiFi credentials in code
- Verify ESP32 and computer on same network
- Open Serial Monitor to see connection status

**Problem:** HTTP timeout errors
- ESP32 may have different IP (check Serial Monitor)
- Firewall blocking port 80
- ESP32 not powered or crashed (try reset)

### Python GUI Issues

**Problem:** "ModuleNotFoundError: No module named 'PyQt6'"
```bash
pip3 install PyQt6
```

**Problem:** Serial port not found
- Close Arduino Serial Monitor
- Unplug and replug USB cable
- Check port permissions (macOS/Linux)
- Try different USB cable

**Problem:** "Permission denied" on serial port (macOS/Linux)
```bash
sudo chmod 666 /dev/cu.usbserial*  # macOS
sudo chmod 666 /dev/ttyUSB*        # Linux
```

**Problem:** GUI crashes or doesn't show data
- Enable **Debug Mode** checkbox to see errors
- Check terminal output for error messages
- Verify ESP32 is actually sending data (check Serial Monitor)

**Problem:** Plot not updating
- Check sample rate setting
- Verify connection status indicator (green = connected)
- Try stopping and restarting

### Data Quality Issues

**Problem:** Noisy readings
- Enable low-pass filter (window: 10-20 samples)
- Check electrode connections
- Add pull-down resistors (10kΩ) to floating inputs
- Use shielded cables for long connections
- Keep electrodes away from AC power sources

**Problem:** Floating inputs showing ~0.6V
- This is normal for unconnected ADC inputs
- Solution 1: Connect unused inputs to GND
- Solution 2: Add 10kΩ pull-down resistors
- Solution 3: Ignore unused channels in GUI

**Problem:** Readings stuck at 0V or max voltage
- Check sensor connections
- Verify voltage is within ADC range (±4.096V for gain ONE)
- Try different gain setting
- Check for short circuits

---

## Advanced Usage

### Custom Gain Settings
Different sensors require different gain values:

| Gain        | Voltage Range | Use Case                           |
|-------------|---------------|------------------------------------|
| TWOTHIRDS   | ±6.144V       | High-voltage sensors (max 3.3V)   |
| ONE         | ±4.096V       | General purpose (default)          |
| TWO         | ±2.048V       | Plant bioelectric signals          |
| FOUR        | ±1.024V       | Sensitive biopotentials            |
| EIGHT       | ±0.512V       | Very sensitive signals             |
| SIXTEEN     | ±0.256V       | Ultra-sensitive (rare)             |

### Differential Mode
Use for measuring voltage *difference* between two points:
- Reduces common-mode noise
- Better for grounded systems
- Pair 1: A0-A1
- Pair 2: A2-A3

### Filter Design
Moving average response time:
```
Response time ≈ (window_size / sample_rate) seconds

Examples:
- Window=5, Rate=10Hz → 0.5s response
- Window=20, Rate=5Hz → 4s response
```

### OSC Custom Port
If port 8000 conflicts with another application:
1. Change port in GUI
2. Update your Max/MSP/PureData patch to match

### Long-Term Recording
For recordings over 1 hour:
- Use Serial mode (more stable)
- Set sample rate to 5 Hz or lower
- Monitor disk space (1 hour @ 5Hz ≈ 1-2 MB)
- File auto-flushes every 100 samples

---

## Educational Context

This tool was developed for **Hybrid Ecologies (Spring 2026)** at the School of the Art Institute of Chicago, a course exploring the intersection of art, electronics, and living systems.

**Typical Use Cases:**
- Plant bioelectrical signal monitoring
- Fungal network activity sensing
- Slime mold behavior studies
- Environmental sensor integration
- Biofeedback art installations

**Learning Objectives:**
- Understanding analog-to-digital conversion
- Real-time data acquisition and visualization
- OSC protocol for creative coding
- Serial vs. network communication
- Signal processing basics (filtering, thresholds)

---

## Project Structure

```
HYBRID_ECOLOGIES_SP26/
├── esplog.py              # Python GUI application
├── esplog.ino             # Arduino ESP32 firmware
├── README.md              # This file
└── examples/              # (optional) Example projects
    ├── max_patches/       # Max/MSP examples
    ├── pd_patches/        # PureData examples
    └── sample_data/       # Example CSV files
```

---

## File Formats

### CSV Output Format
```csv
timestamp_local,timestamp_esp32,ch0_raw,ch0_voltage,ch1_raw,ch1_voltage,ch2_raw,ch2_voltage,ch3_raw,ch3_voltage
2026-01-15T14:23:45.123456,12345,1234,2.456,987,1.234,1500,2.987,2000,3.987
```

**Columns:**
- `timestamp_local`: ISO 8601 format (computer time)
- `timestamp_esp32`: Milliseconds since ESP32 boot
- `chN_raw`: Raw ADC value (0-2047 for 12-bit)
- `chN_voltage`: Converted voltage (V)

### JSON Format (HTTP & Serial)
```json
{
  "timestamp": 12345,
  "channels": {
    "0": {
      "raw": 1234,
      "voltage": 2.456,
      "mode": "single",
      "channel": 0
    },
    "1": { ... },
    "2": { ... },
    "3": { ... }
  }
}
```

---

## Credits & License

**Developed by:** Brett Ian Balogh  
**Institution:** School of the Art Institute of Chicago  
**Course:** Hybrid Ecologies, Spring 2026

**Built with:**
- [PyQt6](https://www.riverbankcomputing.com/software/pyqt/) - GUI framework
- [Adafruit ADS1X15 Library](https://github.com/adafruit/Adafruit_ADS1X15) - ADC driver
- [ArduinoJson](https://arduinojson.org/) - JSON serialization
- [python-osc](https://pypi.org/project/python-osc/) - OSC protocol

**License:** MIT (or specify your preferred license)

---

## Support & Contact

**Issues:** Please report bugs or feature requests via GitHub Issues

**Documentation:** Additional tutorials and examples available in course materials

**Community:** SAIC Hybrid Ecologies Spring 2026

---

## Changelog

### v1.0 (January 2026)
- Initial release
- WiFi and Serial dual-mode operation
- Real-time plotting and CSV logging
- OSC streaming support
- Threshold alerts and low-pass filters
- PyQt6 native GUI with macOS support

---

**Happy data logging! 🌱📊🎨**
