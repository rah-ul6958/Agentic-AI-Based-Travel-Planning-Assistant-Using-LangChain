#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -x venv/bin/python ]; then
  venv/bin/python -m streamlit run app.py
elif [ -x venv/Scripts/python.exe ]; then
  venv/Scripts/python.exe -m streamlit run app.py
else
  python -m streamlit run app.py
fi
