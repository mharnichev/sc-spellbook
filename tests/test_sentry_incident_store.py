import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('incident_preflight', ROOT / 'scripts/check-sentry-incident-store.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class IncidentStoreTests(unittest.TestCase):
    def test_runtime_accepts_private_store_and_safe_existing_sqlite_modes_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            root.chmod(0o700)
            MODULE.validate_files(root)
            self.assertEqual(list(root.iterdir()), [])
            for mode in (0o600, 0o640, 0o644):
                for name in MODULE.FILES:
                    file = root / name
                    file.write_bytes(b'existing synthetic sqlite bytes')
                    file.chmod(mode)
                MODULE.validate_files(root)
                for file in root.iterdir():
                    self.assertEqual(file.read_bytes(), b'existing synthetic sqlite bytes')
                    self.assertEqual(file.stat().st_mode & 0o777, mode)

    def test_runtime_rejects_unsafe_database_and_every_sidecar(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            root.chmod(0o700)
            for name in MODULE.FILES:
                file = root / name
                for mode in (0o000, 0o200, 0o400, 0o620, 0o602, 0o666):
                    file.touch()
                    file.chmod(mode)
                    with self.subTest(name=name, mode=oct(mode)), self.assertRaises(ValueError):
                        MODULE.validate_files(root)
                    file.unlink()
                file.mkdir()
                with self.assertRaises(ValueError):
                    MODULE.validate_files(root)
                file.rmdir()
                file.symlink_to(root / 'missing')
                with self.assertRaises(ValueError):
                    MODULE.validate_files(root)
                file.unlink()
                file.touch(mode=0o600)
                metadata = list(file.lstat())
                metadata[0] |= 0o4000
                with patch.object(MODULE, 'validate'), patch.object(Path, 'lstat', return_value=os.stat_result(metadata)):
                    with self.assertRaises(ValueError):
                        MODULE.validate_files(root)
                with patch.object(MODULE, 'validate'), patch.object(MODULE.os, 'geteuid', return_value=os.geteuid() + 1):
                    with self.assertRaisesRegex(ValueError, 'owned files'):
                        MODULE.validate_files(root)
                file.unlink()

    def test_runtime_read_failure_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            root.chmod(0o700)
            (root / MODULE.FILES[0]).touch(mode=0o600)
            with patch.object(MODULE.os, 'open', side_effect=PermissionError('unreadable')):
                with self.assertRaises(PermissionError):
                    MODULE.validate_files(root)

    def test_existing_private_directory_requires_actual_runtime_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve()
            path.chmod(0o700)
            MODULE.validate(path, str(os.geteuid()))
            with self.assertRaisesRegex(ValueError, 'ownership'):
                MODULE.validate(path, str(os.geteuid() + 1))
            for mode in (0o755, 0o750, 0o777, 0o1700):
                path.chmod(mode)
                with self.assertRaisesRegex(ValueError, '0700'):
                    MODULE.validate(path, str(os.geteuid()))
            path.chmod(0o700)

    def test_missing_file_and_symlink_paths_are_never_created_or_repaired(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            missing = root / 'missing'
            with self.assertRaises(FileNotFoundError):
                MODULE.validate(missing, str(os.geteuid()))
            self.assertFalse(missing.exists())
            file = root / 'file'
            file.touch(mode=0o700)
            target = root / 'target'
            target.mkdir(mode=0o700)
            link = root / 'link'
            link.symlink_to(target, target_is_directory=True)
            child = target / 'child'
            child.mkdir(mode=0o700)
            for path in (file, link, link / 'child'):
                with self.assertRaisesRegex(ValueError, 'real directories'):
                    MODULE.validate(path, str(os.geteuid()))
            self.assertTrue(link.is_symlink())

    def test_invalid_uid_fails_before_filesystem_access(self):
        for uid in ('', '-1', 'root', '0\n0', ' 0', '01'):
            with patch.object(Path, 'lstat') as lstat:
                with self.assertRaisesRegex(ValueError, 'runtime UID'):
                    MODULE.validate(MODULE.STORE, uid)
                lstat.assert_not_called()

    def test_deploy_checks_candidate_uid_without_mounting_or_starting_writers(self):
        source = (ROOT / 'scripts/deploy.sh').read_text()
        function = source.split('preflight_sentry_store() {', 1)[1].split('\n}', 1)[0]
        self.assertIn('--pull=never --network none --entrypoint python "${next_backend}"', function)
        self.assertIn('os.geteuid()', function)
        self.assertNotIn('compose', function)
        self.assertNotIn('mkdir', function)
        self.assertIn('--mount type=bind,src=/opt/soulcuts/data/sentry-incidents,dst=/state,readonly', function)
        self.assertIn('--read-only', function)
        self.assertIn('--cap-drop ALL', function)
        self.assertIn('"${next_backend}" - --runtime-store', function)
        branch = source.split('if [[ "${BACKEND_CHANGED}" == true ]]; then', 1)[1]
        self.assertLess(branch.index('preflight_sentry_store'), branch.index('WRITERS_STOPPING=true'))
        frontend = branch.split('\nelse\n  if [[ -z "${REQUIRED_SCOPE}" ]]; then', 1)[1]
        self.assertNotIn('preflight_sentry_store', frontend)


if __name__ == '__main__':
    unittest.main()
