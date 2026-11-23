#!/usr/bin/env bash
# 현재 커밋(HEAD)을 NAS에 올리고 앱 컨테이너를 다시 빌드한다.
# 커밋 안 된 변경은 올라가지 않는다. data/와 .env는 건드리지 않는다.
#
#   bash scripts/deploy_nas.sh
#
# 터널(cloudflared)은 재시작하지 않으므로 Quick Tunnel 주소가 유지된다.
set -euo pipefail

NAS="${NAS:-nastorond@172.30.1.1}"
DIR="${NAS_DIR:-/volume1/docker/family}"

cd "$(dirname "$0")/.."
echo "배포: $(git log --oneline -1)"
if [ -n "$(git status --porcelain)" ]; then
  echo "주의: 커밋 안 된 변경이 있어요. 커밋된 내용만 올라가요."
fi

git archive --format=tar HEAD | ssh -o BatchMode=yes "$NAS" "tar -x -C '$DIR'"
ssh -o BatchMode=yes "$NAS" "cd '$DIR' && export PATH=/usr/local/bin:\$PATH && \
  docker compose up -d --build --no-deps app 2>&1 | tail -3 && sleep 5 && \
  docker compose ps && \
  echo && echo -n '로컬 응답: ' && curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/login && \
  echo -n '터널 주소: ' && docker compose logs cloudflared 2>&1 | grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -1"
