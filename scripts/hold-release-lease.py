"""Hold the database locks shared with production recovery."""

import argparse
import json
import os
from pathlib import Path
import signal
import sys
import time


PACKAGE = Path("/usr/local/libexec/sc-recovery-5f4ba45-v2")
APP = Path("/opt/soulcuts")


def stop(_signum, _frame):
    raise InterruptedError


def hold(args):
    if not 30 <= args.seconds <= 1800 or os.geteuid() == 0:
        raise RuntimeError("invalid_lease_owner_or_duration")
    if args.release.resolve(strict=True).parent != APP / "releases":
        raise RuntimeError("invalid_lease_release")
    if os.environ.get("DOCKER_HOST") or os.environ.get("DOCKER_CONTEXT"):
        raise RuntimeError("docker_override_refused")
    sys.path.insert(0, str(PACKAGE))
    from controller import Lease, command
    from paired_offline import START_US, TOP_LOCK, TOP_LOCK_SQL, assert_live_paired_lease
    from root_guard import DOCKER

    pg, = json.loads(command([*DOCKER, "inspect", "soulcuts-postgres-1"]))
    labels = pg["Config"]["Labels"]
    if (not pg["State"]["Running"] or labels.get("com.docker.compose.project") != "soulcuts"
            or labels.get("com.docker.compose.service") != "postgres"):
        raise RuntimeError("wrong_postgres_service")
    argv = [*DOCKER, "exec", "-i", pg["Id"], "sh", "-ec",
            'exec psql -XqAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"']
    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, stop)
    deadline = time.monotonic() + args.seconds
    with Lease(argv, seconds=args.seconds) as lease:
        lease.query("ROLLBACK;")
        if lease.query("SELECT current_database();") != "barbershop_platform":
            raise RuntimeError("wrong_release_database")
        if lease.query(f"SELECT pg_try_advisory_lock({TOP_LOCK}::bigint);") != "t":
            raise RuntimeError("top_cache_lease_busy")
        started = lease.query(f"SELECT {START_US} FROM pg_stat_activity WHERE pid=pg_backend_pid();")
        lease.check()
        assert_live_paired_lease(pg["Id"], int(lease.pid), started)
        print(f"CUTOVER_LEASE_PID={lease.pid} CUTOVER_LEASE_START_US={started}", flush=True)
        while time.monotonic() + 5 < deadline:
            time.sleep(3)
            lease.check()
            if lease.query(
                "SELECT count(*) FROM pg_locks l WHERE l.pid=pg_backend_pid() AND l.locktype='advisory'"
                f" AND l.granted AND l.mode='ExclusiveLock' AND {TOP_LOCK_SQL};"
            ) != "1":
                raise RuntimeError("top_cache_lease_lost")
    print("Release lease expired", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release", type=Path)
    parser.add_argument("--seconds", type=int, default=900)
    try:
        hold(parser.parse_args())
    except InterruptedError:
        print("Release lease closed", flush=True)
    except Exception:
        raise SystemExit("Release lease refused or lost; no deployment command was run") from None
