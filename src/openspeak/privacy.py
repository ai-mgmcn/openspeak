"""
No telemetry, by default, from anything we pull in.

huggingface_hub reads these flags once at import time, so they must be set before
faster_whisper is imported — putting them in a config file read later does nothing.
Import this module first. setdefault leaves an explicit user choice alone.
"""

import os

for _name in ("HF_HUB_DISABLE_TELEMETRY", "HF_HUB_DISABLE_IMPLICIT_TOKEN", "DO_NOT_TRACK"):
    os.environ.setdefault(_name, "1")
