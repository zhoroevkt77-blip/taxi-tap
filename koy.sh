#!/data/data/com.termux/files/usr/bin/bash
# Такси ТАП! — Termux'тан GitHub'ка биринчи жолу коюу.
# Download папкасындагы taxi-tap.zip'ти ачып, GitHub'дагы бош репого жөнөтөт.
# Иштетүү:  bash ~/storage/downloads/koy.sh
set -e
ZIP="$HOME/storage/downloads/taxi-tap.zip"
REPO="$HOME/taxi-tap"
URL="https://github.com/zhoroevkt77-blip/taxi-tap.git"

[ -f "$ZIP" ] || { echo "❌ $ZIP табылган жок"; exit 1; }
rm -rf "$REPO" && mkdir -p "$REPO"
cd "$REPO" && unzip -q "$ZIP"
[ -d .git ] || { git init -q && git add -A && git commit -qm "Такси ТАП! — 0-этап"; }
git branch -M main
git remote remove origin 2>/dev/null || true
git remote add origin "$URL"
python -m unittest discover tests || { echo "❌ Сыноо өтпөдү, push кылынбады."; exit 1; }
git push -u origin main
echo "✅ Бүттү! Railway'де ушул репону туташтыр."
