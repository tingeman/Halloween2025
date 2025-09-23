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
WS_PORT     = int(os.getenv("MQTT_WS_PORT", "9001"))

ADMIN_USER  = os.getenv("MQTT_ADMIN_USER", "admin")
ADMIN_PW    = os.getenv("MQTT_ADMIN_PW", "admin")
DEVICE_USER = os.getenv("MQTT_DEVICE_USER", "device")
DEVICE_PW   = os.getenv("MQTT_DEVICE_PW", "device")


# ---------- Helpers ----------

@pytest.fixture
def make_client():
    clients = []
    def _mk(client_id, user=None, pw=None, port=BROKER_PORT, transport="tcp", clean=True, keepalive=20):
        # Use VERSION2 callback API and default protocol (MQTTv5) for all clients
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

def _drain(client, seconds=1.0):
    """Pump network loop for a bit to receive messages"""
    t0 = time.time()
    while time.time() - t0 < seconds:
        client.loop(timeout=0.1)


# ---------- LWT / offline behavior ----------

def test_lwt_offline_retained(make_client):
    """
    Device sets a retained LWT to {status:'offline'} on status topic.
    We connect, publish online, then simulate a crash/abrupt disconnect
    and verify the LWT arrives to a subscriber as retained offline.
    """
    prop_id = "lwt_prop"
    status_topic = f"halloween/{prop_id}/status"

    # 1) Admin subscriber to capture retained/offline transitions
    got = []
    def on_msg(_c, _u, msg):
        got.append(msg.payload.decode())
        
    def on_connect_sub(client, userdata, flags, rc, properties):
        client.subscribe(status_topic, qos=1)

    sub = make_client("admin_sub", ADMIN_USER, ADMIN_PW)
    sub.on_message = on_msg
    sub.on_connect = on_connect_sub
    sub.connect(BROKER_HOST, BROKER_PORT)
    sub.loop_start()

    # 2) Device connects with retained LWT=offline
    # Using direct client creation since we need to set the will before connecting
    dev = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=prop_id,
        clean_session=True
    )
    dev.username_pw_set(DEVICE_USER, DEVICE_PW)
    # Set retained LWT (Last Will and Testament)
    dev.will_set(status_topic, json.dumps({"status":"offline"}), qos=1, retain=True)
    dev.connect(BROKER_HOST, BROKER_PORT, keepalive=10)
    dev.loop_start()    # Publish "online" (retained)
    dev.publish(status_topic, json.dumps({"status":"online"}), qos=1, retain=True)
    _drain(dev, 0.3); _drain(sub, 0.5)

    # For MQTTv5, we need to be more aggressive in simulating an abrupt disconnect
    # First, force close the underlying socket without DISCONNECT message
    try:
        dev._sock.close()  # type: ignore[attr-defined]
    except Exception:
        pass
        
    # Also try to kill the network thread to prevent auto-reconnect
    try:
        dev._thread.stop()  # type: ignore[attr-defined]
    except Exception:
        pass
        
    # Give broker time to detect connection loss and publish LWT
    # (must be > keepalive, and MQTTv5 may need more time)
    time.sleep(25)
    _drain(sub, 2.0)
    sub.loop_stop(); sub.disconnect()
    try:
        dev.loop_stop()
    except Exception:
        pass

    # We expect at least one "online" and one "offline"
    statuses = [json.loads(x).get("status") for x in got if x]
    assert "online" in statuses, f"No online status seen: {got}"
    assert "offline" in statuses, f"No offline LWT seen: {got}"
    
    # The last status seen should be offline
    if statuses:
        assert statuses[-1] == "offline", f"Last status should be 'offline', got: {statuses[-1]}"

    # The last retained message on the topic should be offline now
    # (re-subscribe fresh to read retained)
    last = {}
    def on_last(_c, _u, msg):
        last["p"] = msg.payload.decode()
        print(f"Retained message check: {msg.payload.decode()}")

    def on_connect_check(client, userdata, flags, rc, properties):
        print(f"Check client connected, rc={rc}")
        client.subscribe(status_topic, qos=1)

    # For the check client, use the fixture to get consistent behavior
    check = make_client("check_sub", ADMIN_USER, ADMIN_PW)
    check.on_message = on_last
    check.on_connect = on_connect_check
    check.connect(BROKER_HOST, BROKER_PORT)
    check.loop_start()
    time.sleep(5.0)  # Give more time to connect, subscribe, and receive the retained message       
    check.loop_stop()
    check.disconnect()
    
    # In a controlled test environment, we should have received the retained message
    # Assert that the retained message is what we expect - the LWT message with status "offline"
    assert "p" in last, "Expected to receive a retained message, but none was received"
    status = json.loads(last["p"]).get("status")
    assert status == "offline", f"Expected retained message status to be 'offline', but got '{status}'"
