#!/usr/bin/env python
"""Load .env file and start uvicorn server."""
import os
import subprocess
import sys
from pathlib import Path

# Load .env file into os.environ so subprocess inherits it
env_file = Path('.env')
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                os.environ[key] = value

if __name__ == '__main__':
    # Use subprocess to start uvicorn so it inherits os.environ
    cmd = [
        sys.executable, '-m', 'uvicorn',
        'worldcup_assistant.wc_server:app',
        '--host', '127.0.0.1',
        '--port', os.environ.get('WC_PORT', '8100'),
        '--workers', '1'
    ]
    subprocess.run(cmd, env=os.environ)
