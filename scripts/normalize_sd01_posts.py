import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from scripts.normalize_sd_posts import main as normalize_main


def main() -> int:
    argv = sys.argv[1:]
    if "--site-id" not in argv:
        argv = ["--site-id", "sd01-chichi", *argv]
    if "--base-url" not in argv:
        argv = ["--base-url", "https://sd01-chichi.av-kantei.com", *argv]
    return normalize_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
