/*
 * ESPLog v2 - OSC/UDP Data Logger
 * 
 * Sends ADS1015 ADC data directly as OSC messages over UDP
 * Single channel (A0) operation with configurable gain and mode
 * 
 * OSC Messages Sent:
 * /adc/ch0/raw <int>        - Raw ADC value
 * /adc/ch0/voltage <float>  - Voltage reading
 * /config/gain <string>     - Current gain setting
 * /config/mode <string>     - Current mode (single/differential)
 * 
 * Required Libraries:
 * - Adafruit_ADS1X15 (install via Library Manager)
 * - WiFi.h (included with ESP32)
 * - WiFiUdp.h (included with ESP32)
 * - OSCMessage.h from https://github.com/CNMAT/OSC (install via Library Manager, search "OSC")
 * 
 * Brett Ian Balogh, 2026
 * School of the Art Institute of Chicago - Hybrid Ecologies
 */

#include <WiFi.h>
#include <WiFiUdp.h>
#include <OSCMessage.h>
#include <OSCBundle.h>
#include <Wire.h>
#include <Adafruit_ADS1X15.h>

// WiFi credentials - UPDATE THESE
const char* ssid = "YOUR_WIFI_SSID";
const char* password = "YOUR_WIFI_PASSWORD";

// OSC configuration - Multiple receivers
const char* osc_host = "255.255.255.255";  // Broadcast to all
const int osc_ports[] = {8000, 8001};  // Python=8000, Max=8001
const int num_ports = 2;
const int osc_receive_port = 9000;  // Port to receive config from Python

// Sampling configuration
int sampleRate = 10;  // Samples per second
unsigned long sampleIntervalMs = 1000 / sampleRate;
unsigned long lastSampleTime = 0;

// Sample counter for precise timing
unsigned long sampleCounter = 0;

// ADC Configuration
Adafruit_ADS1015 ads;
WiFiUDP udp;

enum ChannelMode {
  SINGLE_ENDED,
  DIFFERENTIAL
};

struct ADCConfig {
  ChannelMode mode;
  adsGain_t gain;
} config;

// Current reading
struct {
  int16_t raw;
  float voltage;
} currentReading;

void setup() {
  Serial.begin(115200);
  delay(1000);
  
  Serial.println("ESPLog v2 - OSC/UDP Data Logger");
  Serial.println("================================");
  
  // Initialize I2C
  Wire.begin();
  
  // Initialize ADS1015
  if (!ads.begin()) {
    Serial.println("ERROR: Failed to initialize ADS1015!");
    while (1);
  }
  
  // Set default configuration
  config.mode = SINGLE_ENDED;
  config.gain = GAIN_ONE;  // ±4.096V range
  applyADCConfig();
  
  Serial.println("ADS1015 initialized");
  
  // Connect to WiFi
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);
  
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();
  
  Serial.println("WiFi connected!");
  Serial.print("IP address: ");
  Serial.println(WiFi.localIP());
  Serial.print("Sending OSC to: ");
  Serial.print(osc_host);
  Serial.print(" on ports: ");
  for (int i = 0; i < num_ports; i++) {
    Serial.print(osc_ports[i]);
    if (i < num_ports - 1) Serial.print(", ");
  }
  Serial.println();
  Serial.println();
  Serial.println("Starting data transmission...");
  
  // Begin UDP for both sending and receiving
  udp.begin(osc_receive_port);
  
  Serial.print("Listening for config on port: ");
  Serial.println(osc_receive_port);
}

void handleModeConfig(OSCMessage &msg) {
  char modeStr[16];
  msg.getString(0, modeStr, sizeof(modeStr));
  
  if (strcmp(modeStr, "single") == 0) {
    config.mode = SINGLE_ENDED;
    Serial.println("Config: Mode set to SINGLE_ENDED");
  } else if (strcmp(modeStr, "differential") == 0) {
    config.mode = DIFFERENTIAL;
    Serial.println("Config: Mode set to DIFFERENTIAL");
  }
}

