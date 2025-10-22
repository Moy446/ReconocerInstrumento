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
#define DHTPIN      4   // Pin de datos
#define DHTTYPE DHT11   // Tipo de sensor

#define SAMPLE_RATE 16000
#define CHUNK_SIZE  1024    // Bloque pequeño
#define RECORD_TIME 5000    // Tiempo de grabación en ms

/*Casa
INFINITUMFB33
HdKHhdnK7C*/
const char* ssid = "Holiwis";
const char* password = "1234567890";
const char* serverUrl = "http://192.168.1.84:8000/upload_chunk";
const char* serverFinalizar = "http://192.168.1.84:8000/finalize_wav";
DHT dht(DHTPIN, DHTTYPE);



int32_t buffer[CHUNK_SIZE];  // Buffer en 32 bits para INMP441
int16_t samples[CHUNK_SIZE]; // Buffer para muestras convertidas a 16 bits
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
    .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT,  // INMP441 usa 32 bits
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,   // Solo canal izquierdo
    .communication_format = i2s_comm_format_t(I2S_COMM_FORMAT_I2S | I2S_COMM_FORMAT_I2S_MSB),
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
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

    // Leer datos de audio en 32 bits (formato INMP441)
    size_t bytesRead = 0;
    esp_err_t result = i2s_read(I2S_PORT, buffer, CHUNK_SIZE * sizeof(int32_t), &bytesRead, portMAX_DELAY);
    
    if (result == ESP_OK && bytesRead > 0) {
      size_t samplesRead = bytesRead / sizeof(int32_t);
      
      // Convertir de 32 bits a 16 bits correctamente para INMP441
      for (int i = 0; i < samplesRead; i++) {
        // INMP441 entrega datos en los bits 31-14 (18 bits significativos)
        // Desplazar 14 bits a la derecha para obtener los 18 bits útiles
        // Luego desplazar 2 bits más para convertir a 16 bits
        int32_t sample32 = buffer[i] >> 14;  // Obtener bits significativos
        
        // Aplicar ganancia (ajustar según necesidad, probar valores entre 1-8)
        sample32 = sample32 * 2;
        
        // Limitar a rango de 16 bits con signo
        if (sample32 > 32767) sample32 = 32767;
        if (sample32 < -32768) sample32 = -32768;
        
        samples[i] = (int16_t)sample32;
      }
      
      // Enviar chunk al servidor con datos del sensor
      sendChunkToServer(samples, samplesRead * sizeof(int16_t), humedad);
      
      Serial.printf("Chunk enviado - Muestras: %d, Humedad: %.1f%%, Distancia: %.1fcm\n", 
                   samplesRead, humedad, distance);
    }
  }
  
  delay(10); // Pequeña pausa para no saturar el sistema
}

