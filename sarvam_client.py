import os
from pathlib import Path

from sarvamai import SarvamAI


def create_sarvam_client() -> SarvamAI | None:
    key = os.getenv("SARVAM_API_KEY", "").strip()
    env_path = Path(__file__).with_name(".env")
    if not key and env_path.is_file():
        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "SARVAM_API_KEY":
                key = value.strip().strip("\"'")
                break

    if not key:
        return None

    return SarvamAI(api_subscription_key=key, timeout=8)
