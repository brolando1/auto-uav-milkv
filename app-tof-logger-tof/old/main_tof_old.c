#include <string.h>
#include <stdint.h>
#include <stdbool.h>

#include "app.h"

#include "FreeRTOS.h"
#include "task.h"

#include "debug.h"
#include "crtp.h"
#include "vl53l5cx_api.h"
#include "I2C_expander.h"


#define DEBUG_MODULE "TOFMATRIX"
#define NR_OF_SENSORS 4
#define NR_OF_PIXELS 64

static VL53L5CX_Configuration tof_dev[NR_OF_SENSORS];
static VL53L5CX_ResultsData tof_data;

void send_command(uint8_t command, uint8_t arg);
void send_data_packet(uint8_t *data, uint16_t data_len);
void send_data_packet_28b(uint8_t *data, uint8_t size, uint8_t index);

uint8_t config_sensors(VL53L5CX_Configuration *p_dev, uint16_t new_i2c_address);

#define TOF_I2C_ADDR 0x56
uint8_t tof_i2c_addresses[NR_OF_SENSORS];

void appMain() {
   DEBUG_PRINT("Size of configuration %d \n", sizeof(VL53L5CX_Configuration));

   DEBUG_PRINT("Configured for %d ToF sensor(s) \n", NR_OF_SENSORS);
   // Configure GPIO expander pins modes
   I2C_expander_initialize();
   I2C_expander_set_pin(LED0, 1);
   // Define the address of each ToF matrix sensor
   for(uint8_t i=0; i<NR_OF_SENSORS; i++)
      tof_i2c_addresses[i] = TOF_I2C_ADDR + 2 + 2*i;

   // Configure the ToF sensor(s)
   for(uint8_t i=0; i<NR_OF_SENSORS; i++) {
      I2C_expander_set_pin(i, 1); 

      // Configure the current sensor
      uint8_t status = config_sensors(&tof_dev[i], tof_i2c_addresses[i]);
      DEBUG_PRINT("Sensor %d conf. status: %d  (0 means ok) \n", i, status);

      // Start ranging
      status = vl53l5cx_start_ranging(&tof_dev[i]);
      DEBUG_PRINT("Sensor %d ranging status: %d  (0 means ok) \n", i, status);

      if (status == 0)
         I2C_expander_set_pin(LED0, 1);
   }


   uint8_t ranging_ready = 255;
   uint8_t get_data_success = 255;
   uint8_t to_send_buffer[4*NR_OF_PIXELS];
 
   while(1) {
      vTaskDelay(M2T(70));
      vl53l5cx_check_data_ready(&tof_dev[0], &ranging_ready);  // poll for data-ready

      if (ranging_ready == 1) {
         DEBUG_PRINT("Ranging ready");
         get_data_success = vl53l5cx_get_ranging_data(&tof_dev[0], &tof_data);
         if (get_data_success == VL53L5CX_STATUS_OK) {
            for(uint8_t i=0; i<NR_OF_PIXELS; i++)
               DEBUG_PRINT(" %ld \n", (int32_t)tof_data.distance_mm[i]);
            memcpy(&to_send_buffer[0], (uint8_t *)(&tof_data.distance_mm[0]), 2*NR_OF_PIXELS);
            memcpy(&to_send_buffer[2*NR_OF_PIXELS], (uint8_t *)(&tof_data.nb_target_detected[0]), NR_OF_PIXELS);
            memcpy(&to_send_buffer[3*NR_OF_PIXELS], (uint8_t *)(&tof_data.target_status[0]), NR_OF_PIXELS);

            send_command(1, (4*NR_OF_PIXELS)/28 + 1);
            send_data_packet(&to_send_buffer[0], 4*NR_OF_PIXELS);
         }
      }
      ranging_ready = 2;
   }
}


void send_data_packet(uint8_t *data, uint16_t data_len) {
   uint8_t packets_nr = 0;
   if (data_len%28 > 0)
      packets_nr = data_len/28 + 1;
   else
      packets_nr = data_len/28;

   for (uint8_t idx=0; idx<packets_nr; idx++)
      if(data_len - 28*idx >= 28)
         send_data_packet_28b(&data[28*idx], 28, idx);
      else
         send_data_packet_28b(&data[28*idx], data_len - 28*idx, idx);
}


void send_data_packet_28b(uint8_t *data, uint8_t size, uint8_t index) {
   CRTPPacket pk;
   pk.header = CRTP_HEADER(1, 0); // first arg is the port number
   pk.size = size + 2;
   pk.data[0] = 'D';
   pk.data[1] = index;
   memcpy(&(pk.data[2]), data, size);
   crtpSendPacketBlock(&pk);
}

void send_command(uint8_t command, uint8_t arg) {
   CRTPPacket pk;
   pk.header = CRTP_HEADER(1, 0); // first arg is the port number
   pk.size = 5;
   pk.data[0] = 'C';
   pk.data[1] = command;
   pk.data[2] = arg;
   crtpSendPacketBlock(&pk);
}

uint8_t config_sensors(VL53L5CX_Configuration *p_dev, uint16_t new_i2c_address) {
   p_dev->platform = VL53L5CX_DEFAULT_I2C_ADDRESS; // use default adress for first use

   uint8_t status = 0;
   // Initialize the sensor
   status += vl53l5cx_init(p_dev); 

   // Change I2C address
   status += vl53l5cx_set_i2c_address(p_dev, new_i2c_address);
   status += vl53l5cx_set_resolution(p_dev, VL53L5CX_RESOLUTION_8X8);

   // 15Hz frame rate
   status += vl53l5cx_set_ranging_frequency_hz(p_dev, 15);
   status += vl53l5cx_set_target_order(p_dev, VL53L5CX_TARGET_ORDER_CLOSEST);
   status += vl53l5cx_set_ranging_mode(p_dev, VL53L5CX_RANGING_MODE_CONTINUOUS);

   return status;
}