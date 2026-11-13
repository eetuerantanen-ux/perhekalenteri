#!/bin/bash
# Run the Vesiportaali water collector at a random minute between :07 and :21
# during the 07-23 daytime window, so the outbound requests do not look
# mechanical. Cron calls this at the top of every hour; the fetch itself
# happens after the sleep, at the randomly chosen minute.
#
# Night is deliberately idle: the daily meter reading only closes at 23:59, so
# fetch-water.py's first morning run picks up the whole previous day. The
# `WATER_DELAY_MIN` / `WATER_DELAY_MAX` overrides exist for testing only.

set -u

min_delay=${WATER_DELAY_MIN:-7}
max_delay=${WATER_DELAY_MAX:-21}
delay_minutes=$(( RANDOM % (max_delay - min_delay + 1) + min_delay ))

echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] water: random delay ${delay_minutes} min" \
    >> /home/pi/perhekalenteri/cron.log

sleep $(( delay_minutes * 60 ))

exec /usr/bin/python3 /home/pi/perhekalenteri/run_evaka_cron.py \
    --job water --json /var/www/html/water.json
