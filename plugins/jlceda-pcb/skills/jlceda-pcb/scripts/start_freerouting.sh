#!/usr/bin/env bash
set -euo pipefail

java_bin="${FREEROUTING_JAVA:-$HOME/tools/jre25/bin/java}"
jar_path="${FREEROUTING_JAR:-$HOME/tools/freerouting/freerouting-2.5.0.jar}"
port="${FREEROUTING_PORT:-37864}"

if [[ ! "$port" =~ ^[0-9]+$ ]] || (( port < 1024 || port > 65535 )); then
    printf 'Invalid local port: %s\n' "$port" >&2
    exit 2
fi
if [[ ! -x "$java_bin" || ! -f "$jar_path" ]]; then
    printf 'Set FREEROUTING_JAVA and FREEROUTING_JAR to installed files.\n' >&2
    exit 2
fi
if curl --fail --silent --max-time 2 "http://127.0.0.1:$port/v1/system/status" >/dev/null; then
    printf 'A Freerouting service is already listening on 127.0.0.1:%s.\n' "$port"
    exit 0
fi
exec "$java_bin" -Xmx4g -jar "$jar_path" \
    --gui.enabled=false \
    --api_server.enabled=true \
    "--api_server.endpoints=http://127.0.0.1:$port" \
    --api_server.authentication.enabled=false \
    '--api_server.cors_origins=*' \
    --logging.console.level=INFO
