import os
import time
import pytest
import paho.mqtt.client as mqtt

try:
    import ipdb as pdb  # Use ipdb if available for better debugging experience
except ImportError:
    import pdb    # Fallback to standard pdb if ipdb is not installed

BROKER_HOST = os.getenv("MQTT_HOST", "localhost")
BROKER_PORT = int(os.getenv("MQTT_PORT", "1883"))

def test_anonymous_denied():
    # We should not be able to connect with no credentials
    # The on_connect callback will receive a non-zero return code.
    connect_rc = -1

    def on_connect(client, userdata, flags, reason_code, properties):
        nonlocal connect_rc
        connect_rc = reason_code

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="anon_try")
    c.on_connect = on_connect
    c.connect(BROKER_HOST, BROKER_PORT, 10)
    c.loop_start()
    time.sleep(1) # Allow time for connection attempt
    c.loop_stop()
    
    try:
        c.disconnect()
    except:
        pass # Ignore disconnect errors
    
    # RC 5 is "Connection refused - not authorised"
    assert str(connect_rc) == "Not authorized", f"Expected RC 135 (Not Authorised), but got {connect_rc}"
