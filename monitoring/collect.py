#!/usr/bin/env python3
"""Read-only host collector. Run once per minute as the deployment user.

Only ROOT contains collector writes. Docker log payloads never leave memory;
spools deliberately contain metadata, not application messages.
"""
import argparse
import datetime as dt
import fcntl
import json
import math
import os
from pathlib import Path
import re
import resource
import selectors
import signal
import stat
import subprocess
import sys
import time
import uuid

SERVICES = ("caddy", "public-site", "blog", "admin-app", "shop", "backend",
            "booking-sms-reminders", "postgres")
MAX_LOG = 5 * 1024 * 1024
RETENTION = dt.timedelta(hours=72)
MAX_OUTPUT = 2 * 1024 * 1024
CALL_TIMEOUT = 3
GLOBAL_TIMEOUT = 50
ID = re.compile(r"[0-9a-f]{64}\Z")
LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "WARN", "FATAL"}
EXCEPTIONS = ("RuntimeError", "ValueError", "TypeError", "KeyError", "TimeoutError",
              "ConnectionError", "PermissionError", "OSError", "AssertionError")
INSPECT = ('{"id":{{json .Id}},"project":{{json (index .Config.Labels '
           '"com.docker.compose.project")}},"service":{{json (index .Config.Labels '
           '"com.docker.compose.service")}},"state":{{json .State.Status}},'
           '"started":{{json .State.StartedAt}},"health":'
           '{{if .State.Health}}{{json .State.Health.Status}}{{else}}"none"{{end}}}')


class CollectionError(Exception):
    """Never expose exception details to output."""


class Deadline(CollectionError):
    pass


def timestamp(value):
    """Parse RFC3339 including Docker's nanoseconds (datetime has microseconds)."""
    if not isinstance(value, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})", value):
        raise ValueError("invalid timestamp")
    return dt.datetime.fromisoformat(re.sub(r"(\.\d{6})\d+", r"\1", value).replace("Z", "+00:00"))


def iso(value):
    return value.astimezone(dt.timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def docker(args):
    """Bound both execution time and combined pipe bytes, without raw temp files."""
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME")}
    process = subprocess.Popen(["docker", *args], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, env=env)
    chunks = []
    size = 0
    end = time.monotonic() + CALL_TIMEOUT
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, True)
            selector.register(process.stderr, selectors.EVENT_READ, False)
            while selector.get_map():
                remaining = end - time.monotonic()
                if remaining <= 0:
                    raise CollectionError()
                for key, _ in selector.select(remaining):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    size += len(chunk)
                    if size > MAX_OUTPUT:
                        raise CollectionError()
                    # Docker logs sends application stderr to this pipe as well.
                    if key.data or args[0] == "logs":
                        chunks.append(chunk)
            process.wait(timeout=max(.001, end - time.monotonic()))
        if process.returncode:
            raise CollectionError()
        return b"".join(chunks).decode("utf-8", errors="replace")
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()
        process.stderr.close()


def atomic(path, data, mode):
    temp = path.with_name(path.name + ".tmp")
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode)
        with os.fdopen(fd, "w") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        temp.unlink(missing_ok=True)


