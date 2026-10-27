/*
 * TCMIM - M4 ESP32 Firmware (ADXL345 Vibration Sensor)
 * 
 * This firmware reads vibration data from an ADXL345 sensor via I2C
 * and transmits it over the Serial port in JSON format. The Python
 * ingestion pipeline reads this Serial data to acquire HARDWARE provenance
 * sensor samples.
 * 
 * Hardware Connections (ESP32 -> ADXL345):
 * 3V3  -> VCC
 * GND  -> GND
 * G21  -> SDA
 * G22  -> SCL
 * 
 * Dependencies (Arduino IDE / PlatformIO):
 * - Adafruit Unified Sensor
 * - Adafruit ADXL345
 * - ArduinoJson
 */

#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_ADXL345_U.h>
#include <ArduinoJson.h>

// Initialize the ADXL345 sensor (assigning a unique ID, e.g., 12345)
Adafruit_ADXL345_Unified accel = Adafruit_ADXL345_Unified(12345);

// Configuration
const int BAUD_RATE = 115200;
const int SAMPLE_DELAY_MS = 10; // ~100Hz sampling rate
const char* MACHINE_ID = "esp32_testbed_1"; // Logical machine identifier

void setup() {
  Serial.begin(BAUD_RATE);
  while (!Serial) {
    delay(10); // Wait for serial port to connect
  }

  // Initialize I2C and sensor
  if (!accel.begin()) {
    // Send a structured error if initialization fails
    StaticJsonDocument<200> errDoc;
    errDoc["error"] = "No ADXL345 detected. Check wiring.";
    serializeJson(errDoc, Serial);
    Serial.println();
    while (1) {
      delay(100);
    }
  }

  // Set the range of the accelerometer to +/- 16G for max dynamic range
  accel.setRange(ADXL345_RANGE_16_G);
  
  // Set data rate to 100 Hz
  accel.setDataRate(ADXL345_DATARATE_100_HZ);
}

void loop() {
  // Get a new sensor event
  sensors_event_t event;
  accel.getEvent(&event);

  // Prepare JSON payload
  // We use ArduinoJson to ensure strict JSON formatting for the Python ingestor
  StaticJsonDocument<256> doc;
  
  doc["machine_id"] = MACHINE_ID;
  doc["timestamp_ms"] = millis();
  
  // Data object containing X, Y, Z acceleration in m/s^2
  JsonObject data = doc.createNestedObject("data");
  data["accel_x"] = event.acceleration.x;
  data["accel_y"] = event.acceleration.y;
  data["accel_z"] = event.acceleration.z;

  // Output over Serial
  serializeJson(doc, Serial);
  Serial.println();

  // Wait before next sample
  delay(SAMPLE_DELAY_MS);
}
