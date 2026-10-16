import os
import sys
from datetime import datetime
from pathlib import Path

os.environ["KISAN_WEATHER_LIVE"] = "0"
os.environ["KISAN_USE_LLM"] = "0"
os.environ.pop("SARVAM_API_KEY", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from app import clock  # noqa: E402
from app.db import init_db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    init_db(f"sqlite:///{tmp_path}/test.db", reset=True)
    clock.freeze(datetime(2026, 3, 13, 19, 30))
    from app import demo
    demo.reset_world()
    yield
    clock.freeze(None)
