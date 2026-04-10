// ESPNOW_BiDirectional.ino
// Adafruit ESP32 Feather V2 — bi-directional ESP-NOW demo
// Flash identical code to both boards, just fill in both MAC addresses below.
//
// Board A — Send: BLUE   | Receive: YELLOW
// Board B — Send: PINK   | Receive: GREEN

#include <esp_now.h>
#include <WiFi.h>
#include <Adafruit_NeoPixel.h>

// ─── EDIT THESE ──────────────────────────────────────────────────────────────
// Paste BOTH MACs here. Each board will figure out which one is "self"
// and use the other as the peer.
uint8_t MAC_A[] = {0x00, 0x4B, 0x12, 0xBD, 0x58, 0xB8}; // ← replace with Board A MAC
uint8_t MAC_B[] = {0xF4, 0x65, 0x0B, 0x31, 0xEEC8, 0x6C}; // ← replace with Board B MAC
// ─────────────────────────────────────────────────────────────────────────────

#define NEOPIXEL_PIN   0   // Adafruit ESP32 Feather V2 onboard NeoPixel data pin
#define NEOPIXEL_POWER 2   // Power pin for onboard NeoPixel (must be HIGH)
#define NUM_PIXELS     1
#define BLINK_MS       120 // blink duration in milliseconds

Adafruit_NeoPixel pixel(NUM_PIXELS, NEOPIXEL_PIN, NEO_GRB + NEO_KHZ800);

uint8_t peerMAC[6];
bool    peerAdded = false;
bool    isBoardA  = false;
String  inputBuffer = "";

// ── helpers ──────────────────────────────────────────────────────────────────

void blinkPixel(uint32_t color) {
  pixel.setPixelColor(0, color);
  pixel.show();
  delay(BLINK_MS);
  pixel.setPixelColor(0, 0);
  pixel.show();
}

bool macEquals(const uint8_t *a, const uint8_t *b) {
  for (int i = 0; i < 6; i++) if (a[i] != b[i]) return false;
  return true;
}

void printMAC(const uint8_t *mac) {
  for (int i = 0; i < 6; i++) {
    if (i) Serial.print(":");
    if (mac[i] < 0x10) Serial.print("0");
    Serial.print(mac[i], HEX);
  }
}

// ── ESP-NOW callbacks ─────────────────────────────────────────────────────────

void onSent(const esp_now_send_info_t *info, esp_now_send_status_t status) {
  Serial.print("[SEND] → ");
  printMAC(info->des_addr);
  Serial.print("  status: ");
  Serial.println(status == ESP_NOW_SEND_SUCCESS ? "OK" : "FAIL");
}

void onReceive(const esp_now_recv_info_t *info, const uint8_t *data, int len) {
  // Board A receives → YELLOW | Board B receives → GREEN
  blinkPixel(isBoardA ? pixel.Color(80, 60, 0) : pixel.Color(0, 80, 0));

  Serial.print("[RECV] ← ");
  printMAC(info->src_addr);
  Serial.print("  \"");
  for (int i = 0; i < len; i++) Serial.print((char)data[i]);
  Serial.println("\"");
}

// ── send helper ───────────────────────────────────────────────────────────────

void sendMessage(const String &msg) {
  if (!peerAdded) {
    Serial.println("[ERROR] No peer registered.");
    return;
  }
  // Board A sends → BLUE | Board B sends → PINK
  blinkPixel(isBoardA ? pixel.Color(0, 0, 80) : pixel.Color(80, 10, 40));

  esp_err_t result = esp_now_send(peerMAC,
                                  (const uint8_t *)msg.c_str(),
                                  msg.length());
  if (result != ESP_OK) {
    Serial.print("[SEND] esp_now_send error: ");
    Serial.println(result);
  }
}

// ── setup ─────────────────────────────────────────────────────────────────────

void setup() {
  Serial.begin(115200);
  delay(500);

  // power up NeoPixel
  pinMode(NEOPIXEL_POWER, OUTPUT);
  digitalWrite(NEOPIXEL_POWER, HIGH);
  pixel.begin();
  pixel.setBrightness(60);
  pixel.clear();
  pixel.show();

  WiFi.mode(WIFI_STA);
  WiFi.begin();
  delay(200);

  // determine which board we are, set the other as peer
  String myMACStr = WiFi.macAddress(); // e.g. "AA:BB:CC:DD:EE:01"
  myMACStr.toUpperCase();

  // build comparable strings from the arrays
  char macAStr[18], macBStr[18];
  snprintf(macAStr, sizeof(macAStr), "%02X:%02X:%02X:%02X:%02X:%02X",
    MAC_A[0],MAC_A[1],MAC_A[2],MAC_A[3],MAC_A[4],MAC_A[5]);
  snprintf(macBStr, sizeof(macBStr), "%02X:%02X:%02X:%02X:%02X:%02X",
    MAC_B[0],MAC_B[1],MAC_B[2],MAC_B[3],MAC_B[4],MAC_B[5]);

  Serial.print("\nMy MAC: ");
  Serial.println(myMACStr);

  if (myMACStr == String(macAStr)) {
    isBoardA = true;
    memcpy(peerMAC, MAC_B, 6);
    Serial.println("I am Board A — peer is Board B");
  } else if (myMACStr == String(macBStr)) {
    isBoardA = false;
    memcpy(peerMAC, MAC_A, 6);
    Serial.println("I am Board B — peer is Board A");
  } else {
    Serial.println("WARNING: My MAC doesn't match either entry — check MAC_A / MAC_B above!");
    memcpy(peerMAC, MAC_A, 6);
  }

  // init ESP-NOW
  if (esp_now_init() != ESP_OK) {
    Serial.println("ESP-NOW init failed!");
    return;
  }
  esp_now_register_send_cb(onSent);
  esp_now_register_recv_cb(onReceive);

  // register peer
  esp_now_peer_info_t peerInfo = {};
  memcpy(peerInfo.peer_addr, peerMAC, 6);
  peerInfo.channel = 0;
  peerInfo.encrypt = false;
  if (esp_now_add_peer(&peerInfo) == ESP_OK) {
    peerAdded = true;
    Serial.print("Peer registered: ");
    printMAC(peerMAC);
    Serial.println();
  } else {
    Serial.println("Failed to add peer!");
  }

  Serial.println("\nReady! Type a message and press Enter to send.\n");
}

// ── loop ──────────────────────────────────────────────────────────────────────

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (inputBuffer.length() > 0) {
        sendMessage(inputBuffer);
        inputBuffer = "";
      }
    } else {
      inputBuffer += c;
    }
  }
}
