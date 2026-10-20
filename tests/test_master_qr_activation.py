import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/activate-master-qr.py'
SPEC=importlib.util.spec_from_file_location('master_qr_activation',SCRIPT)
MODULE=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

class MasterQRActivationTests(unittest.TestCase):
    def test_optimized_execution_refused_before_files_or_commands(self):
        result=subprocess.run([sys.executable,'-O',str(SCRIPT),'snapshot'],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Optimized execution is forbidden',result.stderr)
        self.assertEqual(result.stdout,'')

    def test_flag_replacement_preserves_every_other_byte(self):
        source=b'# unchanged\nSHOP_CHECKOUT_ENABLED=false\nUNRELATED="retained"\n'+b''.join(key.encode()+b'=false\n' for key in MODULE.FLAGS)
        result=MODULE.replacement_env(source)
        self.assertEqual(result.replace(b'=true\n',b'=false\n'),source)

    def test_ambiguous_and_enabled_dotenv_assignments_rejected(self):
        source=''.join(key+'=false\n' for key in MODULE.FLAGS).encode()
        cases=[source+b'MASTER_MONO_ENABLED=false\n',source+b'export MASTER_MONO_ENABLED=false\n',
               source.replace(b'MASTER_MONO_ENABLED=false',b'export MASTER_MONO_ENABLED=false'),
               source.replace(b'MASTER_MONO_ENABLED=false',b'MASTER_MONO_ENABLED=true')]
        for value in cases:
            with self.subTest(value=value):
                with self.assertRaises(RuntimeError): MODULE.replacement_env(value)

    def test_sql_mutates_only_sales_and_qr_with_snapshot_checks(self):
        before=[{key:(index if key=='id' else key=='is_active') for key in MODULE.FIELDS} for index in range(1,7)]
        after=MODULE.changed_rows(before,[1,2,3,4,5])
        self.assertEqual(after[-1],before[-1])
        sql=MODULE.grants_transaction(before,after,[1,2,3,4,5])
        self.assertIn('SET can_record_sales=v.sales,can_accept_qr_payments=v.qr',sql)
        self.assertIn('FOR UPDATE',sql)
        self.assertIn('Grant snapshot changed',sql)
        self.assertIn('Unrelated grant changed',sql)
        self.assertIn('touched!=5',sql)
        self.assertIn('m.admin_user_id=a.id AND m.is_active',sql)
        self.assertIn('PERFORM id FROM masters',sql)

    def test_foreign_lock_rejected_before_database_access(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'release.lock').mkdir()
            (root/'release.lock/pid').write_text(str(os.getppid()+1))
            with patch.object(MODULE,'APP',root), patch.dict(os.environ,{'RELEASE_LOCK_OWNER_PID':str(os.getppid())}), patch.object(MODULE,'query') as query:
                with self.assertRaises(RuntimeError): MODULE.main()
                query.assert_not_called()

    def test_wrong_pending_release_rejected_before_database_access(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'release.lock').mkdir()
            (root/'release.lock/pid').write_text(str(os.getppid()))
            env=root/'backend.env'
            env.write_bytes(b'fixture')
            env.chmod(0o600)
            (root/'backend-recovery-required').write_text('release=/wrong\nphase=pending_acceptance\n')
            with patch.object(MODULE,'APP',root),patch.object(MODULE,'ENV',env),patch.dict(os.environ,{'RELEASE_LOCK_OWNER_PID':str(os.getppid()),'EXPECTED_RELEASE':'/expected'}),patch.object(sys,'argv',['fixture','apply','/unused']),patch.object(MODULE.os,'kill') as probe,patch.object(MODULE,'query') as query:
                with self.assertRaises(RuntimeError): MODULE.main()
                probe.assert_called_once_with(os.getppid(),0)
                query.assert_not_called()

if __name__=='__main__': unittest.main()
