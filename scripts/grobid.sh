#!/usr/bin/env bash
set -euo pipefail

IMAGE="grobid/grobid:0.9.0-crf"
CONTAINER="corpus2node-grobid"
BASE_URL="http://127.0.0.1:8070"

is_alive() {
  curl --fail --silent --max-time 2 "$BASE_URL/api/isalive" >/dev/null 2>&1
}

case "${1:-status}" in
  start)
    if ! docker info >/dev/null 2>&1; then
      if command -v colima >/dev/null 2>&1; then
        colima start
      else
        echo "Docker daemon is unavailable; start Docker Desktop first." >&2
        exit 1
      fi
    fi
    docker pull "$IMAGE"
    if docker container inspect "$CONTAINER" >/dev/null 2>&1; then
      docker start "$CONTAINER" >/dev/null
    else
      docker run -d \
        --name "$CONTAINER" \
        --restart unless-stopped \
        --init \
        --ulimit core=0 \
        -p 8070:8070 \
        "$IMAGE" >/dev/null
    fi
    for _ in $(seq 1 120); do
      if is_alive; then
        echo "GROBID is ready at $BASE_URL"
        exit 0
      fi
      sleep 1
    done
    echo "GROBID did not become ready; inspect: $0 logs" >&2
    exit 1
    ;;
  stop)
    docker stop "$CONTAINER" >/dev/null
    ;;
  logs)
    docker logs --tail 200 -f "$CONTAINER"
    ;;
  status)
    if is_alive; then
      echo "GROBID is healthy at $BASE_URL"
    else
      docker ps -a --filter "name=^/${CONTAINER}$" --format '{{.Names}} {{.Status}} {{.Image}}'
      exit 1
    fi
    ;;
  *)
    echo "Usage: $0 {start|stop|status|logs}" >&2
    exit 2
    ;;
esac
