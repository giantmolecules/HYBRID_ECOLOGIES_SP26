/*
 * ESPLog v2 - OSC Test Sender (No ADS1015)
 * 
 * Sends random test data as OSC messages over UDP
 * Use this to test OSC receivers without hardware
 * 
 * OSC Messages Sent:
 * /adc/ch0/raw <int>        - Random raw value (0-2047)
 * /adc/ch0/voltage <float>  - Random voltage (0-5V)
 * 
 * Required Libraries:
 * - WiFi.h (included with ESP32)
 * - WiFiUdp.h (included with ESP32)
 * - OSCMessage.h from https://github.com/CNMAT/OSC (install "OSC" via Library Manager)
 * 
 * Brett Ian Balogh, 2026
 * School of the Art Institute of Chicago - Hybrid Ecologies
 */

#include <WiFi.h>
#include <WiFiUdp.h>
#include <OSCMessage.h>

// WiFi credentials - UPDATE THESE
const char* ssid = "SONGBIRD";
const char* password = "quietcartoon195";

// OSC configuration - Multiple receivers
const char* osc_host = "255.255.255.255";  // Broadcast to all
const int osc_ports[] = {8000, 8001};  // Python=8000, Max=8001
const int num_ports = 2;

// Sampling configuration
int sampleRate = 10;  // Samples per second
unsigned long sampleIntervalMs = 1000 / sampleRate;
unsigned long lastSampleTime = 0;

// Sample counter for precise timing
unsigned long sampleCounter = 0;

// WiFi UDP
WiFiUDP udp;

// Test signal parameters
float baseVoltage = 2.5;  // Center voltage
float amplitude = 1.0;    // Amplitude of variation
float frequency = 0.1;    // Frequency in Hz
unsigned long startTime = 0;

void setup() {
  Serial.begin(115200);
  delay(1000);
  
  Serial.println("ESPLog v2 - OSC Test Sender");
  Serial.println("============================");
  Serial.println("Sending RANDOM TEST DATA (no ADS1015)");
  Serial.println();
  
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
  Serial.println("Starting test data transmission...");
  Serial.println("(Random values + slow sine wave)");
  Serial.println();
  
  // Begin UDP
  udp.begin(osc_ports[0]);
  
  startTime = millis();
}

void loop() {
  // Sample at regular intervals
  unsigned long currentTime = millis();
  if (currentTime - lastSampleTime >= sampleIntervalMs) {
    lastSampleTime = currentTime;
    
    // Increment sample counter
    sampleCounter++;
    
    // Generate test data
    float elapsedSec = (currentTime - startTime) / 1000.0;
    
    // Sine wave + random noise
    float sineWave = sin(2.0 * PI * frequency * elapsedSec);
    float randomNoise = (random(-100, 100) / 100.0) * 0.2;  // ±0.2V noise
    float voltage = baseVoltage + (amplitude * sineWave) + randomNoise;
    
    // Clamp to 0-5V range
    voltage = constrain(voltage, 0.0, 5.0);
    
    // Convert to fake raw value (simulate 12-bit ADC)
    int16_t rawValue = (int16_t)((voltage / 5.0) * 2047);
    
    // Print to serial
    Serial.print("Sending: ");
    Serial.print(voltage, 3);
    Serial.print(" V  (raw: ");
    Serial.print(rawValue);
    Serial.println(")");
    
    // Send OSC messages
    sendOSC(rawValue, voltage);
  }
}

void sendOSC(int16_t raw, float voltage) {
  // Send to all configured ports
  for (int i = 0; i < num_ports; i++) {
    // Send raw value with sample counter
    OSCMessage msgRaw("/adc/ch0/raw");
    msgRaw.add((int32_t)raw);
    msgRaw.add((int32_t)sampleCounter);
    udp.beginPacket(osc_host, osc_ports[i]);
    msgRaw.send(udp);
    udp.endPacket();
    msgRaw.empty();
    
    // Send voltage with sample counter
    OSCMessage msgVoltage("/adc/ch0/voltage");
    msgVoltage.add(voltage);
    msgVoltage.add((int32_t)sampleCounter);
    udp.beginPacket(osc_host, osc_ports[i]);
    msgVoltage.send(udp);
    udp.endPacket();
    msgVoltage.empty();
  }
}