void handleGainConfig(OSCMessage &msg) {
  char gainStr[16];
  msg.getString(0, gainStr, sizeof(gainStr));
  
  if (strcmp(gainStr, "TWOTHIRDS") == 0) config.gain = GAIN_TWOTHIRDS;
  else if (strcmp(gainStr, "ONE") == 0) config.gain = GAIN_ONE;
  else if (strcmp(gainStr, "TWO") == 0) config.gain = GAIN_TWO;
  else if (strcmp(gainStr, "FOUR") == 0) config.gain = GAIN_FOUR;
  else if (strcmp(gainStr, "EIGHT") == 0) config.gain = GAIN_EIGHT;
  else if (strcmp(gainStr, "SIXTEEN") == 0) config.gain = GAIN_SIXTEEN;
  
  applyADCConfig();
  Serial.print("Config: Gain set to ");
  Serial.println(gainStr);
}

void handleSampleRateConfig(OSCMessage &msg) {
  int newRate = msg.getInt(0);
  if (newRate > 0 && newRate <= 1000) {
    sampleRate = newRate;
    sampleIntervalMs = 1000 / sampleRate;
    Serial.print("Config: Sample rate set to ");
    Serial.print(sampleRate);
    Serial.println(" Hz");
  }
}

void loop() {
  // Check for incoming OSC config messages
  int packetSize = udp.parsePacket();
  if (packetSize > 0) {
    OSCMessage msgIn;
    while (packetSize--) {
      msgIn.fill(udp.read());
    }
    if (!msgIn.hasError()) {
      msgIn.dispatch("/config/mode", handleModeConfig);
      msgIn.dispatch("/config/gain", handleGainConfig);
      msgIn.dispatch("/config/samplerate", handleSampleRateConfig);
    }
  }
  
  // Sample ADC at regular intervals
  unsigned long currentTime = millis();
  if (currentTime - lastSampleTime >= sampleIntervalMs) {
    lastSampleTime = currentTime;
    
    // Increment sample counter
    sampleCounter++;
    
    readADC();
    sendOSC();
  }
}

void applyADCConfig() {
  // Set gain
  ads.setGain(config.gain);
  
  Serial.println("ADC Configuration:");
  Serial.print("  Mode: ");
  Serial.println(config.mode == SINGLE_ENDED ? "Single-Ended" : "Differential");
  Serial.print("  Gain: ");
  Serial.println(gainToString(config.gain));
}

void readADC() {
  if (config.mode == SINGLE_ENDED) {
    // Read single-ended A0
    currentReading.raw = ads.readADC_SingleEnded(0);
  } else {
    // Read differential A0-A1
    currentReading.raw = ads.readADC_Differential_0_1();
  }
  
  currentReading.voltage = ads.computeVolts(currentReading.raw);
}

void sendOSC() {
  // Send to all configured ports
  for (int i = 0; i < num_ports; i++) {
    // Send raw value with sample counter
    OSCMessage msgRaw("/adc/ch0/raw");
    msgRaw.add((int32_t)currentReading.raw);
    msgRaw.add((int32_t)sampleCounter);
    udp.beginPacket(osc_host, osc_ports[i]);
    msgRaw.send(udp);
    udp.endPacket();
    msgRaw.empty();
    
    // Send voltage with sample counter
    OSCMessage msgVoltage("/adc/ch0/voltage");
    msgVoltage.add(currentReading.voltage);
    msgVoltage.add((int32_t)sampleCounter);
    udp.beginPacket(osc_host, osc_ports[i]);
    msgVoltage.send(udp);
    udp.endPacket();
    msgVoltage.empty();
  }
}

String gainToString(adsGain_t gain) {
  switch(gain) {
    case GAIN_TWOTHIRDS: return "TWOTHIRDS";
    case GAIN_ONE:       return "ONE";
    case GAIN_TWO:       return "TWO";
    case GAIN_FOUR:      return "FOUR";
    case GAIN_EIGHT:     return "EIGHT";
    case GAIN_SIXTEEN:   return "SIXTEEN";
    default:             return "ONE";
  }
}
