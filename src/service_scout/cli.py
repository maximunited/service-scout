"""CLI entrypoints."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from service_scout.config import load_config
from service_scout.db import init_db, make_engine
from service_scout.digest import flush_digest
from service_scout.governor import Governor
from service_scout.runner import run_all


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="service-scout", description="Service Scout research control plane")
    parser.add_argument("-c", "--config", default=None, help="Path to config.yaml")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="Run scout lanes")
    p_run.add_argument("--lane", action="append", dest="lanes", help="Lane name (repeatable)")
    p_run.add_argument("--target", default=None, help="Target id")
    p_run.add_argument("--dry-run", action="store_true", help="Skip Notion writes")

    sub.add_parser("digest", help="Flush weekly Apprise digest")
    sub.add_parser("budget", help="Show Tavily budget snapshot")
    sub.add_parser("init-db", help="Create tables")

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    cfg_path = args.config
    if cfg_path is None and Path("config.yaml").is_file():
        cfg_path = "config.yaml"
    cfg = load_config(cfg_path)

    engine = make_engine(cfg.database)
    Session = init_db(engine)

    if args.cmd == "init-db":
        print("ok: tables created")
        return 0

    with Session() as session:
        if args.cmd == "budget":
            snap = Governor(cfg, session).snapshot()
            print(json.dumps(snap.__dict__, indent=2))
            return 0
        if args.cmd == "digest":
            n = flush_digest(session, cfg)
            print(json.dumps({"flushed": n}))
            return 0
        if args.cmd == "run":
            results = run_all(
                session,
                cfg,
                lanes=args.lanes,
                target_id=args.target,
                dry_run=args.dry_run,
            )
            print(json.dumps(results, indent=2, default=str))
            return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
