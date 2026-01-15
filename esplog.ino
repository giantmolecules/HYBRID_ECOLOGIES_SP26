/*
 * ESPLog - Hybrid Ecologies ESP32 Data Logger
 * 
 * Reads data from ADS1015 ADC via I2C and streams over:
 * - WiFi as JSON via HTTP on port 80
 * - Serial as JSON (115200 baud) - one JSON object per line
 * 
 * Features:
 * - Single-ended and differential modes
 * - Configurable gain and data rate
 * - HTTP configuration endpoints
 * - Serial JSON output for non-WiFi operation
 * 
 * Required Libraries:
 * - Adafruit_ADS1X15 (install via Library Manager)
 * - WiFi.h (included with ESP32 board package)
 * - WebServer.h (included with ESP32 board package)
 * - ArduinoJson (install via Library Manager)
 * 
 * Brett Ian Balogh, 2026
 * School of the Art Institute of Chicago
 */

#include <WiFi.h>
#include <WebServer.h>
#include <Wire.h>
#include <Adafruit_ADS1X15.h>
#include <ArduinoJson.h>

// WiFi credentials - UPDATE THESE WITH YOUR NETWORK
const char* ssid = "YOUR_WIFI_SSID";
const char* password = "YOUR_WIFI_PASSWORD";

// Serial output configuration
bool enableSerialOutput = true;  // Set to false to disable serial JSON output

// Create ADS1015 object
Adafruit_ADS1015 ads;

// Create web server on port 80
WebServer server(80);

// Sampling configuration
int currentSampleRate = 100;  // Samples per second
unsigned long sampleIntervalMs = 1000 / currentSampleRate;
unsigned long lastSampleTime = 0;

// ADC Configuration
enum ChannelMode {
  SINGLE_ENDED,
  DIFFERENTIAL
};

struct ChannelConfig {
  ChannelMode mode;
  int channel;  // For single-ended: 0-3, For differential: 0=0-1, 1=2-3
  adsGain_t gain;
};

// Current configuration (default: 4 single-ended channels)
ChannelConfig channelConfigs[4] = {
  {SINGLE_ENDED, 0, GAIN_ONE},
  {SINGLE_ENDED, 1, GAIN_ONE},
  {SINGLE_ENDED, 2, GAIN_ONE},
  {SINGLE_ENDED, 3, GAIN_ONE}
};

int activeChannels = 4;  // Number of active channels
int dataRate = 1600;     // ADS1015 data rate

// Data storage
struct SensorData {
  unsigned long timestamp;
  int16_t adc[4];
  float voltage[4];
  bool active[4];
} currentData;

void setup() {
  Serial.begin(115200);
  delay(1000);
  
  Serial.println("ESPLog - Hybrid Ecologies Data Logger Starting...");
  
  // Initialize I2C
  Wire.begin();
  
  // Initialize ADS1015
  if (!ads.begin()) {
    Serial.println("Failed to initialize ADS1015!");
    while (1);
  }
  
  // Apply default configuration
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
  Serial.print("Access sensor data at: http://");
  Serial.print(WiFi.localIP());
  Serial.println("/data");
  
  // Setup HTTP server routes
  server.on("/", handleRoot);
  server.on("/data", HTTP_GET, handleData);
  server.on("/config", HTTP_GET, handleGetConfig);
  server.on("/config", HTTP_POST, handleSetConfig);
  server.on("/config", HTTP_OPTIONS, handleConfigOptions);  // CORS preflight
  server.on("/stream", handleStream);
  server.onNotFound(handleNotFound);
  
  // Start server
  server.begin();
  Serial.println("HTTP server started");
  Serial.println("Configuration endpoints: GET/POST /config");
  
  if (enableSerialOutput) {
    Serial.println("Serial JSON output enabled (115200 baud)");
    Serial.println("---BEGIN JSON DATA---");
  }
}

void loop() {
  // Handle HTTP requests
  server.handleClient();
  
  // Sample ADC at regular intervals
  unsigned long currentTime = millis();
  if (currentTime - lastSampleTime >= sampleIntervalMs) {
    lastSampleTime = currentTime;
    readADC();
  }
}

