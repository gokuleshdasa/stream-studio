#!/bin/sh
# macOS / Linux launcher when running from source.
cd "$(dirname "$0")" || exit 1
echo "Starting Stream Studio...  (opens at http://127.0.0.1:5006)"
exec python3 app.py "$@"
