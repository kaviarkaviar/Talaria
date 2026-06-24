#!/bin/zsh
APP_CODE="$(cd "$(dirname "$0")" && pwd)"
export TALARIA_ROOT="$APP_CODE"
export TALARIA_OPEN_BROWSER=1
cd "$APP_CODE" || exit 1

candidate_pythons() {
  print -r -- "$HOME/Applications/miniconda3/bin/python3"
  print -r -- "$HOME/Applications/miniconda3/bin/python3.13"
  print -r -- "$HOME/Applications/miniconda3/bin/pythonw"
  print -r -- "$HOME/Applications/miniconda3/python.app/Contents/MacOS/python"
  print -r -- "$HOME/miniconda3/bin/python3"
  print -r -- "$HOME/anaconda3/bin/python3"
  print -r -- "/opt/anaconda3/bin/python3"
  print -r -- "/opt/homebrew/bin/python3"
  print -r -- "/usr/local/bin/python3"
  print -r -- "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
  print -r -- "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"
  print -r -- "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3"
  print -r -- "/Library/Frameworks/Python.framework/Versions/3.10/bin/python3"
  /bin/zsh -lc 'command -v python3; command -v pythonw; command -v python' 2>/dev/null
}

while IFS= read -r PYTHON; do
  if [ -n "$PYTHON" ] && [ -x "$PYTHON" ]; then
    "$PYTHON" -c "import sys" >/dev/null 2>&1
    if [ $? -eq 0 ]; then
      exec "$PYTHON" intervals_gui.py
    fi
  fi
done < <(candidate_pythons)

echo "Talaria could not find a working Python 3 install."
echo "Install Python 3 from python.org, then try again."
read "?Press return to close."
