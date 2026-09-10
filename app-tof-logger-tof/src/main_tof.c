/* 
 * Copyright (C) 2023 ETH Zurich
 * All rights reserved.
 *
 * This software may be modified and distributed under the terms
 * of the GPL-3.0 license.  See the LICENSE file for details.
 *
 * Authors: Hanna Müller, Vlad Niculescu, Tommaso Polonelli, Iman Ostovar
 */

#include <string.h>
#include <stdint.h>
#include <stdbool.h>

#include "app.h"

/* FreeRTOS includes */
#include "FreeRTOS.h"
#include "task.h"

#include "debug.h"
#include "crtp.h"
#include "vl53l5cx_api.h"
#include "deck.h"
#include "param.h"

#ifdef TOF_OVER_CPX
#include "cpx.h"
#include "cpx_internal_router.h"
#endif

#define  ARM_CM_DEMCR      (*(uint32_t *)0xE000EDFC)
#define  ARM_CM_DWT_CTRL   (*(uint32_t *)0xE0001000)
#define  ARM_CM_DWT_CYCCNT (*(uint32_t *)0xE0001004)

#define DEBUG_MODULE "HELLOWORLD"

//-------------------Control Macros-------------------//
#define SENSOR_FORWARD_ENABLE
#define SEND_DATA
#define ON_BOARD_PROCESS
#define START_FLIGHT

//-------------------Custom libraries-------------------//
#include "I2C_expander.h"

//-------------------Global Defines-------------------//
//Sensors Addresses
#define VL53L5CX_FORWARD_I2C_ADDRESS            ((uint16_t)(VL53L5CX_DEFAULT_I2C_ADDRESS*4))
#define VL53L5CX_BACKWARD_I2C_ADDRESS            ((uint16_t)(VL53L5CX_FORWARD_I2C_ADDRESS+2))
//Data Length
#define ToF_DISTANCES_LEN             (128)
// #define ToF_TARGETS_DETECTED_LEN      (64) TODO : delete
#define ToF_TARGETS_STATUS_LEN        (64)
#define FRONT_SENSOR_OFFSET        (0)
#define BACK_SENSOR_OFFSET        (ToF_DISTANCES_LEN+ToF_TARGETS_STATUS_LEN)



//-------------------Global Variables-------------------//
#ifdef SENSOR_FORWARD_ENABLE
static VL53L5CX_Configuration vl53l5dev_f;
static VL53L5CX_ResultsData vl53l5_res_f;
#endif


// IRQ
volatile uint8_t irq_status = 0;
//uint8_t vl53l5_buffer[VL53L5CX_MAX_RESULTS_SIZE];

uint32_t timestamp;

//-------------------Functions defins-------------------//
#ifdef TOF_OVER_CPX
void send_tof_cpx(uint8_t *dist128, uint8_t *status64);
#else
void send_command(uint8_t command, uint8_t arg);
void send_data_packet(uint8_t *data, uint16_t data_len);
void send_data_packet_28b(uint8_t *data, uint8_t size, uint8_t index);
#endif
//
bool initialize_sensors_I2C(VL53L5CX_Configuration *p_dev, uint8_t mode);
bool config_sensors(VL53L5CX_Configuration *p_dev, uint16_t new_i2c_address);
bool get_sensor_data(VL53L5CX_Configuration *p_dev,VL53L5CX_ResultsData *p_results);

#ifdef START_FLIGHT
uint16_t ToFly = 0;
#else
uint16_t ToFly = 1;
#endif

