#!/usr/bin/env python3
"""
Cleanup script to remove old retained MQTT messages.

This script publishes empty retained messages to old topic names that were
changed during refactoring. This clears them from the MQTT broker.

Run this script after updating the worker code to clean up old topics.
"""

import paho.mqtt.client as mqtt
import time
from pathlib import Path

# MQTT broker configuration
# Note: The broker is running in Docker, so use localhost if running this script on the host
# or use "mqtt" if running inside a Docker container
MQTT_BROKER = "localhost"  # Change to "mqtt" if running inside Docker
MQTT_PORT = 1883


def load_mqtt_credentials():
    """Load MQTT credentials from config/secrets/mqtt_users.env"""
    secrets_file = Path(__file__).parent / "config" / "secrets" / "mqtt_users.env"
    
    if not secrets_file.exists():
        print(f"⚠ Warning: Secrets file not found at {secrets_file}")
        print("  Attempting anonymous connection")
        return None, None
    
    credentials = {}
    with open(secrets_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                credentials[key] = value
    
    # Use admin credentials for full access to clear retained messages
    username = credentials.get('MQTT_ADMIN_USER')
    password = credentials.get('MQTT_ADMIN_PW')
    
    if username and password:
        print(f"✓ Loaded credentials from {secrets_file}")
        print(f"  Using user: {username}")
        return username, password
    else:
        print(f"⚠ Warning: Could not find MQTT_ADMIN_USER/MQTT_ADMIN_PW in {secrets_file}")
        print("  Attempting anonymous connection")
        return None, None


MQTT_USERNAME, MQTT_PASSWORD = load_mqtt_credentials()

# Old topic patterns to clear (for both tesla_hue_nest and thriller_hue_nest)
PROPS = ["tesla_hue_nest", "thriller_hue_nest"]

OLD_TOPICS_TO_CLEAR = [
    # Old chromecast topics
    "chromecast/State",
    "chromecast/speakers",
    "chromecast/state",
    
    # Old hue topics
    "hue/lights",
    "hue/sensors",
    
    # Old speaker topics (intermediate renames)
    "speakers/Connected",
    "speakers/Count",
    
    # Old non-prefixed summary topics (from initialization)
    "lights",
    "sensors",
    "speakers",
    "state",
    "Connected",
    
    # Old hue/tesla state topics (status messages, not actual state)
    "hue/state",
    "tesla/state",
]


def clear_retained_message(client, topic):
    """Publish an empty retained message to clear a topic."""
    result = client.publish(topic, payload=None, qos=1, retain=True)
    if result.rc == mqtt.MQTT_ERR_SUCCESS:
        print(f"✓ Cleared: {topic}")
    else:
        print(f"✗ Failed to clear: {topic} (error code: {result.rc})")


def on_connect(client, userdata, flags, rc):
    """Callback for when the client connects to the broker."""
    if rc == 0:
        print("✓ Connected to MQTT broker successfully")
        userdata['connected'] = True
    else:
        print(f"✗ Connection failed with code {rc}")
        userdata['connected'] = False


def main():
    print("=" * 70)
    print("MQTT Retained Message Cleanup Script")
    print("=" * 70)
    print(f"\nConnecting to MQTT broker at {MQTT_BROKER}:{MQTT_PORT}...")
    
    # Create MQTT client with callback API version
    client = mqtt.Client(client_id="cleanup_script", protocol=mqtt.MQTTv311)
    
    # Set up connection tracking
    userdata = {'connected': False}
    client.user_data_set(userdata)
    client.on_connect = on_connect
    
    # Set credentials if needed
    if MQTT_USERNAME:
        if MQTT_PASSWORD:
            client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
            print(f"Using credentials: {MQTT_USERNAME}/<password>")
        else:
            # Try with username only (some brokers allow this)
            client.username_pw_set(MQTT_USERNAME, None)
            print(f"Using username: {MQTT_USERNAME} (no password)")
    else:
        print("Attempting anonymous connection...")
    
    try:
        # Connect to broker
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        client.loop_start()
        
        # Wait for connection
        timeout = 5
        start = time.time()
        while not userdata['connected'] and (time.time() - start) < timeout:
            time.sleep(0.1)
        
        if not userdata['connected']:
            print("✗ Failed to connect to MQTT broker within timeout")
            return 1
        
        print("\nClearing old retained messages...\n")
        
        # Clear old topics for each prop
        for prop in PROPS:
            print(f"\n--- Prop: {prop} ---")
            for old_topic in OLD_TOPICS_TO_CLEAR:
                full_topic = f"halloween/{prop}/telemetry/{old_topic}"
                clear_retained_message(client, full_topic)
                time.sleep(0.1)  # Small delay between messages
        
        # Give messages time to be sent
        print("\nWaiting for messages to be sent...")
        time.sleep(2)
        
        client.loop_stop()
        client.disconnect()
        
        print("\n" + "=" * 70)
        print("Cleanup complete!")
        print("=" * 70)
        print("\nOld retained messages have been cleared from the MQTT broker.")
        print("You can now restart your workers to see only the new topic structure.")
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        print("\nMake sure:")
        print("  1. The MQTT broker is running")
        print("  2. The broker address/port are correct")
        print("  3. The credentials are correct (if authentication is enabled)")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