def event(line, service):
    date, separator, body = line.partition(" ")
    if not separator:
        raise ValueError("missing timestamp")
    stamp = iso(timestamp(date))
    level = "INFO"
    if service == "caddy":
        try:
            structured = json.loads(body)
            candidate = structured.get("level") if isinstance(structured, dict) else None
            if isinstance(candidate, str) and candidate.upper() in LEVELS:
                level = {"WARN": "WARNING", "FATAL": "CRITICAL"}.get(
                    candidate.upper(), candidate.upper())
        except (ValueError, RecursionError):
            pass
    if service == "postgres":
        severity = re.match(
            r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)? "
            r"(?:UTC|GMT|[+-]\d{2}(?::?\d{2})?) \[\d+\] "
            r"(DEBUG[1-5]|INFO|NOTICE|LOG|WARNING|ERROR|FATAL|PANIC):(?:\s|$)", body)
        if severity:
            level = {"NOTICE": "INFO", "LOG": "INFO", "FATAL": "CRITICAL",
                     "PANIC": "CRITICAL"}.get(severity[1], severity[1])
            if level.startswith("DEBUG"):
                level = "DEBUG"
    match = re.match(r"^(?:\[)?(DEBUG|INFO|WARNING|ERROR|CRITICAL|WARN|FATAL)(?:\]|[: ])", body)
    if match:
        level = {"WARN": "WARNING", "FATAL": "CRITICAL"}.get(match[1], match[1])
        body = body[match.end():].lstrip()
    kind, message = "application", "Application log (details redacted)"
    exception = re.match(r"^(" + "|".join(EXCEPTIONS) + r")(?::|$)", body)
    http = re.fullmatch(r"HTTP (GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) ([1-5][0-9]{2})(?: .*)?", body)
    if http is None:
        # Uvicorn's access format; only the two allowlisted captures may escape.
        http = re.fullmatch(
            r'(?:\[[0-9a-fA-F:]+\]|[0-9a-fA-F:.]+):\d+ - '
            r'"(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) [^"\r\n]* HTTP/\d\.\d" '
            r'([1-5][0-9]{2})(?: [A-Za-z ]+)?', body)
    if exception:
        kind, message, level = "exception", exception[1] + " (details redacted)", "ERROR"
    elif http:
        kind, message = "http", "HTTP " + http[1] + " " + http[2]
    return {"timestamp": stamp, "service": service, "level": level,
            "event": kind, "message": message}


