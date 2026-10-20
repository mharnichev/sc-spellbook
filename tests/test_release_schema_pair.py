from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/rehearse-shop-production-copy.py'
SPEC = importlib.util.spec_from_file_location('release_schema_pair', SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
TABLE = 'mono_checkbox_poll_state'
NAME = 'ck_mono_checkbox_poll_state_mono_checkbox_poll_kind'
OLD = "CHECK (kind::text = ANY (ARRAY['shop'::character varying, 'master'::character varying]::text[]))"
NEW = "CHECK (kind::text = ANY (ARRAY['shop'::character varying::text, 'master'::character varying::text]))"


def strict_base(source, restored, fixture):
    if source != restored:
        raise RuntimeError('Unrecognized remaining schema difference')
    return []


def metadata(definition):
    return dict(constraints=[[TABLE, NAME, 'c', definition, False, False, True]], functions=['unchanged'])


class ReleaseSchemaPairTests(unittest.TestCase):
    def test_exact_pair_keeps_metadata_and_input_unchanged(self):
        source, restored = metadata(OLD), metadata(NEW)
        saved = deepcopy(source)
        pairs = MODULE.compare_release_schema(source, restored, strict_base, {})
        self.assertEqual(source, saved)
        self.assertEqual(pairs, [dict(kind='constraint', table=TABLE, name=NAME,
                                     source_definition=OLD, restored_definition=NEW,
                                     source_sha256=hashlib.sha256(OLD.encode()).hexdigest(),
                                     restored_sha256=hashlib.sha256(NEW.encode()).hexdigest())])

    def test_identical_metadata_needs_no_exception(self):
        self.assertEqual(MODULE.compare_release_schema(metadata(OLD), metadata(OLD), strict_base, {}), [])

    def test_reverse_and_near_match_are_rejected(self):
        for old, new in ((NEW, OLD), (OLD + ' ', NEW), (OLD, NEW + ' '),
                         (OLD, NEW.replace("'master'", "'owner'"))):
            with self.subTest(old=old, new=new), self.assertRaises(RuntimeError):
                MODULE.compare_release_schema(metadata(old), metadata(new), strict_base, {})

    def test_identity_type_flags_duplicates_and_extra_labels_are_rejected(self):
        for index, value in ((0, 'other_table'), (1, NAME + '_other'), (2, 'u'),
                             (4, True), (5, True), (6, False)):
            restored = metadata(NEW)
            restored['constraints'][0][index] = value
            with self.subTest(index=index), self.assertRaises(RuntimeError):
                MODULE.compare_release_schema(metadata(OLD), restored, strict_base, {})
        restored = metadata(NEW)
        restored['constraints'].append(deepcopy(restored['constraints'][0]))
        with self.assertRaises(RuntimeError):
            MODULE.compare_release_schema(metadata(OLD), restored, strict_base, {})

    def test_unrelated_schema_changes_remain_rejected(self):
        restored = metadata(NEW)
        restored['functions'] = ['foreign change']
        with self.assertRaisesRegex(RuntimeError, 'remaining schema'):
            MODULE.compare_release_schema(metadata(OLD), restored, strict_base, {})

    def test_exact_raw_line_gate_still_rejects_other_ddl(self):
        pairs = MODULE.compare_release_schema(metadata(OLD), metadata(NEW), strict_base, {})
        old = "CHECK (((kind)::text = ANY ((ARRAY['shop'::character varying, 'master'::character varying])::text[])))"
        new = "CHECK (((kind)::text = ANY (ARRAY[('shop'::character varying)::text, ('master'::character varying)::text])))"
        before = ('    CONSTRAINT ' + NAME + ' ' + old + '\n').encode()
        after = ('    CONSTRAINT ' + NAME + ' ' + new + '\n').encode()
        MODULE.verify_raw_schema(before, after, pairs, {TABLE + ':' + NAME: old}, {TABLE + ':' + NAME: new}, {}, {})
        with self.assertRaisesRegex(RuntimeError, 'Unrecognized raw schema'):
            MODULE.verify_raw_schema(before, after + b'ALTER TABLE protected DROP COLUMN id;\n',
                                     pairs, {TABLE + ':' + NAME: old}, {TABLE + ':' + NAME: new}, {}, {})
