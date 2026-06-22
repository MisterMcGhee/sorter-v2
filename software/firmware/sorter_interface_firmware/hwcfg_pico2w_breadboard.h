// Pico 2W (RP2350) breadboard — feeder bring-up: C2, C3, C4 active; C1 reserved.
//
// Wiring source: three_motor_wiring_reference.html
//   BTT TMC2209 ×3 in STEP/DIR (standalone) mode — NO UART wired.
//   MS1/MS2 tied to GND on every driver => 1/8 microstepping (hardware-fixed).
//   Motor run current is set by each driver's VREF potentiometer, NOT software.
//   (Pots have been dialed in and verified with the MicroPython spin test.)
//
// IMPORTANT: This board is an RP2350 (Pico 2 W). Configure CMake with
//   -DPICO_BOARD=pico2_w
// otherwise the SDK builds an RP2040 binary that will not run here.

const char* const HW_ID = "pico2w_breadboard";

// Three drivers wired. Mapped to C2, C3, C4 (classification). C1 (bulk bin)
// is not installed yet — its pins are RESERVED below; see "ENABLING C1".
const uint8_t STEPPER_COUNT = 3;

// Active channel wiring (from the three-motor reference):
//   Motor 1: STEP=GP2  DIR=GP3  EN=GP4   -> C2 (second_c_channel_rotor)
//   Motor 2: STEP=GP5  DIR=GP6  EN=GP7   -> C3 (third_c_channel_rotor)
//   Motor 3: STEP=GP8  DIR=GP9  EN=GP10  -> C4 (classification, "carousel")
const uint8_t STEPPER_STEP_PINS[] = {2, 5, 8};
const uint8_t STEPPER_DIR_PINS[]  = {3, 6, 9};

// These exact names are how the backend discovers each channel. C4's
// classification motor must be named "carousel" — the classification_channel
// machine setup aliases it to the classification channel at runtime.
// Logical remapping (which physical motor is which channel) and spin-direction
// flips are also possible at runtime via machine.toml [stepper_bindings] /
// [stepper_direction_inverts] with no reflash.
#ifdef FIRMWARE_ROLE_DISTRIBUTION
const char* const STEPPER_NAMES[] = {
    "distribution_aux_1",
    "distribution_aux_2",
    "chute_stepper"
};
#else
const char* const STEPPER_NAMES[] = {
    "second_c_channel_rotor",   // C2  (Motor 1, GP2/3/4)
    "third_c_channel_rotor",    // C3  (Motor 2, GP5/6/7)
    "carousel"                  // C4 classification (Motor 3, GP8/9/10)
};
#endif

// --- TMC2209 UART: NOT WIRED on this breadboard ---------------------------
// The drivers run standalone (STEP/DIR). The firmware still compiles a UART
// bus and emits config writes at boot; with nothing connected to PDN_UART
// those writes are uart_write_blocking() into the void (non-blocking, never
// waits for a reply) and are simply ignored by the hardware. Pins below are
// otherwise-unused GPIOs so the UART peripheral has somewhere to point.
#define TMC_UART_BUS_COUNT 1
uart_inst_t* const TMC_UART_BUSES[] = {uart0};
const int TMC_UART_BUS_TX_PINS[] = {0};   // GP0 — not connected
const int TMC_UART_BUS_RX_PINS[] = {1};   // GP1 — not connected
const int TMC_UART_BAUDRATE = 400000;

// Addresses are irrelevant without UART; kept distinct for completeness.
const uint8_t TMC_UART_BUS_INDEX[] = {0, 0, 0};
const uint8_t TMC_UART_ADDRESSES[] = {0, 1, 2};

// nEN (enable) is active-LOW, wired per motor to GP4 / GP7 / GP10.
const int STEPPER_nEN_PINS[] = {4, 7, 10};

// DIAG/StallGuard not wired — -1 disables per-channel stall checking.
const int STEPPER_DIAG_PINS[] = {-1, -1, -1};

// --- ENABLING C1 (bulk bin rotor) LATER -----------------------------------
// When the 4th driver is added on the breadboard, wire it to these RESERVED
// free GPIOs and switch this file to 4 steppers:
//   C1: STEP=GP11  DIR=GP12  EN=GP13   (all currently unused)
// Then make ALL of the following length-4, appending the C1 entry LAST:
//   STEPPER_COUNT          = 4
//   STEPPER_STEP_PINS[]    = {2, 5, 8, 11}
//   STEPPER_DIR_PINS[]     = {3, 6, 9, 12}
//   STEPPER_NAMES[] (feeder) append:  "first_c_channel_rotor"
//   STEPPER_NAMES[] (distribution) append:  "distribution_aux_3"
//   STEPPER_nEN_PINS[]     = {4, 7, 10, 13}
//   STEPPER_DIAG_PINS[]    = {-1, -1, -1, -1}
//   TMC_UART_BUS_INDEX[]   = {0, 0, 0, 0}
//   TMC_UART_ADDRESSES[]   = {0, 1, 2, 3}
// Dial in the new driver's VREF pot before driving it (as with the others).

// No endstops wired (classification uses optical spoke homing later).
const uint8_t DIGITAL_INPUT_COUNT = 0;
const int digital_input_pins[] = {0};

const uint8_t DIGITAL_OUTPUT_COUNT = 0;
const int digital_output_pins[] = {0};
const int FAN0_OUTPUT_CHANNEL = -1;

// I2C for PCA9685 servo expansion — not wired. Backend should run with
// `--disable servos`. Pins point at free GPIOs so the firmware compiles/boots.
i2c_inst_t* const I2C_PORT = i2c0;
const int I2C_SDA_PIN = 20;   // GP20 — not connected
const int I2C_SCL_PIN = 21;   // GP21 — not connected

const uint8_t SERVO_I2C_ADDRESS = 0x40;