//MAIN
void appMain()
{ 

  vTaskDelay(M2T(3000)); //no rush to start

  //-----------------------------------Initilaize The Deck -----------------------------------------------------//
  bool gpio_exp_status = false;
  bool sensors_status = true;
  gpio_exp_status = I2C_expander_initialize();
  DEBUG_PRINT("ToFDeck I2C_GPIO Expander: %s\n", gpio_exp_status ? "OK." : "ERROR!");  
  #ifdef SENSOR_FORWARD_ENABLE
    vTaskDelay(M2T(100)); 
    sensors_status = initialize_sensors_I2C(&vl53l5dev_f,1); //forward
    DEBUG_PRINT("ToFDeck Forward Sensor Initlaize 1: %s\n", sensors_status ? "OK." : "ERROR!");
  #endif


  if(gpio_exp_status == false || sensors_status == false)
  {
    DEBUG_PRINT("ERROR LOOP_1!"); 
    while (1)
    {//stay in ERROR LOOP
      vTaskDelay(M2T(10000)); 
    }
  }

  DEBUG_PRINT("ToFDeck GPIO & Interrupt Initlaized. \n");  

  //-----------------------------------Start Sensors Ranging -----------------------------------------------------//
  #ifdef SENSOR_FORWARD_ENABLE
    vTaskDelay(M2T(100));
    uint8_t ranging_start_res_f = vl53l5cx_start_ranging(&vl53l5dev_f);


    DEBUG_PRINT("ToFDeck Start Sensor Forward Ranging: %s\n", (ranging_start_res_f == VL53L5CX_STATUS_OK) ? "OK." : "ERROR!"); 
  #else
    uint8_t ranging_start_res_f = VL53L5CX_STATUS_OK;
  #endif

  if(ranging_start_res_f != VL53L5CX_STATUS_OK){
    DEBUG_PRINT("ERROR LOOP_2!"); 
    while (1)
    {//stay in ERROR LOOP
      vTaskDelay(M2T(10000)); 
    }
  }

  //-----------------------------------Collect and Send Data------------------------------------------------------//

  #ifdef SENSOR_FORWARD_ENABLE
    uint8_t get_data_success_f = false;
    #if defined(SEND_DATA) && !defined(TOF_OVER_CPX)
      uint8_t to_send_buffer_f[ToF_DISTANCES_LEN+ToF_TARGETS_STATUS_LEN];
    #endif
  #endif

  // TODO : delete if second while loop works
  // while(1) {
   
  //   vTaskDelay(M2T(67)); // Task Delay, we want to run this task at 15Hz
  //   // Collect Data
  //   #ifdef SENSOR_FORWARD_ENABLE
  //     get_data_success_f = get_sensor_data(&vl53l5dev_f, &vl53l5_res_f);
  //     if (get_data_success_f == true)
  //     {
  //       //
  //       send_command(1, (ToF_DISTANCES_LEN+ToF_TARGETS_DETECTED_LEN+ToF_TARGETS_STATUS_LEN)/28 + 1);  
  //       //
  //       memcpy(&to_send_buffer_f[0], (uint8_t *)(&vl53l5_res_f.distance_mm[0]), ToF_DISTANCES_LEN);
  //       memcpy(&to_send_buffer_f[ToF_DISTANCES_LEN], (uint8_t *)(&vl53l5_res_f.nb_target_detected[0]), ToF_TARGETS_DETECTED_LEN);
  //       memcpy(&to_send_buffer_f[ToF_DISTANCES_LEN+ToF_TARGETS_DETECTED_LEN], (uint8_t *)(&vl53l5_res_f.target_status[0]), ToF_TARGETS_STATUS_LEN);
  //       //
  //       send_data_packet(&to_send_buffer_f[0], ToF_DISTANCES_LEN+ToF_TARGETS_DETECTED_LEN+ToF_TARGETS_STATUS_LEN);


  //       // Clear Flag
  //       get_data_success_f = false;

  //     }
  //   #endif
  // }

  TickType_t xLastWakeTime = xTaskGetTickCount();
  #ifdef TOF_OVER_CPX
    uint32_t polls_without_data = 0;
    bool first_frame_done = false;
    DEBUG_PRINT("ToF loop start (CPX)\n");
  #endif

  while(1) {
   
    //vTaskDelay(M2T(67)); // Task Delay, we want to run this task at 15Hz
    vTaskDelayUntil(&xLastWakeTime, M2T(67));
    // Collect Data
    #ifdef SENSOR_FORWARD_ENABLE
      get_data_success_f = get_sensor_data(&vl53l5dev_f, &vl53l5_res_f);
      #ifdef TOF_OVER_CPX
        if (!get_data_success_f) {
          polls_without_data++;
          if ((polls_without_data % 450) == 0)   // every ~30 s without a frame
            DEBUG_PRINT("ToF: no data ready (%lu polls)\n", (unsigned long)polls_without_data);
        }
      #endif
      if (get_data_success_f == true)
      {
        #ifdef TOF_OVER_CPX
          if (!first_frame_done) DEBUG_PRINT("ToF: first frame ready, sending over CPX\n");
          // one frame = 3 CPX packets to the wifi host, radio stays free
          send_tof_cpx((uint8_t *)(&vl53l5_res_f.distance_mm[0]), (uint8_t *)(&vl53l5_res_f.target_status[0]));
          if (!first_frame_done) { DEBUG_PRINT("ToF: first frame sent\n"); first_frame_done = true; }
        #else
          //
          send_command(1, (ToF_DISTANCES_LEN+ToF_TARGETS_STATUS_LEN)/28 + 1);
          //
          memcpy(&to_send_buffer_f[0], (uint8_t *)(&vl53l5_res_f.distance_mm[0]), ToF_DISTANCES_LEN);
          memcpy(&to_send_buffer_f[ToF_DISTANCES_LEN], (uint8_t *)(&vl53l5_res_f.target_status[0]), ToF_TARGETS_STATUS_LEN);
          //
          send_data_packet(&to_send_buffer_f[0], ToF_DISTANCES_LEN+ToF_TARGETS_STATUS_LEN);
        #endif

        // Clear Flag
        get_data_success_f = false;

      }
    #endif
  }
}

