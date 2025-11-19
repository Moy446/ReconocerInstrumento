#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <driver/i2s.h>
#include "DHT.h"

// 🎙️ Pines I2S ICS-43434
#define I2S_WS 25
#define I2S_SD 32
#define I2S_SCK 33

// Sensores
#define trigger 23
#define echo 21
#define DHTPIN 4
#define DHTTYPE DHT11

// Audio
#define SAMPLE_RATE 32000      // ICS-43434 recomendado
#define BUFFER_SIZE 1024
#define RECORD_TIME 5000

/*Escuela
Holiwis
1234567890*/

// WiFi
const char* ssid = "Holiwis";
const char* password = "1234567890";

const char* serverUrl = "https://detectarinstrumentos.azurewebsites.net/upload_chunk";
const char* serverFinalizar = "https://detectarinstrumentos.azurewebsites.net/finalize_wav";

DHT dht(DHTPIN, DHTTYPE);

// Buffers globales seguros
static int32_t audio_sample[BUFFER_SIZE];
static int16_t pcm16[512];

// Filtros globales
static int32_t prev_input = 0;
static float prev_output = 0;
static int smooth_idx = 0;
static int16_t smooth_buffer[4] = {0};    // Ventana móvil 4

bool isRecording = false;
unsigned long recordStartTime = 0;


// ------------------------------------------------------
// ULTRASONIDO
// ------------------------------------------------------
float readDistance() {
  digitalWrite(trigger, LOW);
  delayMicroseconds(2);
  digitalWrite(trigger, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigger, LOW);

  float distance = pulseIn(echo, HIGH) / 58.00;
  return distance;
}


// ------------------------------------------------------
// CONFIGURAR I2S (ICS-43434)
// ------------------------------------------------------
void setupI2S() {
  i2s_config_t i2s_config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT,
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 8,
    .dma_buf_len = BUFFER_SIZE,
    .use_apll = false,
    .tx_desc_auto_clear = false,
    .fixed_mclk = 0
  };

  i2s_driver_install(I2S_NUM_0, &i2s_config, 0, NULL);
  
  i2s_pin_config_t pin_config = {
    .bck_io_num = I2S_SCK,
    .ws_io_num = I2S_WS,
    .data_out_num = -1,
    .data_in_num = I2S_SD
  };

  i2s_set_pin(I2S_NUM_0, &pin_config);
}


// ------------------------------------------------------
// SUBIR CHUNK
// ------------------------------------------------------
void sendChunkToServer(int16_t* pcmChunk, size_t size, float humedad) {
  HTTPClient http;

  http.begin(serverUrl);
  http.addHeader("Content-Type", "application/octet-stream");
  http.addHeader("X-Humidity", String(humedad));
  http.addHeader("X-Timestamp", String(millis()));

  int httpResponseCode = http.POST((uint8_t*)pcmChunk, size);

  if (httpResponseCode > 0) {
    Serial.printf("Chunk enviado (%d bytes) Humedad %.1f%%\n", size, humedad);
  } else {
    Serial.printf("Error enviando chunk: %s\n",
                  http.errorToString(httpResponseCode).c_str());
  }

  http.end();
}


// ------------------------------------------------------
// FINALIZAR ARCHIVO WAV
// ------------------------------------------------------
void finalizeWav() {
  HTTPClient http;
  http.begin(serverFinalizar);

  int httpResponseCode = http.GET();
  if (httpResponseCode > 0) {
    Serial.println("Respuesta del servidor:");
    Serial.println(http.getString());
  } else {
    Serial.println("Error finalizando WAV");
  }

  http.end();
}


// ------------------------------------------------------
// SETUP
// ------------------------------------------------------
void setup() {
  Serial.begin(115200);

  WiFi.begin(ssid, password);
  Serial.println("Conectando...");

  while (WiFi.status() != WL_CONNECTED) {
    delay(300);
    Serial.print(".");
  }

  Serial.println("\nWiFi conectado.");
  Serial.println(WiFi.localIP());

  setupI2S();

  pinMode(trigger, OUTPUT);
  pinMode(echo, INPUT);

  dht.begin();
}


// ------------------------------------------------------
// LOOP
// ------------------------------------------------------
void loop() {

  float distancia = readDistance();
  float humedad = dht.readHumidity();
  if (isnan(humedad)) humedad = 0.0;

  // Iniciar grabación
  if (distancia < 60 && !isRecording) {
    isRecording = true;
    recordStartTime = millis();
    Serial.println("▶ Grabación iniciada");
  }

  // Parar grabación
  if (isRecording &&
     (distancia >= 60 || (millis() - recordStartTime) > RECORD_TIME)) {

    isRecording = false;
    finalizeWav();
    Serial.println("⛔ Grabación detenida");
    delay(1500);
    return;
  }


  // Si está grabando → procesar audio
  if (isRecording) {

    size_t bytes_read;
    esp_err_t result = i2s_read(I2S_NUM_0, audio_sample, sizeof(audio_sample), &bytes_read, portMAX_DELAY);

    if (result != ESP_OK || bytes_read == 0)
      return;

    int sampleCount = bytes_read / sizeof(int32_t);
    const float alpha = 0.98;     // menos ruido
    for (int i = 0; i < sampleCount; i++) {

      int32_t input = audio_sample[i] >> 16;  // 24-bit → 16-bit correcto

      float output = (float)(input - prev_input) + alpha * prev_output;
      prev_input = input;
      prev_output = output;
      pcm16[i] = (int16_t)output;

      // Guardar valor filtrado
      smooth_buffer[smooth_idx] = (int16_t)output;
      smooth_idx = (smooth_idx + 1) % 4;

      int32_t sum = 0;
      for (int j = 0; j < 4; j++) sum += smooth_buffer[j];
      pcm16[i] = sum / 4;
    }

    // Enviar chunk
    sendChunkToServer(pcm16, sampleCount * sizeof(int16_t), humedad);
  }

  delay(10);
}
