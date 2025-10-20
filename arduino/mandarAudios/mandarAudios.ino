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
#define RECORD_TIME 5000    // Tiempo de grabación en ms

/*Casa
INFINITUMFB33
HdKHhdnK7C
Escuela
saquenmedeaqui
12345678*/

const char* ssid = "ANA5000";
const char* password = "123456789";
const char* serverUrl = "http://192.168.137.225:8000/upload_chunk";
const char* serverFinalizar = "http://192.168.137.225:8000/finalize_wav";
DHT dht(DHTPIN, DHTTYPE);



int16_t buffer[CHUNK_SIZE];  // Cambiar a 16 bits directamente
bool isRecording = false;
unsigned long recordStartTime = 0;

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
    .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,  // Cambiar a 16 bits para mejor compatibilidad
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,   // Solo canal izquierdo para INMP441
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,  // Formato estándar I2S
    .intr_alloc_flags = 0,
    .dma_buf_count = 8,  // Incrementar buffers para evitar pérdida de datos
    .dma_buf_len = 512,  // Reducir tamaño de buffer individual
    .use_apll = true,    // Usar APLL para mejor precisión de frecuencia
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

void sendChunkToServer(int16_t* pcmChunk, size_t size, float humedad) {
  HTTPClient http;
  http.begin(serverUrl);
  http.addHeader("Content-Type", "application/octet-stream");
  http.addHeader("X-Humidity", String(humedad));  // Enviar humedad en header
  http.addHeader("X-Timestamp", String(millis())); // Timestamp para sincronización

  int httpResponseCode = http.POST((uint8_t*)pcmChunk, size);

  if (httpResponseCode > 0) {
    Serial.printf("Chunk enviado con humedad %.1f%%, servidor respondió: %d\n", humedad, httpResponseCode);
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
  
  if (isnan(humedad)) {
    Serial.println("Error al leer el sensor DHT11");
    humedad = 0.0; // Valor por defecto si hay error
  }

  // Lógica mejorada para inicio/fin de grabación
  if (distance < 60 && !isRecording) {
    // Comenzar grabación
    isRecording = true;
    recordStartTime = millis();
    Serial.printf("Iniciando grabación. Distancia: %.1fcm, Humedad: %.1f%%\n", distance, humedad);
  }

  if (isRecording) {
    // Verificar si debe continuar grabando
    if (distance >= 60 || (millis() - recordStartTime) > RECORD_TIME) {
      // Finalizar grabación
      isRecording = false;
      finalizeWav();
      Serial.println("Finalizando grabación");
      delay(2000); // Pausa antes de permitir nueva grabación
      return;
    }

    // Leer datos de audio directamente en 16 bits
    size_t bytesRead;
    esp_err_t result = i2s_read(I2S_PORT, buffer, CHUNK_SIZE * sizeof(int16_t), &bytesRead, 100);
    
    if (result == ESP_OK && bytesRead > 0) {
      // Los datos ya están en formato 16 bits, no necesitan conversión adicional
      size_t samplesRead = bytesRead / sizeof(int16_t);
      
      // Aplicar ganancia para mejorar el volumen
      for (int i = 0; i < samplesRead; i++) {
        int32_t sample = buffer[i] * 4; // Aumentar ganancia
        if (sample > 32767) sample = 32767;
        if (sample < -32768) sample = -32768;
        buffer[i] = (int16_t)sample;
      }
      
      // Enviar chunk al servidor con datos del sensor
      sendChunkToServer(buffer, bytesRead, humedad);
      
      Serial.printf("Chunk enviado - Muestras: %d, Humedad: %.1f%%, Distancia: %.1fcm\n", 
                   samplesRead, humedad, distance);
    }
  }
  
  delay(10); // Pequeña pausa para no saturar el sistema
}