#ifdef TOF_OVER_CPX
// The UART2 CPX link caps the payload well below 192 bytes, so one 8x8 frame
// goes out as 3 chunks of 64 data bytes each:
//   chunk 0: distance_mm bytes [0:64]
//   chunk 1: distance_mm bytes [64:128]
//   chunk 2: target_status bytes [0:64]
// Header per chunk: magic 'T', frame seq, chunk idx, n chunks, timestamp_ms (u32)
#define TOF_CPX_MAGIC       (0x54)
#define TOF_CPX_CHUNKS      (3)
#define TOF_CPX_CHUNK_DATA  (64)

static CPXPacket_t cpx_tof_packet;
static uint32_t send_timeouts = 0;
static uint32_t frames_sent = 0;

void send_tof_cpx(uint8_t *dist128, uint8_t *status64)
{
  static uint8_t frame_seq = 0;
  static bool route_ready = false;

  if (!route_ready) {
    cpxInitRoute(CPX_T_STM32, CPX_T_WIFI_HOST, CPX_F_APP, &cpx_tof_packet.route);
    // the STM32 cpxInitRoute leaves lastPacket at 0 (the GAP8 lib sets it);
    // every chunk is a self-contained CPX packet, so mark it as such
    cpx_tof_packet.route.lastPacket = true;
    route_ready = true;
  }

  uint32_t timestamp_ms = T2M(xTaskGetTickCount());

  for (uint8_t idx = 0; idx < TOF_CPX_CHUNKS; idx++) {
    cpx_tof_packet.data[0] = TOF_CPX_MAGIC;
    cpx_tof_packet.data[1] = frame_seq;
    cpx_tof_packet.data[2] = idx;
    cpx_tof_packet.data[3] = TOF_CPX_CHUNKS;
    memcpy(&cpx_tof_packet.data[4], (uint8_t *)(&timestamp_ms), 4);
    if (idx < 2)
      memcpy(&cpx_tof_packet.data[8], &dist128[idx * TOF_CPX_CHUNK_DATA], TOF_CPX_CHUNK_DATA);
    else
      memcpy(&cpx_tof_packet.data[8], &status64[0], TOF_CPX_CHUNK_DATA);
    cpx_tof_packet.dataLength = 8 + TOF_CPX_CHUNK_DATA;
    // bounded wait: if the UART2 link to the ESP32 stalls we drop the frame
    // instead of blocking the app task forever
    if (!cpxSendPacketBlockingTimeout(&cpx_tof_packet, M2T(200))) {
      send_timeouts++;
      if (send_timeouts == 1 || (send_timeouts % 150) == 0)
        DEBUG_PRINT("ToF CPX: send timeout #%lu (frame %u chunk %u) - UART2 link to the ESP32 stalled?\n", (unsigned long)send_timeouts, (unsigned)frame_seq, (unsigned)idx);
      break;
    }
  }
  frame_seq++;
  frames_sent++;
  if ((frames_sent % 300) == 0) {   // ~20 s at 15 Hz
    DEBUG_PRINT("ToF CPX: %lu frames sent, %lu send timeouts\n", (unsigned long)frames_sent, (unsigned long)send_timeouts);
  }
}
#endif

