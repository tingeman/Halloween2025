# libs/py/halloween_common/mqtt_client.py
import json, os
import paho.mqtt.client as mqtt

def make_client(client_id, username, password, host=None, port=None, lwt_topic=None):
    host = host or os.getenv("MQTT_HOST", "mqtt")
    port = int(port or os.getenv("MQTT_PORT", "1883"))
    c = mqtt.Client(client_id=client_id, clean_session=True)
    c.username_pw_set(username, password)
    if lwt_topic:
        c.will_set(lwt_topic, json.dumps({"status":"offline"}), qos=1, retain=True)
    c.connect(host, port, keepalive=30)
    return c

def publish_json(client, topic, payload, retain=False, qos=1):
    client.publish(topic, json.dumps(payload), qos=qos, retain=retain)
