// MAC_Finder.ino
// Flash this to each ESP32 Feather V2 and open Serial Monitor (115200 baud)
// to read the board's MAC address. You'll need both MACs for the main sketch.

#include <WiFi.h>

void setup() {
  Serial.begin(115200);
  while (!Serial) delay(10);

  WiFi.mode(WIFI_STA);
  WiFi.begin();          // init the stack so MAC is populated
  delay(200);            // give it time to settle

  Serial.println("\n-----------------------------");
  Serial.print("MAC Address: ");
  Serial.println(WiFi.macAddress());
  Serial.println("-----------------------------");
}

void loop() {}