#ifndef TOF_OVER_CPX
void send_data_packet(uint8_t *data, uint16_t data_len)
{
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

void send_data_packet_28b(uint8_t *data, uint8_t size, uint8_t index)
{
  CRTPPacket pk;
  pk.header = CRTP_HEADER(1, 0); // first arg is the port number
  pk.size = size + 2;
  pk.data[0] = 'D';
  pk.data[1] = index;
  memcpy(&(pk.data[2]), data, size);
  crtpSendPacketBlock(&pk);
}


void send_command(uint8_t command, uint8_t arg)
{
  //uint32_t timestamp = get_time_stamp();
  CRTPPacket pk;
  pk.header = CRTP_HEADER(1, 0); // first arg is the port number
  pk.size = 7;
  pk.data[0] = 'C';
  pk.data[1] = command;
  pk.data[2] = arg;
  memcpy(&pk.data[3], (uint8_t *)(&timestamp), 4);
  //DEBUG_PRINT("cmd PK 1:%d, 2:%d, 3:%d, 4:%d, ",pk.data[3],pk.data[4],pk.data[5],pk.data[6]); //todo delete
  crtpSendPacketBlock(&pk);
}
#endif /* !TOF_OVER_CPX */

bool config_sensors(VL53L5CX_Configuration *p_dev, uint16_t new_i2c_address)
{
  p_dev->platform = VL53L5CX_DEFAULT_I2C_ADDRESS; // use default adress for first use

  // initialize the sensor
  uint8_t tof_res = vl53l5cx_init(p_dev);   if (tof_res != VL53L5CX_STATUS_OK) return false ;
  //DEBUG_PRINT("ToF Config Result: %d \n", tof_init_res);

  // Configurations
  //change i2c address
  tof_res = vl53l5cx_set_i2c_address(p_dev, new_i2c_address);if (tof_res != VL53L5CX_STATUS_OK) return false ;
  tof_res = vl53l5cx_set_resolution(p_dev, VL53L5CX_RESOLUTION_8X8);if (tof_res != VL53L5CX_STATUS_OK) return false ; 
  // 15hz
  tof_res = vl53l5cx_set_ranging_frequency_hz(p_dev, 15);if (tof_res != VL53L5CX_STATUS_OK) return false ; 
  tof_res = vl53l5cx_set_target_order(p_dev, VL53L5CX_TARGET_ORDER_CLOSEST);if (tof_res != VL53L5CX_STATUS_OK) return false ;
  tof_res = vl53l5cx_set_ranging_mode(p_dev, VL53L5CX_RANGING_MODE_CONTINUOUS);if (tof_res != VL53L5CX_STATUS_OK) return false ;
  //tof_res = vl53l5cx_set_ranging_mode(p_dev, VL53L5CX_RANGING_MODE_AUTONOMOUS);if (tof_res != VL53L5CX_STATUS_OK) return false ;// TODO test it

  //Check for sensor to be alive
  uint8_t isAlive;
  tof_res =vl53l5cx_is_alive(p_dev,&isAlive);if (tof_res != VL53L5CX_STATUS_OK) return false;
  if (isAlive != 1) return false;
  
  // All Good!
  return true;
}

bool initialize_sensors_I2C(VL53L5CX_Configuration *p_dev, uint8_t mode)
{
  bool status = false;

  //reset I2C  //configure pins out/in for forward only

  //status = I2C_expander_set_register(OUTPUT_PORT_REG_ADDRESS,I2C_RST_BACKWARD_PIN,I2C_RST_FORWARD_PIN);if (status == false)return status;

  if (mode == 1 && p_dev != NULL){
    //enable forward only and config
    status = I2C_expander_set_register(OUTPUT_PORT_REG_ADDRESS,LPN_FORWARD_PIN);if (status == false)return status; 
    status = config_sensors(p_dev,VL53L5CX_FORWARD_I2C_ADDRESS);if (status == false)return status; 
  }
  if (mode == 2 && p_dev != NULL){
    //enable backward only and config
    status = I2C_expander_set_register(OUTPUT_PORT_REG_ADDRESS,LPN_BACKWARD_PIN | LED_BACKWARD_PIN); if (status == false)return status; 
    status = config_sensors(p_dev,VL53L5CX_BACKWARD_I2C_ADDRESS);if (status == false)return status; 
  }
  //status = I2C_expander_set_register(OUTPUT_PORT_REG_ADDRESS,0x00); //all off
  if (mode == 3){
    //enable both forward & backward
    status = I2C_expander_set_register(OUTPUT_PORT_REG_ADDRESS,LPN_BACKWARD_PIN | LED_BACKWARD_PIN|LPN_FORWARD_PIN | LED_FORWARD_PIN); if (status == false)return status; 
  }
  return status;
}

bool get_sensor_data(VL53L5CX_Configuration *p_dev,VL53L5CX_ResultsData *p_results){
 
  // Check  for data ready I2c
  uint8_t ranging_ready = 2;
  //ranging_ready --> 0 if data is not ready, or 1 if a new data is ready.
  uint8_t status = vl53l5cx_check_data_ready(p_dev, &ranging_ready);if (status != VL53L5CX_STATUS_OK) return false;

  // 1 Get data in case it is ready
  if (ranging_ready == 1){
    status = vl53l5cx_get_ranging_data(p_dev, p_results);if (status != VL53L5CX_STATUS_OK) return false;
  }else {
    //0  data in not ready yet
    return false;
  }

  // All good then
  //return false;// TODO deleet
  return true;
}

PARAM_GROUP_START(ToF_FLY_PARAMS)
PARAM_ADD(PARAM_UINT16, ToFly, &ToFly)
PARAM_GROUP_STOP(ToF_FLY_PARAMS)