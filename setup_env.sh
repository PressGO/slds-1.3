#!/usr/bin/env bash
# setup_env.sh - Linux/macOS version of setup_env.bat for SLDS project 1.3.
# Creates .venv in the project folder with polars, numpy, matplotlib and Jupyter,
# and registers the notebook kernel "Python (SLDS 1.3)". Safe to run again.
# The collector does NOT use this environment: it runs on the system python3 (standard library only).
set -euo pipefail
cd "$(dirname "$0")"

if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
    echo "Python 3.10 or newer is needed. Found: $(python3 --version 2>&1)"; exit 1
fi
if ! python3 -c 'import venv, ensurepip' 2>/dev/null; then
    echo "The venv module is missing. On Ubuntu run:  sudo apt install -y python3-venv"; exit 1
fi

[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install --upgrade -r requirements.txt
.venv/bin/python -m ipykernel install --user --name slds-1.3 --display-name "Python (SLDS 1.3)"
.venv/bin/python -c "import sys, polars, numpy, matplotlib; print('OK  Python', sys.version.split()[0], '| polars', polars.__version__, '| numpy', numpy.__version__, '| matplotlib', matplotlib.__version__)"
echo
echo "Done. Start Jupyter from this folder (the notebooks expect it as the working directory):"
echo "  cd $(pwd) && .venv/bin/jupyter lab"
