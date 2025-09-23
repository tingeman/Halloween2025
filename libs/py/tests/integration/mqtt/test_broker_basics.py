import os
import json
import time
import socket
import pytest
import paho.mqtt.client as mqtt

try:
    import ipdb as pdb  # Use ipdb if available for better debugging experience
except ImportError:
    import pdb    # Fallback to standard pdb if ipdb is not installed

BROKER_HOST = os.getenv("MQTT_HOST", "localhost")
BROKER_PORT = int(os.getenv("MQTT_PORT", "1883"))
ADMIN_USER  = os.getenv("MQTT_ADMIN_USER", "admin")
ADMIN_PW    = os.getenv("MQTT_ADMIN_PW", "admin")
DEVICE_USER = os.getenv("MQTT_DEVICE_USER", "device")
DEVICE_PW   = os.getenv("MQTT_DEVICE_PW", "device")

@pytest.fixture
def make_client():
    clients = []
    def _mk(client_id, user=None, pw=None, port=BROKER_PORT, transport="tcp", clean=True, keepalive=20):
        # Use VERSION2 callback API and default protocol (MQTTv5)
        c = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, 
            client_id=client_id, 
            clean_session=clean,
            transport=transport
        )
        if user:
            c.username_pw_set(user, pw)
        clients.append(c)
        return c
    
    yield _mk

    # Clean up all clients at the end of the test
    for c in clients:
        try:
            c.loop_stop()
            c.disconnect()
        except:
            pass

def _drain(client, timeout=2.0):
    # Pump network loop for a bit to receive messages
    t0 = time.time()
    while time.time() - t0 < timeout:
        client.loop(timeout=0.1)

def test_connect_as_admin(make_client):
    c = make_client("test_admin", ADMIN_USER, ADMIN_PW)
    c.connect(BROKER_HOST, BROKER_PORT)
    c.loop_start()
    # Admin can RW any topic
    topic = "halloween/test_admin/smoke"
    assert c.publish(topic, "ok", qos=1).rc == mqtt.MQTT_ERR_SUCCESS
    c.loop_stop(); c.disconnect()

def test_device_can_only_access_own_namespace(make_client):
    prop_id = "coffin_jumper"
    other_prop_id = "other_prop"
    own_status_topic = f"halloween/{prop_id}/status"
    other_status_topic = f"halloween/{other_prop_id}/status"

    # 1. Admin client to listen on the "forbidden" topic
    received_msgs = []
    def on_message(client, userdata, msg):
        received_msgs.append(msg)

    admin_sub = make_client("admin_subscriber", ADMIN_USER, ADMIN_PW)
    admin_sub.on_message = on_message
    admin_sub.subscribe(other_status_topic)
    admin_sub.connect(BROKER_HOST, BROKER_PORT)
    admin_sub.loop_start()

    # 2. Device client to test publishing
    device_client = make_client(prop_id, DEVICE_USER, DEVICE_PW)
    device_client.connect(BROKER_HOST, BROKER_PORT)
    device_client.loop_start()

    # This publish should succeed
    rc = device_client.publish(own_status_topic, json.dumps({"status": "online"}), qos=1).rc
    assert rc == mqtt.MQTT_ERR_SUCCESS

    # This publish should be blocked by the broker's ACL
    device_client.publish(other_status_topic, "unauthorized_payload", qos=1)

    # 3. Wait and verify no message was received by the admin
    time.sleep(1.0) # Give broker time to process and (not) deliver the message

    assert len(received_msgs) == 0, "Device was able to publish to a forbidden topic"

    # Cleanup
    admin_sub.loop_stop(); admin_sub.disconnect()
    device_client.loop_stop(); device_client.disconnect()

def test_retained_status_roundtrip(make_client):
    """
    Tests that a message published with the retain flag is immediately
    received by a new subscriber that connects after the message was sent.
    """
    prop_id = "smoke_prop"
    status_topic = f"halloween/{prop_id}/status"

    # Publisher: set retained status
    pub = make_client(prop_id, DEVICE_USER, DEVICE_PW)
    pub.connect(BROKER_HOST, BROKER_PORT)
    pub.loop_start()
    pub.publish(status_topic, json.dumps({"status":"online"}), qos=1, retain=True)
    _drain(pub, 0.5)
    pub.loop_stop(); pub.disconnect()

    # print("\nPublisher has finished. Check for the retained message now.")
    # pdb.set_trace()
    # The broker successfully accepted the retained message and subsequent subscribers receive it.

    # Fresh subscriber should immediately get the retained msg
    got = {}
    def on_msg(_c, _u, msg):
        print(f"DEBUG: on_msg received: {msg.payload.decode()}")
        got["payload"] = msg.payload.decode()

    def on_connect(client, userdata, flags, rc, properties):
        print(f"DEBUG: on_connect fired with rc={rc}")
        # Subscribe from within on_connect to guarantee subscription happens after connection.
        client.subscribe(status_topic, qos=1)

    def on_log(client, userdata, level, buf):
        print(f"DEBUG: paho-log: {buf}")

    sub = make_client("reader", ADMIN_USER, ADMIN_PW)
    sub.on_message = on_msg
    sub.on_connect = on_connect
    sub.on_log = on_log  # <-- Add the log callback
    sub.connect(BROKER_HOST, BROKER_PORT)

    # Using loop_start() is more robust for catching immediate retained messages
    sub.loop_start()
    print("DEBUG: Subscriber loop started, waiting for 1 second...")
    time.sleep(1.0) # Give the background thread time to process the message
    sub.loop_stop()
    print("DEBUG: Subscriber loop stopped.")
    sub.disconnect()

    assert "payload" in got, "No retained status received"
    assert json.loads(got["payload"]).get("status") == "online"


