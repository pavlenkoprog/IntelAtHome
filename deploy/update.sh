#!/bin/bash
set -euo pipefail
cd /opt/intelathome
git fetch origin prod
git checkout prod
local_rev=$(git rev-parse HEAD)
remote_rev=$(git rev-parse origin/prod)
need_restart=0
if [ "$local_rev" != "$remote_rev" ]; then
  git pull --ff-only origin prod
  .venv/bin/pip install -q -r backend/requirements.txt
  need_restart=1
fi
if ! cmp -s deploy/intelathome.service /etc/systemd/system/intelathome.service; then
  cp deploy/intelathome.service /etc/systemd/system/intelathome.service
  systemctl daemon-reload
  systemctl enable intelathome
  need_restart=1
fi
if [ "$need_restart" -eq 1 ]; then
  systemctl restart intelathome
fi
