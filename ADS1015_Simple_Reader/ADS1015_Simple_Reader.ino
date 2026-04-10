/*
 * Simple ADS1015 Channel 0 Reader
 * 
 * Reads channel 0 in single-ended mode and prints voltage to Serial Monitor
 * 
 * Wiring:
 * ADS1015 VDD -> ESP32 3.3V
 * ADS1015 GND -> ESP32 GND
 * ADS1015 SDA -> ESP32 GPIO 23 (SDA)
 * ADS1015 SCL -> ESP32 GPIO 22 (SCL)
 * ADS1015 ADDR -> GND (sets I2C address to 0x48)
 * 
 * Sensor -> ADS1015 A0
 * 
 * Required Library:
 * - Adafruit_ADS1X15 (install via Library Manager)
 */

#include <Wire.h>
#include <Adafruit_ADS1X15.h>

// Create ADS1015 object
Adafruit_ADS1015 ads;

void setup() {
  Serial.begin(115200);
  delay(1000);
  
  Serial.println("ADS1015 Channel 0 Reader");
  Serial.println("------------------------");
  
  // Initialize I2C
  Wire.begin();
  
  // Initialize ADS1015
  if (!ads.begin()) {
    Serial.println("ERROR: Failed to initialize ADS1015!");
    Serial.println("Check wiring:");
    Serial.println("  - VDD to 3.3V");
    Serial.println("  - GND to GND");
    Serial.println("  - SDA to GPIO 23");
    Serial.println("  - SCL to GPIO 22");
    Serial.println("  - ADDR to GND");
    while (1);
  }
  
  // Set gain to ONE (±4.096V range)
  // Options: GAIN_TWOTHIRDS, GAIN_ONE, GAIN_TWO, GAIN_FOUR, GAIN_EIGHT, GAIN_SIXTEEN
  ads.setGain(GAIN_ONE);
  
  Serial.println("ADS1015 initialized successfully!");
  Serial.println("Gain: ONE (±4.096V range)");
  Serial.println();
  Serial.println("Reading channel 0...");
  Serial.println();
}

void loop() {
  // Read channel 0 (single-ended)
  int16_t adc0 = ads.readADC_SingleEnded(0);
  
  // Convert to voltage
  float voltage0 = ads.computeVolts(adc0);
  
  // Print to Serial Monitor
  Serial.print("CH0: ");
  Serial.print(voltage0, 3);  // 3 decimal places
  Serial.print(" V  (raw: ");
  Serial.print(adc0);
  Serial.println(")");
  
  // Wait 200ms (5 Hz sample rate)
  delay(200);
}
