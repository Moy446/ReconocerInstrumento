#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <driver/i2s.h>

#define I2S_WS      25   // LRCL
#define I2S_SD      22   // DOUT
#define I2S_SCK     26   // BCLK
#define I2S_PORT    I2S_NUM_0

#define SAMPLE_RATE     8000
#define RECORD_TIME     2              // segundos
#define BUFFER_SIZE     (SAMPLE_RATE * RECORD_TIME)

const char* ssid = "INFINITUMFB33";
const char* password = "HdKHhdnK7C";
const char* serverUrl = "http://192.168.1.78:8000/upload"; // endpoint en tu servidor

// Buffer para guardar audio
int32_t samples[BUFFER_SIZE];

// ----------------------
// Configuración I2S
// ----------------------
void setupI2S() {
  i2s_config_t i2s_config = {
    .mode = i2s_mode_t(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT,
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT, // L/R=GND → canal izquierdo
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

// ----------------------
// Generar encabezado WAV
// ----------------------
void createWavHeader(uint8_t* header, int wavSize, int sampleRate) {
  int byteRate = sampleRate * 2; // 16 bits = 2 bytes

  memcpy(header, "RIFF", 4);
  *(int32_t*)(header + 4) = wavSize - 8;
  memcpy(header + 8, "WAVE", 4);

  memcpy(header + 12, "fmt ", 4);
  *(int32_t*)(header + 16) = 16;          // Subchunk1Size
  *(int16_t*)(header + 20) = 1;           // AudioFormat PCM
  *(int16_t*)(header + 22) = 1;           // NumChannels = 1 (mono)
  *(int32_t*)(header + 24) = sampleRate;  // SampleRate
  *(int32_t*)(header + 28) = byteRate;    // ByteRate
  *(int16_t*)(header + 32) = 2;           // BlockAlign
  *(int16_t*)(header + 34) = 16;          // BitsPerSample

  memcpy(header + 36, "data", 4);
  *(int32_t*)(header + 40) = wavSize - 44;
}

// ----------------------
// Grabar audio en buffer
// ----------------------
void recordAudio() {
  size_t bytesRead;
  int totalSamples = 0;

  Serial.println("Grabando...");

  while (totalSamples < BUFFER_SIZE) {
    i2s_read(I2S_PORT, (void*)&samples[totalSamples],
             (BUFFER_SIZE - totalSamples) * sizeof(int32_t),
             &bytesRead, portMAX_DELAY);

    totalSamples += bytesRead / sizeof(int32_t);
  }

  Serial.println("Grabación finalizada");
}

// ----------------------
// Enviar WAV al servidor
// ----------------------
void sendAudio() {
  int16_t pcm[BUFFER_SIZE];
  for (int i = 0; i < BUFFER_SIZE; i++) {
    pcm[i] = samples[i] >> 16; // convertir 32 bits → 16 bits PCM
  }

  int wavSize = 44 + BUFFER_SIZE * sizeof(int16_t);
  uint8_t* wavData = (uint8_t*)malloc(wavSize);

  createWavHeader(wavData, wavSize, SAMPLE_RATE);
  memcpy(wavData + 44, pcm, BUFFER_SIZE * sizeof(int16_t));

  HTTPClient http;
  http.begin(serverUrl);
  http.addHeader("Content-Type", "audio/wav");

  int httpResponseCode = http.POST(wavData, wavSize);

  if (httpResponseCode > 0) {
    Serial.printf("Respuesta del servidor: %d\n", httpResponseCode);
  } else {
    Serial.printf("Error en envío: %s\n", http.errorToString(httpResponseCode).c_str());
  }

  http.end();
  free(wavData);
}

// ----------------------
// Setup principal
// ----------------------
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
}

// ----------------------
// Loop principal
// ----------------------
void loop() {
  recordAudio();
  sendAudio();
  delay(10000); // espera 10s entre grabaciones
}
