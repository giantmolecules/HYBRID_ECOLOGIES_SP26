/*
 * ESPLog v2 - OSC/UDP Data Logger (Internal ADC)
 * 
 * Uses ESP32 internal ADC (ADC1) on pin A2 (GPIO34).
 * ADC2 pins are unavailable when WiFi is active — this sketch
 * uses only ADC1-mapped pins to avoid that conflict.
 * 
 * Pin options (all ADC1, WiFi-safe):
 *   A2 = GPIO34  ← default
 *   A3 = GPIO39
 *   A4 = GPIO36
 * 
 * ADC specs:
 *   Resolution: 12-bit (0–4095)
 *   Input range: 0–3.3V (with default attenuation)
 *   Note: ESP32 internal ADC has nonlinearity near the rails (~0–0.1V and ~3.1–3.3V).
 *         For best results keep your signal in the 0.1–3.0V range.
 * 
 * OSC Messages Sent:
 *   /adc/ch0/raw     <int>    - Raw ADC value (0–4095)
 *   /adc/ch0/voltage <float>  - Voltage reading (0.0–3.3V)
 * 
 * OSC Messages Received (port 9000):
 *   /config/pin        <int>    - ADC pin number (GPIO)
 *   /config/samplerate <int>    - Samples per second
 *   /config/serialdebug <int>   - 1=on, 0=off
 * 
 * Required Libraries:
 *   - WiFi.h      (included with ESP32)
 *   - WiFiUdp.h   (included with ESP32)
 *   - OSCMessage.h from https://github.com/CNMAT/OSC
 * 
 * Brett Ian Balogh, 2026
 * School of the Art Institute of Chicago - Hybrid Ecologies
 */

#include <WiFi.h>
#include <WiFiUdp.h>
#include <OSCMessage.h>
#include <OSCBundle.h>

// ── WiFi credentials ─────────────────────────────────────────────
const char* ssid     = "SONGBIRD";
const char* password = "quietcartoon195";

// ── OSC configuration ────────────────────────────────────────────
const char* osc_host       = "255.255.255.255";   // broadcast
const int   osc_ports[]    = {9001, 9002};         // Python=9001, Max=9002
const int   num_ports      = 2;
const int   osc_receive_port = 9000;              // incoming config port

// ── ADC configuration ────────────────────────────────────────────
// ADC1 pins only — safe to use with WiFi active
// A2=GPIO34 (default), A3=GPIO39, A4=GPIO36
int adcPin = A2;  // GPIO34

// 12-bit ADC, 3.3V reference
const int   ADC_BITS       = 12;
const int   ADC_MAX        = (1 << ADC_BITS) - 1;  // 4095
const float ADC_VREF       = 3.3f;

// ── Sampling configuration ───────────────────────────────────────
int           sampleRate       = 10;
unsigned long sampleIntervalMs = 1000 / sampleRate;
unsigned long lastSampleTime   = 0;
unsigned long sampleCounter    = 0;

// ── Serial debug ─────────────────────────────────────────────────
bool serialDebug = false;

// ── Current reading ──────────────────────────────────────────────
struct {
  int16_t raw;
  float   voltage;
} currentReading;

WiFiUDP udp;

// ─────────────────────────────────────────────────────────────────

void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println("ESPLog v2 - OSC/UDP Data Logger (Internal ADC)");
  Serial.println("===============================================");

  // Configure ADC
  analogReadResolution(ADC_BITS);
  analogSetAttenuation(ADC_11db);  // full 0–3.3V range
  pinMode(adcPin, INPUT);

  Serial.print("ADC pin: GPIO");
  Serial.println(adcPin);
  Serial.print("Resolution: ");
  Serial.print(ADC_BITS);
  Serial.println("-bit (0–4095)");
  Serial.println("Attenuation: 11dB (0–3.3V range)");

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

  udp.begin(osc_receive_port);
  Serial.print("Listening for config on port: ");
  Serial.println(osc_receive_port);
}

// ── OSC config handlers ──────────────────────────────────────────

void handlePinConfig(OSCMessage &msg) {
  int newPin = msg.getInt(0);
  // Only allow ADC1 pins (WiFi-safe): 32,33,34,35,36,37,38,39
  const int adc1pins[] = {32, 33, 34, 35, 36, 37, 38, 39};
  bool valid = false;
  for (int p : adc1pins) {
    if (newPin == p) { valid = true; break; }
  }
  if (valid) {
    adcPin = newPin;
    pinMode(adcPin, INPUT);
    Serial.print("Config: ADC pin set to GPIO");
    Serial.println(adcPin);
  } else {
    Serial.print("Config: Rejected pin GPIO");
    Serial.print(newPin);
    Serial.println(" — not an ADC1 pin");
  }
}

void handleSampleRateConfig(OSCMessage &msg) {
  int newRate = msg.getInt(0);
  if (newRate > 0 && newRate <= 1000) {
    sampleRate       = newRate;
    sampleIntervalMs = 1000 / sampleRate;
    Serial.print("Config: Sample rate set to ");
    Serial.print(sampleRate);
    Serial.println(" Hz");
  }
}

void handleSerialDebugConfig(OSCMessage &msg) {
  int debugState = msg.getInt(0);
  serialDebug = (debugState == 1);
  Serial.print("Config: Serial debug ");
  Serial.println(serialDebug ? "ENABLED" : "DISABLED");
}

// ── Main loop ────────────────────────────────────────────────────

void loop() {
  // Check for incoming OSC config messages
  int packetSize = udp.parsePacket();
  if (packetSize > 0) {
    OSCMessage msgIn;
    while (packetSize--) {
      msgIn.fill(udp.read());
    }
    if (!msgIn.hasError()) {
      msgIn.dispatch("/config/pin",         handlePinConfig);
      msgIn.dispatch("/config/samplerate",  handleSampleRateConfig);
      msgIn.dispatch("/config/serialdebug", handleSerialDebugConfig);
    }
  }

  // Sample ADC at regular intervals
  unsigned long currentTime = millis();
  if (currentTime - lastSampleTime >= sampleIntervalMs) {
    lastSampleTime = currentTime;
    sampleCounter++;
    readADC();
    sendOSC();
  }
}

// ── ADC read ─────────────────────────────────────────────────────

void readADC() {
  currentReading.raw     = (int16_t)analogRead(adcPin);
  currentReading.voltage = currentReading.raw * (ADC_VREF / ADC_MAX);
}

// ── OSC send ─────────────────────────────────────────────────────

void sendOSC() {
  for (int i = 0; i < num_ports; i++) {
    // Raw value + sample counter
    OSCMessage msgRaw("/adc/ch0/raw");
    msgRaw.add((int32_t)currentReading.raw);
    msgRaw.add((int32_t)sampleCounter);
    udp.beginPacket(osc_host, osc_ports[i]);
    msgRaw.send(udp);
    udp.endPacket();
    msgRaw.empty();

    // Voltage + sample counter
    OSCMessage msgVoltage("/adc/ch0/voltage");
    msgVoltage.add(currentReading.voltage);
    msgVoltage.add((int32_t)sampleCounter);
    udp.beginPacket(osc_host, osc_ports[i]);
    msgVoltage.send(udp);
    udp.endPacket();
    msgVoltage.empty();
  }

  if (serialDebug) {
    Serial.print("Sample ");
    Serial.print(sampleCounter);
    Serial.print(": Pin=GPIO");
    Serial.print(adcPin);
    Serial.print(", Raw=");
    Serial.print(currentReading.raw);
    Serial.print(", Voltage=");
    Serial.print(currentReading.voltage, 3);
    Serial.println("V");
  }
}
