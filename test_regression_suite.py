"""Run the legacy executable regression scripts in isolated processes.

Each script sets its own temporary TRIBLI_DB before importing the app. Running
them in one pytest interpreter reuses app.config from the first import and can
write fixtures into the developer database, so process isolation is part of
the test contract.
"""
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parent
SCRIPTS = sorted(
    path for path in ROOT.glob("test_*.py") if path.name != Path(__file__).name
)


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda path: path.stem)
def test_regression_script(script):
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"{script.name} failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