void applyADCConfig() {
  // Set data rate
  switch(dataRate) {
    case 128:  ads.setDataRate(RATE_ADS1015_128SPS); break;
    case 250:  ads.setDataRate(RATE_ADS1015_250SPS); break;
    case 490:  ads.setDataRate(RATE_ADS1015_490SPS); break;
    case 920:  ads.setDataRate(RATE_ADS1015_920SPS); break;
    case 1600: ads.setDataRate(RATE_ADS1015_1600SPS); break;
    case 2400: ads.setDataRate(RATE_ADS1015_2400SPS); break;
    case 3300: ads.setDataRate(RATE_ADS1015_3300SPS); break;
    default:   ads.setDataRate(RATE_ADS1015_1600SPS); break;
  }
  
  // Set gain once here (use gain from first active channel)
  // This prevents repeated setGain calls that slow down reading
  ads.setGain(channelConfigs[0].gain);
  
  // Initialize all channels as inactive
  for (int i = 0; i < 4; i++) {
    currentData.active[i] = false;
  }
  
  // Mark active channels based on configuration
  for (int i = 0; i < activeChannels; i++) {
    currentData.active[i] = true;
  }
  
  Serial.println("ADC configuration applied");
  Serial.print("Active channels: ");
  Serial.println(activeChannels);
  Serial.print("Data rate: ");
  Serial.println(dataRate);
  Serial.print("Gain: ");
  Serial.println(gainToString(channelConfigs[0].gain));
}

void readADC() {
  currentData.timestamp = millis();
  
  for (int i = 0; i < activeChannels; i++) {
    if (channelConfigs[i].mode == SINGLE_ENDED) {
      // Read single-ended (gain already set in applyADCConfig)
      currentData.adc[i] = ads.readADC_SingleEnded(channelConfigs[i].channel);
      currentData.voltage[i] = ads.computeVolts(currentData.adc[i]);
      
    } else {  // DIFFERENTIAL
      // Read differential (gain already set in applyADCConfig)
      if (channelConfigs[i].channel == 0) {
        // Differential 0-1
        currentData.adc[i] = ads.readADC_Differential_0_1();
      } else {
        // Differential 2-3
        currentData.adc[i] = ads.readADC_Differential_2_3();
      }
      currentData.voltage[i] = ads.computeVolts(currentData.adc[i]);
    }
  }
  
  // Output JSON to serial if enabled
  if (enableSerialOutput) {
    outputSerialJSON();
  }
}

