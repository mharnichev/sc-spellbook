"""Disposable integration of actual pinned monitoring containers, no prod access."""
import datetime
import argparse
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import tempfile

parser=argparse.ArgumentParser()
parser.add_argument('--tmpfs',action='store_true')
args=parser.parse_args()
source = Path(__file__).resolve().parents[1]
root = Path(tempfile.mkdtemp(prefix='soulcuts-observability-test-'))
project = 'soulcuts-observability-test-' + secrets.token_hex(4)
assert project.startswith('soulcuts-observability-test-')
os.umask(0o077)
env = dict(os.environ, MONITORING_ROOT=str(root), MONITORING_UID=str(os.getuid()), MONITORING_GID=str(os.getgid()))
compose = ['docker', 'compose', '-p', project, '--env-file', str(source/'monitoring/images.env'), '-f', str(source/'monitoring/compose.yml')]
if args.tmpfs:
    override=root/'test-tmpfs.json'
    override.write_text(json.dumps({'services':{name:{'volumes':[{'type':'tmpfs','target':target,'tmpfs':{'size':size,'mode':0o777}}]} for name,target,size in [('grafana','/var/lib/grafana',134217728),('loki','/loki',134217728),('prometheus','/prometheus',134217728)]}}))
    compose += ['-f',str(override)]
log_fd, log_name = tempfile.mkstemp(prefix='soulcuts-monitoring-integration-', suffix='.log')
os.close(log_fd)
log = Path(log_name)
password = secrets.token_urlsafe(36)
marker = secrets.token_hex(8)
services = ['caddy','public-site','blog','admin-app','shop','backend','booking-sms-reminders','postgres']
now = datetime.datetime.now(datetime.timezone.utc)
for p in ['spool/logs','spool/metrics','data/alloy','secrets']:
    (root/p).mkdir(parents=True,mode=0o750)
for name in ['grafana_admin_password','grafana_secret_key']:
    p=root/'secrets'/name
    p.write_text((password if name.endswith('password') else secrets.token_urlsafe(36))+'\n')
    p.chmod(0o640)
for service in services:
    entry={'timestamp':now.isoformat().replace('+00:00','Z'),'service':service,'level':'INFO','event':'monitoring_smoke','message':'Synthetic monitoring verification '+marker}
    p=root/'spool/logs'/f'{service}.log';p.write_text(json.dumps(entry)+'\n');p.chmod(0o640)
lines=[]
for service in services:
    for metric,value in [('soulcuts_service_running',1),('soulcuts_service_healthy',1),('soulcuts_service_healthcheck_present',int(service!='booking-sms-reminders')),('soulcuts_container_cpu_percent',1),('soulcuts_container_memory_bytes',1048576)]:
        lines.append(f'{metric}{{service="{service}"}} {value}')
for metric,value in [('soulcuts_collector_last_success_unixtime',now.timestamp()),('soulcuts_collector_last_attempt_unixtime',now.timestamp()),('soulcuts_collector_success',1),('soulcuts_host_memory_total_bytes',16*2**30),('soulcuts_host_memory_available_bytes',12*2**30),('soulcuts_host_disk_size_bytes',100*2**30),('soulcuts_host_disk_free_bytes',80*2**30),('soulcuts_host_cpu_busy_ratio',.1)]:
    lines.append(f'{metric} {value}')
p=root/'spool/metrics/soulcuts.prom';p.write_text('\n'.join(lines)+'\n');p.chmod(0o644)
probe=socket.socket()
try:
    probe.bind(('127.0.0.1',3300))
finally:
    probe.close()
spec=importlib.util.spec_from_file_location('monitoring_verify',source/'monitoring/verify.py')
verify=importlib.util.module_from_spec(spec);spec.loader.exec_module(verify)
with log.open('a') as output:
    try:
        subprocess.run(compose+['up','-d','--no-deps','grafana','prometheus','loki','alloy','node-exporter'],env=env,stdout=output,stderr=output,check=True,timeout=120)
        result=verify.wait_ready(verify.Grafana('http://127.0.0.1:3300',password),marker=marker,timeout=180)
        result.update(project=project,synthetic_data_only=True,test_storage='tmpfs' if args.tmpfs else 'persistent')
        print(json.dumps(result))
    except Exception:
        subprocess.run(compose+['logs','--tail','80'],env=env,stdout=output,stderr=output,timeout=30)
        raise
    finally:
        stopped=subprocess.run(compose+['down','--volumes','--remove-orphans'],env=env,stdout=output,stderr=output,timeout=90)
        if stopped.returncode==0:
            shutil.rmtree(root)
        else:
            raise RuntimeError('Owned integration cleanup failed')
