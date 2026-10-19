import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('deployed_images', ROOT / 'scripts/verify-deployed-images.py')
images = importlib.util.module_from_spec(spec)
spec.loader.exec_module(images)


class DeployedImagesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'versions').mkdir()
        self.refs = {key: 'registry.example/' + key.lower() + '@sha256:' + 'a' * 64
                     for key in images.SERVICES.values()}
        # Preserve legacy public/blog commit tags; do not force repinning them.
        self.refs['PUBLIC_SITE_IMAGE'] = 'registry.example/public:' + 'b' * 40
        self.refs['BLOG_IMAGE'] = 'registry.example/blog:' + 'c' * 40
        self.path = self.root / 'versions/production.env'
        self.save()
        self.ids = {service: hashlib.sha256(service.encode()).hexdigest() for service in images.SERVICES}
        self.by_id = {value: service for service, value in self.ids.items()}
        self.calls = []

    def save(self):
        self.path.write_text('\n'.join(f'{key}={value}' for key, value in self.refs.items()))

    def image_id(self, service):
        return 'sha256:' + hashlib.sha256(self.refs[images.SERVICES[service]].encode()).hexdigest()

    def query(self, args):
        self.calls.append(args)
        if args[:3] == ['docker', 'image', 'inspect']:
            return 'sha256:' + hashlib.sha256(args[-1].encode()).hexdigest()
        if args[-3:-1] == ['ps', '-q']:
            return self.ids[args[-1]]
        if args[:2] == ['docker', 'inspect']:
            service = self.by_id[args[-1]]
            return '|'.join((self.image_id(service), 'true', service, 'soulcuts'))
        raise AssertionError('Unexpected Docker action')

    def test_matching_config_image_ids_accept_all_services_without_full_config_or_pull(self):
        with patch.object(images, 'command', side_effect=self.query), patch.dict(os.environ, {'BACKEND_IMAGE': 'wrong-shell-override'}):
            images.verify(self.root, 'soulcuts')
            self.assertEqual(os.environ['BACKEND_IMAGE'], 'wrong-shell-override')
        self.assertEqual(sum(call[:2] == ['docker', 'inspect'] for call in self.calls), 8)
        self.assertFalse(any('config' in call or 'pull' in call for call in self.calls))
        self.assertNotEqual(self.image_id('backend'), self.refs['BACKEND_IMAGE'].split('@')[1])

    def test_each_service_image_mismatch_refuses(self):
        for service in images.SERVICES:
            def query(args):
                value = self.query(args)
                if args[:2] == ['docker', 'inspect'] and args[-1] == self.ids[service]:
                    return 'sha256:' + '0' * 64 + value[value.index('|'):]
                return value
            with self.subTest(service=service), patch.object(images, 'command', side_effect=query):
                with self.assertRaises(images.VerificationError):
                    images.verify(self.root, 'soulcuts')

    def test_no_container_multiple_containers_stopped_or_wrong_labels_refuse(self):
        for value in ('', self.ids['backend'] + '\n' + 'f' * 64, 'invalid-id'):
            def query(args):
                return value if args[-3:] == ['ps', '-q', 'backend'] else self.query(args)
            with self.subTest(value=value), patch.object(images, 'command', side_effect=query):
                with self.assertRaises(images.VerificationError):
                    images.verify(self.root, 'soulcuts')
        for suffix in ('false|backend|soulcuts', 'true|other|soulcuts', 'true|backend|other'):
            def query(args):
                return self.image_id('backend') + '|' + suffix if args[:2] == ['docker', 'inspect'] else self.query(args)
            with self.subTest(suffix=suffix), patch.object(images, 'command', side_effect=query):
                with self.assertRaises(images.VerificationError):
                    images.verify(self.root, 'soulcuts')

    def test_new_pins_require_full_lowercase_sha256_legacy_tags_stay_unchanged(self):
        for ref in ('registry.example/api:latest', 'registry.example/api@sha256:abc',
                    'registry.example/api@sha256:' + 'A' * 64):
            self.refs['BACKEND_IMAGE'] = ref
            self.save()
            with self.subTest(ref=ref), self.assertRaises(images.VerificationError):
                images.pins(self.path)

    def test_docker_errors_and_timeouts_are_sanitized_and_bounded(self):
        with patch.object(images.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', 'PRIVATE_SENTINEL')) as run:
            with self.assertRaisesRegex(images.VerificationError, '^Docker query failed$'):
                images.command(['docker', 'image', 'inspect', 'synthetic'])
            self.assertEqual(run.call_args.kwargs['timeout'], 15)
        with patch.object(images.subprocess, 'run', side_effect=subprocess.TimeoutExpired('PRIVATE_SENTINEL', 15)):
            with self.assertRaisesRegex(images.VerificationError, '^Docker query unavailable or timed out$'):
                images.command(['docker', 'inspect', 'synthetic'])


if __name__ == '__main__':
    unittest.main()
