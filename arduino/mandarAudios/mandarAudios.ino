#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <driver/i2s.h>
#include "DHT.h"

#define I2S_WS      25
#define I2S_SD      22
#define I2S_SCK     26
#define I2S_PORT    I2S_NUM_0
#define trigger     23  //hcsr trigger
#define echo        21  //hcsr trigger
#define DHTPIN 4        // Pin de datos
#define DHTTYPE DHT11   // Tipo de sensor

#define SAMPLE_RATE 16000
#define CHUNK_SIZE  1024    // Bloque pequeño

/*Casa
INFINITUMFB33
HdKHhdnK7C*/
const char* ssid = "Holiwis";
const char* password = "1234567890";
const char* serverUrl = "http://192.168.1.84:8000/upload_chunk";
const char* serverFinalizar = "http://192.168.1.84:8000/finalize_wav";
DHT dht(DHTPIN, DHTTYPE);



int32_t buffer[CHUNK_SIZE];

float readDistance() {
  digitalWrite(trigger, LOW);   // Set trig pin to low to ensure a clean pulse
  delayMicroseconds(2);         
  digitalWrite(trigger, HIGH);  // Send a 10 microsecond pulse by setting trig pin to high
  delayMicroseconds(10);
  digitalWrite(trigger, LOW);  // Set trig pin back to low

  float distance = pulseIn(echo, HIGH) / 58.00;  // Formula: (340m/s * 1us) / 2
  return distance;
}

void setupI2S() {
  i2s_config_t i2s_config = {
    .mode = i2s_mode_t(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT,
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = i2s_comm_format_t(I2S_COMM_FORMAT_I2S | I2S_COMM_FORMAT_I2S_MSB),
    .intr_alloc_flags = 0,
    .dma_buf_count = 4,
    .dma_buf_len = 1024,
    .use_apll = false,
    .tx_desc_auto_clear = false,
    .fixed_mclk = 0
  };

  i2s_pin_config_t pin_config = {
    .bck_io_num = I2S_SCK,
    .ws_io_num = I2S_WS,
    .data_out_num = I2S_PIN_NO_CHANGE,
    .data_in_num = I2S_SD
  };

  i2s_driver_install(I2S_PORT, &i2s_config, 0, NULL);
  i2s_set_pin(I2S_PORT, &pin_config);
}

void sendChunkToServer(int16_t* pcmChunk, size_t size) {
  HTTPClient http;
  http.begin(serverUrl);
  http.addHeader("Content-Type", "application/octet-stream");

  int httpResponseCode = http.POST((uint8_t*)pcmChunk, size);

  if (httpResponseCode > 0) {
    Serial.printf("Chunk enviado, servidor respondió: %d\n", httpResponseCode);
  } else {
    Serial.printf("Error enviando chunk: %s\n", http.errorToString(httpResponseCode).c_str());
  }
  http.end();
}
void finalizeWav() {
  HTTPClient http;
  http.begin(serverFinalizar);
  int httpResponseCode = http.GET();
  if (httpResponseCode > 0) {
    String response = http.getString();
    Serial.println("Respuesta del servidor:");
    Serial.println(response);
  } else {
    Serial.println("Error en GET");
  }
  http.end();
}
void setup() {
  Serial.begin(115200);
  WiFi.begin(ssid, password);

  Serial.println("Conectando WiFi...");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi conectado");

  setupI2S();
  pinMode(trigger, OUTPUT);
  pinMode(echo, INPUT);
  dht.begin();
}

void loop() {
  float distance = readDistance();
  float humedad = dht.readHumidity();
  size_t bytesRead;
  if (isnan(humedad)){
    Serial.println("Error al leer el sensor DHT11");
  }

  if (distance<60){
    // Leer un chunk
    i2s_read(I2S_PORT, buffer, CHUNK_SIZE * sizeof(int32_t), &bytesRead, portMAX_DELAY);
    // Convertir a 16 bits PCM
    int16_t pcmChunk[CHUNK_SIZE];
    for (int i = 0; i < CHUNK_SIZE; i++) {
      int32_t sample = buffer[i];
      sample = (sample >> 8) & 0xFFFFFF; // tomar 24 bits útiles
      pcmChunk[i] = sample >> 8; 
    }
    // Enviar chunk al servidor
    sendChunkToServer(pcmChunk, CHUNK_SIZE * sizeof(int16_t));
    delay(10); // opcional, para no saturar la red
    Serial.print("Humedad: ");
    Serial.print(humedad);
  }else{
    finalizeWav();
  }

}

