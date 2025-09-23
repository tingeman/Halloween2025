#!/usr/bin/env sh
set -eu

echo "MQTT_ADMIN_PW=$MQTT_ADMIN_PW"
echo "MQTT_DASHBOARD_PW=$MQTT_DASHBOARD_PW"
echo "MQTT_WORKER_PW=$MQTT_WORKER_PW"
echo "MQTT_DEVICE_PW=$MQTT_DEVICE_PW"

OUT="/mosquitto/config/mosquitto_passwd"
TMP="/tmp/mosq_passwd"

# Start clean
: > "$TMP"

# Create or update users non-interactively (-b)
# (-c only on first user to create the file, afterward append)
mosquitto_passwd -c -b "$TMP" admin     "${MQTT_ADMIN_PW:?MQTT_ADMIN_PW missing}"
mosquitto_passwd    -b "$TMP" dashboard "${MQTT_DASHBOARD_PW:?MQTT_DASHBOARD_PW missing}"
mosquitto_passwd    -b "$TMP" worker    "${MQTT_WORKER_PW:?MQTT_WORKER_PW missing}"
mosquitto_passwd    -b "$TMP" device    "${MQTT_DEVICE_PW:?MQTT_DEVICE_PW missing}"

mv "$TMP" "$OUT"
chown mosquitto:mosquitto "$OUT" || true
chmod 700 "$OUT" || true
echo "Wrote $OUT"
