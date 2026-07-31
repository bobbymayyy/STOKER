from __future__ import annotations

import argparse
import logging
import sys

from .builder import StokerBuilder
from .config import BuildConfig
from .errors import StokerBuildError


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="stoker-build",
        description="Compile a STOKER Debian appliance ISO from YAML.",
    )
    result.add_argument(
        "-c",
        "--config",
        default="config/stoker-build.yaml",
        help="Main build YAML (default: config/stoker-build.yaml)",
    )
    result.add_argument("--dry-run", action="store_true", help="Print external commands without running them")
    result.add_argument(
        "--allow-placeholder-secrets",
        action="store_true",
        help="Render CHANGE_ME placeholders when secret environment variables are absent",
    )
    result.add_argument("-v", "--verbose", action="count", default=0)
    result.add_argument(
        "command",
        choices=[
            "validate",
            "render",
            "resolve",
            "repository",
            "extract",
            "inject",
            "checksum",
            "package",
            "verify",
            "all",
            "clean",
        ],
    )
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )
    try:
        config = BuildConfig.load(args.config)
        builder = StokerBuilder(
            config,
            dry_run=args.dry_run,
            allow_placeholder_secrets=args.allow_placeholder_secrets,
        )
        action = getattr(builder, args.command)
        action()
        return 0
    except StokerBuildError as exc:
        logging.getLogger("stoker-builder").error("%s", exc)
        return 2
    except KeyboardInterrupt:
        logging.getLogger("stoker-builder").error("Interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
