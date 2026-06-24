#!/bin/zsh
FOLDER="$(cd "$(dirname "$0")" && pwd)"
exec "$FOLDER/Talaria.app/Contents/MacOS/talaria"
