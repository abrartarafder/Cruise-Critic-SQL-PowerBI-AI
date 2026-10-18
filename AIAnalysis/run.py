"""Start the app with one command: python3 AIAnalysis/run.py.

This script uses only Python's standard library. It prepares a separate Python
environment, installs the requirements, and starts Streamlit from the right folder.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import venv

APP_DIR = Path(__file__).resolve().parent


def main():
    if sys.version_info < (3, 11):
        print("Please install Python 3.11 or newer, then run this command again.")
        return 1

    # This project's path contains a colon. Keep the environment outside it.
    temp_root = Path("/tmp") if os.name == "posix" else Path(tempfile.gettempdir())
    environment = temp_root / "cruise-critic-ai-venv"
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    try:
        if not python.exists():
            print("First-time setup: preparing Python for the app…", flush=True)
            venv.EnvBuilder(with_pip=True).create(environment)

        print("Checking app packages. The first run needs an internet connection…", flush=True)
        subprocess.run([
            str(python), "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
            "--no-input", "--cache-dir", str(environment / "pip-cache"),
            "-r", str(APP_DIR / "requirements.txt"),
        ], check=True)

        print("Starting Cruise Data Helper. Open the URL below. Press Ctrl+C to stop.", flush=True)
        return subprocess.call([
            str(python), "-m", "streamlit", "run", "app.py", *sys.argv[1:],
        ], cwd=APP_DIR)
    except KeyboardInterrupt:
        print("\nApp stopped.")
        return 0
    except (OSError, subprocess.CalledProcessError):
        print("Setup couldn't finish. Check your internet connection and run the command again.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
