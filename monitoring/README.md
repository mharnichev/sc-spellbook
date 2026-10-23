# Soulcuts Local Monitoring

Separate `soulcuts-monitoring` Compose project. No application image, environment,
database, API handler, session, pilot, ingress or Caddy changes are required.
No Docker socket, host root, host PID namespace or application network is mounted
into a monitoring container. Only Grafana binds `127.0.0.1:3300`; all other ports
are internal. Grafana alone also joins a separate UI bridge because Docker does
not publish ports from an internal-only network. This bridge is not shared with
application services; its only published port is still loopback-only. Official
stable images are pinned by digest in `images.env`.

## Access

From the operator's workstation:

```sh
ssh -i ~/.ssh/id_hetzner -N -L 13300:127.0.0.1:3300 deploy@178.105.132.73
```

Open `http://localhost:13300`, username `admin`. Retrieve the generated password
directly in your own terminal, not in chat or CI logs:

```sh
ssh -i ~/.ssh/id_hetzner deploy@178.105.132.73 \
  'cat /opt/soulcuts/monitoring/secrets/grafana_admin_password'
```

The password and Grafana encryption key are generated on the server, preserved
outside releases, and mounted read-only through `__FILE` configuration. Anonymous
access, signup, telemetry and update checks are disabled. Never expose 3300,
Prometheus, Loki or Alloy in public ingress/firewall rules.

Grafana loads the signed plugins bundled in the pinned official image directly
from `/usr/share/grafana/data/plugins-bundled`. Runtime plugin installation and
auto-updates are disabled; Prometheus does not depend on a plugin download at
startup. No unsigned-plugin exception is enabled.

## Data And Limits

- A bounded, unprivileged host collector runs once per minute using only Docker
  `ps`, formatted `inspect`, `stats` and `logs` for eight allowlisted Soulcuts
  services. New container IDs are rediscovered after deployments.
- CPU, memory, network, disk, uptime, per-service health and collector freshness
  are written atomically as Prometheus textfile metrics. The reminder utility
  has no Docker healthcheck: its running state is reported separately from the
  `healthcheck_present` gauge, without inventing an application-level check.
- Application logs are **operational metadata only**: timestamp, service,
  severity, recognized exception type or HTTP method/status. Unrestricted log
  messages, request bodies/URLs, SQL and personal data are not persisted. Use
  existing Sentry for detailed, separately scrubbed exception diagnostics.
- Each service spool is limited to 5 MiB plus one rotated file. At most 200 log
  lines per service per collection are read; high-rate bursts can be truncated.
  This is not a complete audit archive. Failed cursor persistence can replay
  already-sanitized events; logs are not an exactly-once business ledger.
- Loki retains logs for 72 hours with compactor retention enabled. Prometheus
  retains metrics for 15 days or 512 MB, whichever limit is reached first;
  WAL/head overhead is additional. Docker's monitoring logs are rotated.
- All five containers have memory, CPU and PID limits and read-only root filesystems.
  Prometheus rules show stale/missing collector, service failure and low-disk
  conditions. No external alert notification receiver is configured.

The provisioned **Soulcuts Production** dashboard has Prometheus metrics and
sanitized Loki logs with a fixed service selector. Collectors and datasource
health are included so an empty/stale graph is distinguishable from a healthy
service. This does not add request latency instrumentation or database query
metrics, nor does it replace off-host uptime monitoring.

## Installation And Verification

1. Test the exact source, native config validators and disposable full-stack
   integration; obtain independent security review and green mandatory CI.
2. Merge the reviewed infrastructure PR. The existing application workflow may
   recreate Caddy for its immutable config bind path, but application pins and
   backend writers must remain unchanged. Wait for that normal workflow to finish.
3. Dispatch **Deploy monitoring** on the accepted `main` SHA. It uploads only
   monitoring files into `/opt/soulcuts/monitoring/releases/<full-sha>` and uses
   the existing global production release lock. It never invokes the application
   Compose file or migrates the database.
4. Installation validates Docker loopback-publishing safety, free disk, immutable
   pins and existing application health. It saves a private baseline, generates
   credentials, starts only its own project and verifies Grafana authentication,
   both datasources, dashboard, four scrape targets, eight service metrics and
   an explicitly synthetic log marker through Alloy/Loki/Grafana.
5. The collector cron is added without replacing pre-existing entries. Acceptance
   waits for a **future scheduled collection** to arrive, then checks all eight
   application container IDs, starts, image IDs and every environment hash are
   unchanged. The monitoring recovery marker is cleared only after success.

Private evidence: `/opt/soulcuts/monitoring/evidence/`. The password and raw
application logs are never included in acceptance output. The initial installer
refuses unknown existing monitoring state, duplicate cron blocks or outstanding
recovery fences. It is intentionally not an automatic upgrade/recovery tool.

## Recovery And Maintenance

If deployment fails, do not repeatedly dispatch it or delete the marker blindly.
Inspect only `soulcuts-monitoring` containers and private evidence, confirm the
application baseline, identify the failed phase, then plan an explicit bounded
recovery. Never use the application rollback or alter its recovery fences.

To stop collection for maintenance, remove **only** the marked monitoring cron
block, preserving all other cron entries. Stop only this Compose project using
the exact accepted release and image environment. Do not use `docker system
prune`, global volume cleanup or application service stop commands. Preserve all
monitoring volumes and credentials unless deliberate data removal is authorized.

Before future upgrades, back up Grafana's database/config and retained data using
service-appropriate consistency controls, test restore, and review new digests.
Check disk consumption and collector freshness regularly. This single-host stack
cannot observe the server during a total server outage.

Official references:

- https://grafana.com/docs/grafana/latest/setup-grafana/configure-docker/
- https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.file/
- https://grafana.com/docs/loki/latest/operations/storage/retention/
- https://prometheus.io/docs/prometheus/latest/storage/
