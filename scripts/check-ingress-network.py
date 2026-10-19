#!/usr/bin/env python3
"""Fail closed on route/network collisions; no container mutations."""
import ipaddress
import json
import subprocess
import sys

SUBNET = ipaddress.ip_network('172.30.41.0/29')


def validate(routes, networks, expected_name):
    existing = [n for n in networks if n['Name'] == expected_name]
    bridge = None
    if existing:
        network = existing[0]
        ranges = [c.get('Subnet') for c in network.get('IPAM', {}).get('Config', [])]
        if ranges != [str(SUBNET)] or not network.get('Internal'):
            raise ValueError('Existing ingress network does not match the release boundary')
        bridge = network.get('Options', {}).get('com.docker.network.bridge.name') or 'br-' + network['Id'][:12]
    for route in routes:
        destination = route.get('dst', 'default')
        if destination == 'default':
            continue
        candidate = ipaddress.ip_network(destination, strict=False)
        if candidate.version == SUBNET.version and candidate.overlaps(SUBNET):
            if candidate.subnet_of(SUBNET) and route.get('dev') == bridge:
                continue
            raise ValueError('Ingress subnet overlaps a host route')
    for network in networks:
        for config in network.get('IPAM', {}).get('Config', []):
            if not config.get('Subnet'):
                continue
            candidate = ipaddress.ip_network(config['Subnet'])
            if candidate.version == SUBNET.version and candidate.overlaps(SUBNET) and network['Name'] != expected_name:
                raise ValueError('Ingress subnet overlaps another Docker network')


def main():
    routes = json.loads(subprocess.check_output(['ip', '-j', '-4', 'route', 'show', 'table', 'all']))
    ids = subprocess.check_output(['docker', 'network', 'ls', '-q'], text=True).split()
    networks = json.loads(subprocess.check_output(['docker', 'network', 'inspect', *ids])) if ids else []
    validate(routes, networks, sys.argv[1])
    print('Ingress subnet preflight passed')


if __name__ == '__main__':
    main()
