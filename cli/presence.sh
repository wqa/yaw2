#!/usr/bin/env bash
# Keep Jean Claude Du Spam present on the network until a deadline or a stop file,
# restarting the bot if it ever crashes. Survives this terminal when run detached.
#
#   nohup ./cli/presence.sh >/dev/null 2>&1 &      # start (default 4h)
#   PRESENCE_SECONDS=7200 nohup ./cli/presence.sh & # 2h
#   touch logs/STOP                                 # stop gracefully
#
# Logs: chat -> logs/chat-YYYY-MM-DD.log ; bot stdout -> logs/presence.out
cd "$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
mkdir -p logs
rm -f logs/STOP
DEADLINE=$(( $(date +%s) + ${PRESENCE_SECONDS:-14400} ))   # default 4 hours
echo "=== presence started $(date) (until $(date -r "$DEADLINE")) ===" >> logs/presence.out
while [ "$(date +%s)" -lt "$DEADLINE" ] && [ ! -f logs/STOP ]; do
  REMAIN=$(( DEADLINE - $(date +%s) ))
  [ "$REMAIN" -gt 0 ] || break
  cli/.venv/bin/python -u cli/greet_bot.py --seconds "$REMAIN" >> logs/presence.out 2>&1
  sleep 3   # brief gap before a restart-on-crash
done
echo "=== presence ended $(date) ===" >> logs/presence.out
