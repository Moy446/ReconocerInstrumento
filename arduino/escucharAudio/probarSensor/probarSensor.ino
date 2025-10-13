#include <Arduino.h>
#include <driver/i2s.h>
#include "DHT.h"


#define I2S_WS 25   // LRCL
#define I2S_SD 22   // DOUT
#define I2S_SCK 26   // BCLK
#define trigger 23  //hcsr trigger
#define echo 21  //hcsr trigger
#define DHTPIN 4        // Pin de datos
#define DHTTYPE DHT11   // Tipo de senso

#define SAMPLE_RATE     44100
#define I2S_PORT        I2S_NUM_0
DHT dht(DHTPIN, DHTTYPE);


float readDistance() {
  digitalWrite(trigger, LOW);   // Set trig pin to low to ensure a clean pulse
  delayMicroseconds(2);         // Delay for 2 microseconds
  digitalWrite(trigger, HIGH);  // Send a 10 microsecond pulse by setting trig pin to high
  delayMicroseconds(10);
  digitalWrite(trigger, LOW);  // Set trig pin back to low

  // Measure the pulse width of the echo pin and calculate the distance value
  float distance = pulseIn(echo, HIGH) / 58.00;  // Formula: (340m/s * 1us) / 2
  return distance;
}


void setup() {
  Serial.begin(115200);

  // Configuración I2S
  i2s_config_t i2s_config = {
      .mode = i2s_mode_t(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT, // I2S_BITS_PER_SAMPLE_16BIT or I2S_BITS_PER_SAMPLE_32BIT
    .channel_format = I2S_CHANNEL_FMT_ONLY_RIGHT,      // L/R to high - left, L/R to ground - right channel
    .communication_format = i2s_comm_format_t(I2S_COMM_FORMAT_I2S | I2S_COMM_FORMAT_I2S_MSB),
    .intr_alloc_flags = 0, // default interrupt priority
    //.intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 4,
    .dma_buf_len = 1024,
    .use_apll = false,
    .tx_desc_auto_clear = false,
    .fixed_mclk = 0
  };

  i2s_pin_config_t pin_config = {
    .bck_io_num = I2S_SCK,
    .ws_io_num = I2S_WS,
    .data_out_num = I2S_PIN_NO_CHANGE, // No transmitimos
    .data_in_num = I2S_SD
  };

  i2s_driver_install(I2S_PORT, &i2s_config, 0, NULL);
  i2s_set_pin(I2S_PORT, &pin_config);

  pinMode(trigger, OUTPUT);
  pinMode(echo, INPUT);

  dht.begin();

  Serial.println("INMP441 listo para grabar audio.");
  Serial.println("HC-SR04 listo para medir distancia");
}

void loop() {
  float humedad = dht.readHumidity();
  const int bufferSize = 1024;
  int32_t buffer[bufferSize];
  size_t bytesRead;
  float distancia = readDistance();

  if (isnan(humedad)){
    Serial.println("Error al leer el sensor DHT11");
  }
  Serial.print("Humedad: ");
  Serial.print(humedad);

  if(distancia<60){
    // Leer audio
    i2s_read(I2S_PORT, (void*)buffer, bufferSize * sizeof(int32_t), &bytesRead, portMAX_DELAY);

    // Número real de muestras leídas
    int samplesRead = bytesRead / sizeof(int32_t);
    long long sumSquares = 0;
    int32_t peak = 0;
    for (int i = 0; i < samplesRead; i++) {
      // Escalar a 24 bits útiles
      int32_t sample = buffer[i] >> 8;
      // RMS
      sumSquares += (long long)sample * sample;
      // Pico absoluto
      if (abs(sample) > peak) {
        peak = abs(sample);
      }
  }
  // Calcular RMS del bloque
  float rms = sqrt((double)sumSquares / samplesRead);
  // Mostrar resultados
  Serial.print("RMS: ");
  Serial.print(rms);
  Serial.print(" | Peak: ");
  Serial.println(peak);

  delay(100);
  }
  else{
    Serial.println("Acercate mas");
  }
  delay(400);
}