def append_events(path, records):
    payload = "".join(json.dumps(record, separators=(",", ":")) + "\n" for record in records)
    encoded = payload.encode("utf-8")
    if len(encoded) > MAX_LOG:
        raise CollectionError()
    if path.exists() and path.stat().st_size + len(encoded) > MAX_LOG:
        os.replace(path, path.with_suffix(".log.1"))
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o640)
    with os.fdopen(fd, "ab") as stream:
        os.fchmod(stream.fileno(), 0o640)
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def prune_spool(path, service, now):
    """Expire existing metadata only; caller must hold the collector lock."""
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        try:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                         dir_fd=directory)
        except FileNotFoundError:
            return
        retained = []
        changed = False
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise CollectionError()
            if info.st_size > MAX_LOG:
                # Oversized/corrupt files are discarded without reading past the cap.
                changed = True
            else:
                remaining = MAX_LOG
                while remaining:
                    line = stream.readline(remaining)
                    if not line:
                        break
                    remaining -= len(line)
                    try:
                        record = json.loads(line)
                        if (not line.endswith(b"\n") or not isinstance(record, dict)
                                or set(record) != {"timestamp", "service", "level", "event", "message"}
                                or record["service"] != service
                                or record["level"] not in LEVELS):
                            raise ValueError("invalid metadata")
                        message = record["message"]
                        kind = record["event"]
                        safe = (kind == "application" and message == "Application log (details redacted)"
                                or kind == "exception" and message in {
                                    name + " (details redacted)" for name in EXCEPTIONS}
                                or kind == "http" and isinstance(message, str) and re.fullmatch(
                                    r"HTTP (GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) [1-5][0-9]{2}", message))
                        if not safe or not now - RETENTION <= timestamp(record["timestamp"]) <= now:
                            raise ValueError("expired or invalid metadata")
                    except (ValueError, TypeError, KeyError, RecursionError):
                        changed = True
                    else:
                        retained.append(line)
        if not changed:
            return
        # Never stage rejected records, and never follow spool or temporary symlinks.
        temp = path.name + ".prune-" + uuid.uuid4().hex + ".tmp"
        created = False
        try:
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o640, dir_fd=directory)
            created = True
            with os.fdopen(fd, "wb") as stream:
                os.fchmod(stream.fileno(), 0o640)
                stream.writelines(retained)
                stream.flush()
                os.fsync(stream.fileno())
            # Refuse a replaced symlink rather than replacing it silently.
            current = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
            if not stat.S_ISREG(current.st_mode) or (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
                raise CollectionError()
            os.replace(temp, path.name, src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
        finally:
            if created:
                try:
                    os.unlink(temp, dir_fd=directory)
                except FileNotFoundError:
                    pass
    finally:
        os.close(directory)


def number(value):
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError("invalid number")
    return result


def memory(value):
    match = re.fullmatch(r"\s*([0-9.]+)\s*(B|kB|KB|MB|GB|TB|KiB|MiB|GiB|TiB)\s*", value)
    if not match:
        raise ValueError("invalid memory")
    unit = match[2]
    power = {"B": 0, "kB": 1, "KB": 1, "MB": 2, "GB": 3, "TB": 4,
             "KiB": 1, "MiB": 2, "GiB": 3, "TiB": 4}[unit]
    return number(match[1]) * (1024 if "i" in unit else 1000) ** power


def host_metrics(root, previous):
    mem = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        mem[key] = int(value.split()[0]) * 1024
    disk = os.statvfs(root)
    cpu = list(map(int, Path("/proc/stat").read_text().splitlines()[0].split()[1:9]))
    total, idle = sum(cpu), cpu[3] + cpu[4]
    old = previous.get("cpu", [total, idle])
    delta = total - old[0]
    busy = max(0, min(1, 1 - (idle - old[1]) / delta)) if delta > 0 else 0
    metrics = {"soulcuts_host_memory_total_bytes": mem["MemTotal"],
               "soulcuts_host_memory_available_bytes": mem["MemAvailable"],
               "soulcuts_host_disk_size_bytes": disk.f_blocks * disk.f_frsize,
               "soulcuts_host_disk_free_bytes": disk.f_bavail * disk.f_frsize,
               "soulcuts_host_cpu_busy_ratio": busy,
               "soulcuts_host_uptime_seconds": number(Path("/proc/uptime").read_text().split()[0])}
    rx = tx = 0
    for line in Path("/proc/net/dev").read_text().splitlines()[2:]:
        name, values = line.split(":", 1)
        if name.strip() != "lo":
            fields = values.split()
            rx += int(fields[0])
            tx += int(fields[8])
    metrics.update(soulcuts_host_network_receive_bytes_total=rx,
                   soulcuts_host_network_transmit_bytes_total=tx)
    return metrics, [total, idle]


def sample(name, value, service=None):
    labels = '{service="' + service + '"}' if service else ""
    return f"{name}{labels} {value}\n"


def service_collect(service, root, state, now):
    if service not in SERVICES:
        raise CollectionError()
    values = {"soulcuts_service_running": 0, "soulcuts_service_healthy": 0,
              "soulcuts_service_healthcheck_present": 0, "soulcuts_service_uptime_seconds": 0,
              "soulcuts_container_cpu_percent": 0, "soulcuts_container_memory_bytes": 0}
    errors = 0
    try:
        old = state.get(service, {})
        if not isinstance(old, dict):
            raise CollectionError()
        ids = docker(["ps", "-a", "--no-trunc", "--filter", "label=com.docker.compose.project=soulcuts",
                      "--filter", "label=com.docker.compose.service=" + service,
                      "--format", "{{.ID}}"]).splitlines()
        # Reject ambiguity, truncated IDs, and identity changes before reading logs.
        if len(ids) != 1 or not ID.fullmatch(ids[0]):
            raise CollectionError()
        ident = ids[0]
        info = json.loads(docker(["inspect", "--format", INSPECT, ident]))
        if info["id"] != ident or info["project"] != "soulcuts" or info["service"] != service:
            raise CollectionError()
        running = info["state"] == "running"
        values["soulcuts_service_running"] = int(running)
        values["soulcuts_service_healthy"] = int(running and info["health"] in ("healthy", "none"))
        values["soulcuts_service_healthcheck_present"] = int(info["health"] != "none")
        if running:
            uptime = max(0, (now - timestamp(info["started"])).total_seconds())
            monotonic = time.monotonic()
            if (old.get("id") == ident and old.get("started") == info["started"]
                    and 0 <= number(old.get("monotonic", monotonic + 1)) <= monotonic):
                uptime = number(old["uptime"]) + monotonic - number(old["monotonic"])
            values["soulcuts_service_uptime_seconds"] = uptime
            stats = json.loads(docker(["stats", "--no-stream", "--format", "{{json .}}", ident]))
            values["soulcuts_container_cpu_percent"] = number(stats["CPUPerc"].removesuffix("%"))
            values["soulcuts_container_memory_bytes"] = memory(stats["MemUsage"].split("/")[0])
        since = now - dt.timedelta(seconds=60)
        if old.get("id") == ident:
            since = max(now - RETENTION, min(now, timestamp(old["until"])))
        raw = docker(["logs", "--timestamps", "--since", iso(since), "--until", iso(now),
                      "--tail", "200", ident])
        records = []
        for line in raw.splitlines():
            try:
                record = event(line, service)
                if since <= timestamp(record["timestamp"]) <= now:
                    records.append(record)
                else:
                    errors += 1
            except (ValueError, TypeError):
                errors += 1
        append_events(root / "spool" / "logs" / (service + ".log"), records)
        # Persist only after the sanitized spool and its directory are durable.
        updated = dict(state)
        updated[service] = {"id": ident, "until": iso(now)}
        if running:
            updated[service].update(started=info["started"], uptime=uptime, monotonic=monotonic)
        atomic(root / "state.json", json.dumps(updated), 0o600)
        state.clear()
        state.update(updated)
    except Deadline:
        raise
    except Exception:
        # All untrusted Docker/state parsing errors are fixed metadata, never text.
        errors += 1
    values["soulcuts_service_collection_errors"] = errors
    return values


def failure_metrics(path, now):
    """Retain last samples on global failure, but never retain a healthy status."""
    old = path.read_text() if path.exists() else ""
    lines = [line for line in old.splitlines() if not line.startswith((
        "soulcuts_collector_success ", "soulcuts_collector_last_attempt_unixtime ",
        "soulcuts_collector_errors ", "soulcuts_service_collection_errors{"))]
    data = "\n".join(lines) + "\n"
    if not any(line.startswith("soulcuts_collector_last_success_unixtime ") for line in lines):
        data += sample("soulcuts_collector_last_success_unixtime", 0)
    data += sample("soulcuts_collector_success", 0)
    data += sample("soulcuts_collector_errors", 1)
    data += sample("soulcuts_collector_last_attempt_unixtime", now)
    for service in SERVICES:
        data += sample("soulcuts_service_collection_errors", 1, service)
    atomic(path, data, 0o644)


def collect(root):
    root = Path(root)
    for directory in (root, root / "spool", root / "spool/logs", root / "spool/metrics"):
        directory.mkdir(mode=0o750, parents=True, exist_ok=True)
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fchmod(fd, 0o750)
        finally:
            os.close(fd)
    lockfd = os.open(root / "collector.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lockfd, "w") as lock:
        os.fchmod(lock.fileno(), 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        now = dt.datetime.now(dt.timezone.utc)
        metric_path = root / "spool/metrics/soulcuts.prom"
        previous_handler = signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(Deadline()))
        signal.alarm(GLOBAL_TIMEOUT)
        try:
            retention_failed = False
            for service in SERVICES:
                for suffix in (".log", ".log.1"):
                    try:
                        prune_spool(root / "spool/logs" / (service + suffix), service, now)
                    except (OSError, CollectionError):
                        retention_failed = True
            if retention_failed:
                raise CollectionError()
            state = {}
            if (root / "state.json").exists():
                state = json.loads((root / "state.json").read_text())
                if not isinstance(state, dict):
                    raise CollectionError()
            metrics, cpu = host_metrics(root, state)
            data = "".join(sample(k, v) for k, v in metrics.items())
            errors = 0
            for service in SERVICES:
                values = service_collect(service, root, state, now)
                errors += values["soulcuts_service_collection_errors"]
                data += "".join(sample(k, v, service) for k, v in values.items())
            state["cpu"] = cpu
            atomic(root / "state.json", json.dumps(state), 0o600)
            last = state.get("last_success", 0)
            if not errors:
                last = now.timestamp()
                state["last_success"] = last
                atomic(root / "state.json", json.dumps(state), 0o600)
            data += sample("soulcuts_collector_last_success_unixtime", last)
            data += sample("soulcuts_collector_last_attempt_unixtime", now.timestamp())
            data += sample("soulcuts_collector_success", int(not errors))
            data += sample("soulcuts_collector_errors", errors)
            atomic(metric_path, data, 0o644)
            if errors:
                print("collector: collection incomplete", file=sys.stderr)
            return int(bool(errors))
        except Exception:
            signal.alarm(0)
            try:
                failure_metrics(metric_path, now.timestamp())
            except OSError:
                pass
            print("collector: collection failed", file=sys.stderr)
            return 1
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous_handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="/opt/soulcuts/monitoring")
    args = parser.parse_args()
    os.umask(0o027)
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        # Do not cap address space: subprocesses inherit limits and the Go Docker
        # CLI needs a large virtual reservation even with a small resident set.
        resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
        return collect(args.root)
    except Exception:
        print("collector: initialization failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