void outputSerialJSON() {
  // Build JSON output identical to HTTP /data endpoint
  StaticJsonDocument<512> doc;
  doc["timestamp"] = currentData.timestamp;
  
  JsonObject channels = doc.createNestedObject("channels");
  
  for (int i = 0; i < 4; i++) {
    if (currentData.active[i]) {
      JsonObject ch = channels.createNestedObject(String(i));
      ch["raw"] = currentData.adc[i];
      ch["voltage"] = currentData.voltage[i];
      
      // Add mode info
      if (channelConfigs[i].mode == SINGLE_ENDED) {
        ch["mode"] = "single";
        ch["channel"] = channelConfigs[i].channel;
      } else {
        ch["mode"] = "differential";
        ch["pair"] = channelConfigs[i].channel == 0 ? "0-1" : "2-3";
      }
    }
  }
  
  // Print JSON on single line (important for parsing)
  serializeJson(doc, Serial);
  Serial.println();  // Add newline
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

adsGain_t stringToGain(String gainStr) {
  if (gainStr == "TWOTHIRDS") return GAIN_TWOTHIRDS;
  if (gainStr == "ONE")       return GAIN_ONE;
  if (gainStr == "TWO")       return GAIN_TWO;
  if (gainStr == "FOUR")      return GAIN_FOUR;
  if (gainStr == "EIGHT")     return GAIN_EIGHT;
  if (gainStr == "SIXTEEN")   return GAIN_SIXTEEN;
  return GAIN_ONE;
}

void handleRoot() {
  String html = "<html><head><title>ESPLog - Hybrid Ecologies</title></head><body>";
  html += "<h1>ESPLog - Hybrid Ecologies Data Logger</h1>";
  html += "<p>Endpoints:</p>";
  html += "<ul>";
  html += "<li><a href='/data'>/data</a> - Get current ADC readings (JSON)</li>";
  html += "<li><a href='/config'>/config</a> - GET: View configuration, POST: Set configuration (JSON)</li>";
  html += "<li><a href='/stream'>/stream</a> - Get continuous stream info</li>";
  html += "</ul>";
  html += "<p>Sample Rate: " + String(currentSampleRate) + " Hz</p>";
  html += "<p>Active Channels: " + String(activeChannels) + "</p>";
  html += "</body></html>";
  
  server.send(200, "text/html", html);
}

void handleData() {
  // Set CORS headers
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.sendHeader("Access-Control-Allow-Methods", "GET");
  
  // Build JSON response
  StaticJsonDocument<512> doc;
  doc["timestamp"] = currentData.timestamp;
  
  JsonObject channels = doc.createNestedObject("channels");
  
  for (int i = 0; i < 4; i++) {
    if (currentData.active[i]) {
      JsonObject ch = channels.createNestedObject(String(i));
      ch["raw"] = currentData.adc[i];
      ch["voltage"] = currentData.voltage[i];
      
      // Add mode info
      if (channelConfigs[i].mode == SINGLE_ENDED) {
        ch["mode"] = "single";
        ch["channel"] = channelConfigs[i].channel;
      } else {
        ch["mode"] = "differential";
        ch["pair"] = channelConfigs[i].channel == 0 ? "0-1" : "2-3";
      }
    }
  }
  
  String output;
  serializeJson(doc, output);
  server.send(200, "application/json", output);
}

void handleGetConfig() {
  // Set CORS headers
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.sendHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  
  // Build configuration JSON
  StaticJsonDocument<1024> doc;
  doc["sample_rate"] = currentSampleRate;
  doc["data_rate"] = dataRate;
  doc["active_channels"] = activeChannels;
  
  JsonArray channels = doc.createNestedArray("channels");
  
  for (int i = 0; i < activeChannels; i++) {
    JsonObject ch = channels.createNestedObject();
    ch["index"] = i;
    ch["mode"] = (channelConfigs[i].mode == SINGLE_ENDED) ? "single" : "differential";
    ch["channel"] = channelConfigs[i].channel;
    ch["gain"] = gainToString(channelConfigs[i].gain);
  }
  
  String output;
  serializeJson(doc, output);
  server.send(200, "application/json", output);
}

void handleSetConfig() {
  // Set CORS headers
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.sendHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  
  if (!server.hasArg("plain")) {
    server.send(400, "application/json", "{\"error\":\"No body\"}");
    return;
  }
  
  String body = server.arg("plain");
  Serial.println("Received config: " + body);
  
  StaticJsonDocument<1024> doc;
  DeserializationError error = deserializeJson(doc, body);
  
  if (error) {
    Serial.print("JSON parse error: ");
    Serial.println(error.c_str());
    server.send(400, "application/json", "{\"error\":\"Invalid JSON\"}");
    return;
  }
  
  // Parse configuration
  if (doc.containsKey("sample_rate")) {
    currentSampleRate = doc["sample_rate"];
    sampleIntervalMs = 1000 / currentSampleRate;
  }
  
  if (doc.containsKey("data_rate")) {
    dataRate = doc["data_rate"];
  }
  
  if (doc.containsKey("mode")) {
    // Simple mode configuration
    String mode = doc["mode"].as<String>();
    
    if (mode == "single_ended") {
      // 4 single-ended channels
      activeChannels = 4;
      for (int i = 0; i < 4; i++) {
        channelConfigs[i].mode = SINGLE_ENDED;
        channelConfigs[i].channel = i;
        channelConfigs[i].gain = GAIN_ONE;
      }
    } else if (mode == "differential") {
      // 2 differential channels (0-1, 2-3)
      activeChannels = 2;
      channelConfigs[0].mode = DIFFERENTIAL;
      channelConfigs[0].channel = 0;  // 0-1
      channelConfigs[0].gain = GAIN_ONE;
      
      channelConfigs[1].mode = DIFFERENTIAL;
      channelConfigs[1].channel = 1;  // 2-3
      channelConfigs[1].gain = GAIN_ONE;
    }
    
    // Apply gain if specified
    if (doc.containsKey("gain")) {
      String gainStr = doc["gain"].as<String>();
      adsGain_t gain = stringToGain(gainStr);
      for (int i = 0; i < activeChannels; i++) {
        channelConfigs[i].gain = gain;
      }
    }
  }
  
  if (doc.containsKey("channels")) {
    // Advanced mode configuration
    JsonArray channels = doc["channels"].as<JsonArray>();
    activeChannels = channels.size();
    
    int i = 0;
    for (JsonObject ch : channels) {
      if (i >= 4) break;
      
      String mode = ch["mode"].as<String>();
      channelConfigs[i].mode = (mode == "single") ? SINGLE_ENDED : DIFFERENTIAL;
      channelConfigs[i].channel = ch["channel"];
      
      if (ch.containsKey("gain")) {
        String gainStr = ch["gain"].as<String>();
        channelConfigs[i].gain = stringToGain(gainStr);
      } else {
        channelConfigs[i].gain = GAIN_ONE;
      }
      
      i++;
    }
  }
  
  // Apply new configuration
  applyADCConfig();
  
  server.send(200, "application/json", "{\"status\":\"ok\",\"message\":\"Configuration applied\"}");
}

void handleConfigOptions() {
  // Handle CORS preflight
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.sendHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  server.sendHeader("Access-Control-Allow-Headers", "Content-Type");
  server.send(204);
}

void handleStream() {
  String info = "{";
  info += "\"status\":\"streaming\",";
  info += "\"ip\":\"" + WiFi.localIP().toString() + "\",";
  info += "\"sample_rate\":" + String(currentSampleRate) + ",";
  info += "\"endpoint\":\"/data\",";
  info += "\"config_endpoint\":\"/config\",";
  info += "\"message\":\"Poll the /data endpoint at your desired rate (max " + String(currentSampleRate) + " Hz)\"";
  info += "}";
  
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.send(200, "application/json", info);
}

void handleNotFound() {
  server.send(404, "text/plain", "Not Found");
}