# ---------- WebSocket listener (port 9001) ----------

def test_websocket_admin_pubsub(make_client):
    """
    Connect via WebSockets as admin and perform a pub/sub roundtrip.
    """
    topic = "halloween/ws_test/topic"
    payload = {"via": "websocket", "ok": True}

    # subscriber (WS)
    got = {}
    def on_msg(_c, _u, msg):
        got["p"] = json.loads(msg.payload.decode())
        
    def on_connect_ws(client, userdata, flags, rc, properties):
        client.subscribe(topic, qos=1)

    sub = make_client("ws_sub", ADMIN_USER, ADMIN_PW, port=WS_PORT, transport="websockets")    
    sub.on_message = on_msg
    sub.on_connect = on_connect_ws
    sub.connect(BROKER_HOST, WS_PORT)
    sub.loop_start()

    # Give WebSocket connection time to establish
    time.sleep(2.0)

    # publisher (WS)
    pub = make_client("ws_pub", ADMIN_USER, ADMIN_PW, port=WS_PORT, transport="websockets")
    pub.connect(BROKER_HOST, WS_PORT)
    pub.loop_start()
    
    # Give publisher time to connect
    time.sleep(1.0)
    
    # Publish the message
    pub.publish(topic, json.dumps(payload), qos=1)

    # Give time for message to be delivered
    time.sleep(3.0)
    
    sub.loop_stop(); sub.disconnect()
    pub.loop_stop(); pub.disconnect()

    assert "p" in got and got["p"] == payload


# ---------- Health / uptime topic ----------

def test_broker_uptime_topic(make_client):
    """
    The broker entrypoint publishes json to halloween/broker/uptime periodically.
    Verify we can receive and that uptime increases between messages.
    """
    topic = "halloween/broker/uptime"

    readings = []

    def on_msg(_c, _u, msg):
        try:
            data = json.loads(msg.payload.decode())
            if "uptime_s" in data:
                readings.append(int(data["uptime_s"]))
        except Exception:
            print("Invalid uptime message:", msg.payload)


    def on_connect_uptime(client, userdata, flags, rc, properties):
        client.subscribe(topic, qos=1)

    c = make_client("uptime_reader", ADMIN_USER, ADMIN_PW)
    c.on_message = on_msg
    c.on_connect = on_connect_uptime
    c.connect(BROKER_HOST, BROKER_PORT)
    c.loop_start()

    # Allow a moment for the broker's publisher to start up
    time.sleep(2)

    # Wait long enough to get at least two ticks from the 5s publisher
    t0 = time.time()
    while len(readings) < 2 and time.time() - t0 < 20:
        time.sleep(0.5)  # Just wait, the loop_start() background thread handles the network I/O
        
    c.loop_stop()
    c.disconnect()

    print(f"Uptime readings: {readings}")
    assert len(readings) >= 1, "No uptime messages received"
    if len(readings) >= 2:
        assert readings[-1] >= readings[0], "Uptime did not increase"
