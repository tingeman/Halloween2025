#!/usr/bin/env sh
set -eu

echo "--------------------------------------"
echo "Date: $(date -u || echo unknown)"
echo "Starting MQTT broker entrypoint..."
echo "--------------------------------------"

CFG="/mosquitto/config/mosquitto.conf"
PASS="/mosquitto/config/mosquitto_passwd"
ACL="/mosquitto/config/acl"
PID_FILE="/mosquitto/run/mosquitto.pid"

# List the contents of the config dir for debugging
echo "[mqtt-entrypoint] Listing /mosquitto/config:"
ls -l /mosquitto/config || true

mkdir -p /mosquitto/run
chown mosquitto:mosquitto /mosquitto/run
chmod 775 /mosquitto/run

# Publish uptime to a topic every 5s
PUB_BIN="$(command -v mosquitto_pub || true)"

publish_uptime() {
  # publish every 5s as admin so ACL permits it
  if [ -x "$PUB_BIN" ] && [ -n "${MQTT_ADMIN_USER:-}" ] && [ -n "${MQTT_ADMIN_PW:-}" ]; then
    # wait until broker accepts an authenticated publish (avoid racing with broker startup)
    echo "[mqtt-entrypoint] Waiting for broker to accept authenticated publish..."
    timeout=30
    interval=1
    waited=0
    accepted=0
    while [ $waited -lt $timeout ]; do
      if "$PUB_BIN" -h localhost -p 1883 -u "$MQTT_ADMIN_USER" -P "$MQTT_ADMIN_PW" -q 1 -r -t "halloween/broker/uptime" -m '{}' >/dev/null 2>&1; then
        echo "[mqtt-entrypoint] Broker accepted publish, starting uptime loop"
        accepted=1
        break
      fi
      sleep $interval
      waited=$((waited + interval))
    done

    # only start publisher loop if probe succeeded (accepted=1). Remove this check if you want publisher to always start.
    if [ "$accepted" -ne 1 ]; then
      echo "[mqtt-entrypoint] Skipping uptime publisher because probe failed"
      return  
    fi

    while true; do
      uptime_s=$(( $(date +%s) - START_TS ))
      payload="$(printf '{"uptime_s": %s}' "$uptime_s")"
      # authenticate when publishing; publish retained so late subscribers immediately receive last tick
      "$PUB_BIN" -h localhost -p 1883 -u "$MQTT_ADMIN_USER" -P "$MQTT_ADMIN_PW" -q 1 -r -t "halloween/broker/uptime" -m "$payload" >/dev/null 2>&1 || true
      sleep 5
    done &
  else
    echo "[mqtt-entrypoint] mosquitto_pub not available or admin creds missing; uptime publisher disabled"
  fi
}

START_TS="$(date +%s || echo 0)"


# compute initial hashes (empty if files missing)
hash_of() { [ -f "$1" ] && sha256sum "$1" | awk '{print $1}' || echo "absent"; }
pass_hash="$(hash_of "$PASS")"
acl_hash="$(hash_of "$ACL")"

# start mosquitto in background so we can watch
mosquitto -c "$CFG" &
MOSQ_PID=$!

echo "[mqtt-entrypoint] Started mosquitto (pid $MOSQ_PID)"
echo "[mqtt-entrypoint] Initial passwd hash: $pass_hash"
echo "[mqtt-entrypoint] Initial acl    hash: $acl_hash"

# start optional publisher in background
publish_uptime &

echo "[mqtt-entrypoint] Started uptime publisher (pid $!)"

# small helper to hup safely
hup_mosq() {
  # prefer pid file if present, fallback to bg pid
  if [ -f "$PID_FILE" ]; then
    kill -HUP "$(cat "$PID_FILE")" 2>/dev/null || true
  else
    kill -HUP "$MOSQ_PID" 2>/dev/null || true
  fi
}

# watcher loop (no inotify dependency)
while :; do
  sleep 2
  new_pass="$(hash_of "$PASS")"
  new_acl="$(hash_of "$ACL")"
  if [ "$new_pass" != "$pass_hash" ] || [ "$new_acl" != "$acl_hash" ]; then
    echo "[mqtt-entrypoint] Detected change in passwd/acl — sending SIGHUP"
    pass_hash="$new_pass"
    acl_hash="$new_acl"
    hup_mosq
  fi

  # if mosquitto died, exit (let Docker restart policy handle it)
  if ! kill -0 "$MOSQ_PID" 2>/dev/null; then
    echo "[mqtt-entrypoint] Mosquitto exited; stopping watcher."
    wait "$MOSQ_PID" || true
    exit 1
  fi
done

