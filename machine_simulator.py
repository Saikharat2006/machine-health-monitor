import json
import random
import time

import paho.mqtt.client as mqtt

BROKER = "broker.hivemq.com"
PREFIX = "ce350_mhm_g1"  # change g1 to your group name (same in dashboard.html)
MOTORS = 3


def on_connect(client, motor, flags, rc, *args):
    client.subscribe(motor.topic("cmd"))
    client.publish(motor.topic("status"), "online", retain=True)
    print(motor.name, "connected to broker")


def on_message(client, motor, msg):
    cmd = msg.payload.decode().strip().lower()
    print(motor.name, "received command:", cmd)
    if cmd == "stop":
        motor.state = "STOPPED"
    elif cmd == "start":
        motor.state = "RUNNING"
    elif cmd == "fault":
        motor.fault = True
    elif cmd == "reset":
        motor.fault = False
        motor.wear = 0.0
        motor.state = "RUNNING"


class Motor:
    def __init__(self, n):
        self.name = "motor" + str(n)
        self.state = "RUNNING"  # RUNNING, STOPPED, FAILED
        self.fault = False
        self.wear = 0.0  # 0 = new bearing, 1 = failed
        self.vib = 2.0  # mm/s
        self.temp = 55.0  # deg C
        self.cur = 8.0  # amps
        self.client = self.make_client()

    def topic(self, leaf):
        return PREFIX + "/" + self.name + "/" + leaf

    def make_client(self):
        try:
            c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        except AttributeError:
            c = mqtt.Client()
        c.user_data_set(self)
        # Last Will: broker publishes "offline" if this device dies
        c.will_set(self.topic("status"), "offline", retain=True)
        c.on_connect = on_connect
        c.on_message = on_message
        c.connect(BROKER, 1883, 60)
        c.loop_start()
        return c

    def step(self):
        if self.state == "RUNNING":
            if self.fault:
                self.wear = min(1.0, self.wear + 0.015)
            else:
                self.wear = max(0.0, self.wear - 0.01)
            target_vib = 2.0 + 8.0 * self.wear
            target_temp = 55.0 + 35.0 * self.wear
            self.cur = 8.0 + 5.0 * self.wear + random.uniform(-0.2, 0.2)
            self.vib = target_vib + random.uniform(-0.2, 0.2)
            if self.wear >= 1.0:
                self.state = "FAILED"
        else:
            target_temp = 30.0
            self.vib = 0.0
            self.cur = 0.0
        self.temp += (target_temp - self.temp) * 0.25

    def health(self):
        if self.state == "FAILED":
            return 0
        pv = min(1, max(0, (self.vib - 3) / 7))
        pt = min(1, max(0, (self.temp - 65) / 25))
        pc = min(1, max(0, (self.cur - 10) / 3))
        return round(100 - 50 * pv - 30 * pt - 20 * pc)

    def publish(self):
        data = {
            "vib": round(self.vib, 2),
            "temp": round(self.temp, 1),
            "cur": round(self.cur, 2),
            "health": self.health(),
            "state": self.state,
        }
        self.client.publish(self.topic("telemetry"), json.dumps(data))
        print(self.name, data)


motors = [Motor(i) for i in range(2, MOTORS + 1)]

try:
    while True:
        for m in motors:
            m.step()
            m.publish()
        time.sleep(1)
except KeyboardInterrupt:
    for m in motors:
        m.client.publish(m.topic("status"), "offline", retain=True)
        m.client.disconnect()
    print("Stopped")
