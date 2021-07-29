/*
Stepper controller via serial connection.

Baud rate is set by a constant to be 115200.

Waits for the number of steps to traverse as an interger between -LIMIT to +LIMIT, where:
{abs(LIMIT) <= 400} for the model 42BYGHM809.

The speed is set via DELAY_TIME.

Sends INIT_MSG set to "OK" when initiating a serial connection or upon receiving "echo" or "Echo".

Stepper driver is DRV8825.

STEPS:
400 steps - 360 deg.
200 steps - 180 deg.
100 steps - 90 deg.
*/

#define ENABLE_PIN        8
#define X_DIRECTION_PIN     5
#define X_STEP_PIN     2
#define BAUDRATE 115200
#define SERIAL_TIMEOUT_MILISECONDS 500
#define CLOCKWISE true
#define COUNTER_CLOCKWISE false
#define DELAY_TIME
#define MSG_TERMINATOR  '\n'
#define INIT_MSG  "OK"

int delayTimePulse = 500; // Delay for pulses (uS) (400 - inf). Affects speed.


void setup(){
  Serial.begin(BAUDRATE);
  Serial.setTimeout(SERIAL_TIMEOUT_MILISECONDS);
  Serial.write(INIT_MSG);

  // Assign pins to outputs
  pinMode(X_DIRECTION_PIN, OUTPUT);
  pinMode(X_STEP_PIN, OUTPUT);

  // Set ENABLDE pin to LOW
  pinMode(ENABLE_PIN, OUTPUT);
  digitalWrite(ENABLE_PIN, LOW);
}


void loop() {
  if (Serial.available() > 0){
    String incomingMsg = Serial.readStringUntil(MSG_TERMINATOR);
    incomingMsg.toLowerCase();

    if (incomingMsg.indexOf("echo") > -1)
      Serial.println(INIT_MSG);
    else if (incomingMsg.indexOf("speed") > -1){
      int speed = incomingMsg.substring(5).toInt();
      if (speed < 400 | speed > 5000)
        Serial.println("Speed must be between 400 to 5000");
      else{
        delayTimePulse = speed;
        Serial.println(speed);
      }
    }
    else{
      int numOfSteps = incomingMsg.toInt();
      boolean spinDirection = numOfSteps > 0;
      Serial.println(numOfSteps);
      takeStep(spinDirection, X_DIRECTION_PIN, X_STEP_PIN, numOfSteps);
    }
  }
}


void takeStep(boolean dir, byte dirPin, byte stepperPin, int numOfSteps){
  digitalWrite(dirPin, dir);
  delay(50);
  for (int i = 0; i < abs(numOfSteps); i++) {
    digitalWrite(stepperPin, HIGH);
    delayMicroseconds(delayTimePulse);
    digitalWrite(stepperPin, LOW);
    delayMicroseconds(delayTimePulse);
  }
}
