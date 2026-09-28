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
#include "vl53l5cx_api.h"
#include "deck.h"
#include "param.h"
#include "log.h"
#include "uart1.h"
#include "commander.h"
#include "supervisor.h"

#define  ARM_CM_DEMCR      (*(uint32_t *)0xE000EDFC)
#define  ARM_CM_DWT_CTRL   (*(uint32_t *)0xE0001000)
#define  ARM_CM_DWT_CYCCNT (*(uint32_t *)0xE0001004)

#define DEBUG_MODULE "HELLOWORLD"

//-------------------Control Macros-------------------//
#define SENSOR_FORWARD_ENABLE
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

//-------------------Serial link to the Duo S-------------------//
// UART1 of the expansion port (TX1/RX1 pins), 115200 8N1. Frame layout, same
// as in milkv/common/protocol.py:
//   AA 55 | type | len | payload | xor of type, len and payload
#define UART_BAUD   115200
#define UART_TOF    'T'   // out: seq u8, timestamp_ms u32, 128 B distances, 64 B target status
#define UART_STATE  'S'   // out: z, roll, pitch, yaw (float), tumbled u8
#define UART_CMD    'C'   // in:  sp_type u8, vx, vy, yawrate, zdistance (float)
#define SP_HOVER    1
#define SP_STOP     2
#define SP_UNLOCK   3

struct __attribute__((packed)) state_payload { float z, roll, pitch, yaw; uint8_t tumbled; };
struct __attribute__((packed)) cmd_payload { uint8_t sp_type; float vx, vy, yawrate, zdistance; };

static logVarId_t id_z, id_roll, id_pitch, id_yaw, id_tumbled;

static void send_tof(uint8_t *dist128, uint8_t *status64);
static void send_state(void);
static void uart_rx_task(void *param);
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
  #endif

  uart1Init(UART_BAUD);
  xTaskCreate(uart_rx_task, "uartRx", 2 * configMINIMAL_STACK_SIZE, NULL, 2, NULL);
  id_z = logGetVarId("stateEstimate", "z");
  id_roll = logGetVarId("stateEstimate", "roll");
  id_pitch = logGetVarId("stateEstimate", "pitch");
  id_yaw = logGetVarId("stateEstimate", "yaw");
  id_tumbled = logGetVarId("sys", "isTumbled");
  DEBUG_PRINT("ToF loop start, UART1 at %d\n", UART_BAUD);

  TickType_t xLastWakeTime = xTaskGetTickCount();
  while(1) {
    vTaskDelayUntil(&xLastWakeTime, M2T(67));   // 15 Hz, the ToF rate
    send_state();
    #ifdef SENSOR_FORWARD_ENABLE
      get_data_success_f = get_sensor_data(&vl53l5dev_f, &vl53l5_res_f);
      if (get_data_success_f == true)
      {
        send_tof((uint8_t *)(&vl53l5_res_f.distance_mm[0]), (uint8_t *)(&vl53l5_res_f.target_status[0]));
        get_data_success_f = false;
      }
    #endif
  }
}

static void uart_send_frame(uint8_t type, const uint8_t *payload, uint8_t len)
{
  static uint8_t buf[5 + 255];
  buf[0] = 0xAA; buf[1] = 0x55; buf[2] = type; buf[3] = len;
  uint8_t x = type ^ len;
  for (uint8_t i = 0; i < len; i++) { buf[4 + i] = payload[i]; x ^= payload[i]; }
  buf[4 + len] = x;
  // byte by byte, the DMA variant only has a 64 byte buffer and a ToF frame is 202
  uart1SendData(5 + len, buf);
}

static void send_tof(uint8_t *dist128, uint8_t *status64)
{
  static uint8_t payload[5 + 128 + 64];
  static uint8_t seq = 0;
  uint32_t timestamp_ms = T2M(xTaskGetTickCount());
  payload[0] = seq++;
  memcpy(&payload[1], &timestamp_ms, 4);
  memcpy(&payload[5], dist128, 128);
  memcpy(&payload[133], status64, 64);
  uart_send_frame(UART_TOF, payload, sizeof(payload));
}

static void send_state(void)
{
  struct state_payload s = {
    logGetFloat(id_z), logGetFloat(id_roll), logGetFloat(id_pitch), logGetFloat(id_yaw),
    (uint8_t)logGetUint(id_tumbled),
  };
  uart_send_frame(UART_STATE, (uint8_t *)&s, sizeof(s));
}

static void handle_cmd(const struct cmd_payload *c)
{
  static setpoint_t sp;
  memset(&sp, 0, sizeof(sp));
  if (c->sp_type == SP_HOVER) {
    // same fields the hover packet of the CRTP generic commander sets
    sp.mode.z = modeAbs;
    sp.position.z = c->zdistance;
    sp.mode.yaw = modeVelocity;
    sp.attitudeRate.yaw = c->yawrate;
    sp.mode.x = modeVelocity;
    sp.mode.y = modeVelocity;
    sp.velocity.x = c->vx;
    sp.velocity.y = c->vy;
    sp.velocity_body = true;
  } else if (c->sp_type == SP_UNLOCK) {
    supervisorRequestArming(true);
  }
  // stop and unlock hand over the all-zero setpoint: motors off, commander watchdog fed
  commanderSetSetpoint(&sp, COMMANDER_PRIORITY_CRTP);
}

// reads the command frames from the Duo S byte by byte
static void uart_rx_task(void *param)
{
  static uint8_t payload[255];
  uint8_t byte, type = 0, len = 0, pos = 0, x = 0;
  int state = 0;   // 0/1: sync bytes, 2: type, 3: len, 4: payload, 5: checksum
  while (1) {
    if (!uart1GetDataWithTimeout(&byte, M2T(100))) continue;
    switch (state) {
      case 0: state = (byte == 0xAA) ? 1 : 0; break;
      case 1: state = (byte == 0x55) ? 2 : (byte == 0xAA) ? 1 : 0; break;
      case 2: type = byte; x = byte; state = 3; break;
      case 3: len = byte; x ^= byte; pos = 0; state = len ? 4 : 5; break;
      case 4: payload[pos++] = byte; x ^= byte; if (pos == len) state = 5; break;
      case 5:
        if (byte == x && type == UART_CMD && len == sizeof(struct cmd_payload))
          handle_cmd((const struct cmd_payload *)payload);
        state = 0;
        break;
    }
  }
}

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