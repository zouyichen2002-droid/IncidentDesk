#!/bin/sh
# PID 1 forwards shutdown, while the worker remains a normal, suspendable process.
"$@" &
child=$!
trap 'kill -TERM "$child" 2>/dev/null; wait "$child"' TERM INT
wait "$child"
