#!/usr/bin/env bash
# Deploy naar een Linux-server: native venv + systemd-timers, geen webpoort.
# Draait eerst de tests. Servergegevens in deploy.env (zie deploy.env.example).
# De units in systemd/ zijn sjablonen: deploy.sh vult @DEST@ en @RUN_USER@ in en zet
# UNIT_PREFIX voor de naam (alles uit deploy.env).
set -euo pipefail
export COPYFILE_DISABLE=1
cd "$(dirname "$0")"
[ -f deploy.env ] || { echo "deploy.env ontbreekt (kopieer deploy.env.example)"; exit 1; }
. ./deploy.env
RUN_USER="${RUN_USER:?RUN_USER ontbreekt in deploy.env}"
UNIT_PREFIX="${UNIT_PREFIX:-}"

.venv/bin/python -m pytest -q

ssh -p "$PORT" "$VPS" "mkdir -p '$DEST/data'"
tar cf - --no-mac-metadata --exclude='.DS_Store' --exclude='._*' --exclude='__pycache__' \
    pbibrief prompts systemd kanalen.yaml requirements.txt README.md \
  | ssh -p "$PORT" "$VPS" "tar xf - -C '$DEST' && find '$DEST' -name '._*' -delete"

ssh -p "$PORT" "$VPS" "bash -lc '
set -euo pipefail
cd $DEST
chmod 700 data

# Eenmalig: .env met endpoint, heartbeat-map en (optioneel) de mailgegevens uit MAIL_BRON.
if [ ! -f .env ]; then
  umask 077
  {
    echo \"QWEN_BASE_URL=$QWEN_BASE_URL\"
    echo \"HEARTBEAT_DIR=$HEARTBEAT_DIR\"
    if [ -n \"$MAIL_BRON\" ]; then grep -E \"^(POSTMARK_TOKEN|MAIL_FROM|MAIL_TO)=\" \"$MAIL_BRON\" || true; fi
  } > .env
  chmod 600 .env
fi

[ -x venv/bin/python ] || python3 -m venv venv
venv/bin/python -c \"import sys; assert sys.version_info[:2]==(3,12), sys.version\"
venv/bin/pip install -q -U pip
venv/bin/pip install -q -r requirements.txt

for f in systemd/pbi-brief-*.service systemd/pbi-brief-*.timer; do
  sed -e \"s|@DEST@|$DEST|g\" -e \"s|@RUN_USER@|$RUN_USER|g\" \"\$f\" \\
    | sudo tee \"/etc/systemd/system/${UNIT_PREFIX}\$(basename \"\$f\")\" >/dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable --now ${UNIT_PREFIX}pbi-brief-nacht.timer ${UNIT_PREFIX}pbi-brief-editie.timer
systemctl list-timers --no-pager | grep pbi-brief || true
'"

echo "OK: gedeployed naar $VPS:$DEST (nacht 01:30 NL, editie zo 08:10 NL)"
