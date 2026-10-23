from copy import deepcopy
import ast
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/rehearse-shop-production-copy.py'
SPEC = importlib.util.spec_from_file_location('release_schema_pair', SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
TABLE = 'mono_checkbox_poll_state'
NAME = 'ck_mono_checkbox_poll_state_mono_checkbox_poll_kind'
OLD = "CHECK (kind::text = ANY (ARRAY['shop'::character varying, 'master'::character varying]::text[]))"
NEW = "CHECK (kind::text = ANY (ARRAY['shop'::character varying::text, 'master'::character varying::text]))"
ADMISSION_TABLE = 'shop_ingress_admissions'
ADMISSION_NAME = 'ck_shop_ingress_admissions_action'
ADMISSION_OLD = "CHECK (action::text = ANY (ARRAY['otp_send'::character varying, 'otp_verify'::character varying, 'checkout'::character varying, 'feedback'::character varying, 'review'::character varying, 'profile'::character varying, 'search'::character varying, 'cart'::character varying]::text[]))"
ADMISSION_NEW = "CHECK (action::text = ANY (ARRAY['otp_send'::character varying::text, 'otp_verify'::character varying::text, 'checkout'::character varying::text, 'feedback'::character varying::text, 'review'::character varying::text, 'profile'::character varying::text, 'search'::character varying::text, 'cart'::character varying::text]))"
# Observed from the pinned PostgreSQL 16.15 image, before/after pg_dump + pg_restore.
ADMISSION_TEN_OLD = "CHECK (action::text = ANY (ARRAY['otp_send'::character varying, 'otp_verify'::character varying, 'checkout'::character varying, 'feedback'::character varying, 'review'::character varying, 'profile'::character varying, 'search'::character varying, 'cart'::character varying, 'reminder'::character varying, 'reminder_email'::character varying]::text[]))"
ADMISSION_TEN_NEW = "CHECK (action::text = ANY (ARRAY['otp_send'::character varying::text, 'otp_verify'::character varying::text, 'checkout'::character varying::text, 'feedback'::character varying::text, 'review'::character varying::text, 'profile'::character varying::text, 'search'::character varying::text, 'cart'::character varying::text, 'reminder'::character varying::text, 'reminder_email'::character varying::text]))"
STATE_TABLE = 'checkout_reminders'
STATE_NAME = 'ck_checkout_reminders_checkout_reminder_state'
STATE_OLD = "CHECK (state::text = ANY (ARRAY['pending'::character varying, 'attempting'::character varying, 'retry'::character varying, 'sent'::character varying, 'dry_run'::character varying, 'uncertain'::character varying, 'cancelled'::character varying, 'completed'::character varying, 'expired'::character varying, 'suppressed'::character varying]::text[]))"
STATE_NEW = "CHECK (state::text = ANY (ARRAY['pending'::character varying::text, 'attempting'::character varying::text, 'retry'::character varying::text, 'sent'::character varying::text, 'dry_run'::character varying::text, 'uncertain'::character varying::text, 'cancelled'::character varying::text, 'completed'::character varying::text, 'expired'::character varying::text, 'suppressed'::character varying::text]))"
NEW_PAIRS = ((ADMISSION_TABLE, ADMISSION_NAME, ADMISSION_TEN_OLD, ADMISSION_TEN_NEW),
             (STATE_TABLE, STATE_NAME, STATE_OLD, STATE_NEW))


def strict_base(source, restored, fixture):
    if source != restored:
        raise RuntimeError('Unrecognized remaining schema difference')
    return []


def metadata(definition, table=TABLE, name=NAME):
    return dict(constraints=[[table, name, 'c', definition, False, False, True]], functions=['unchanged'])


class ReleaseSchemaPairTests(unittest.TestCase):
    def test_exact_observed_0142_pairs_preserve_both_inputs_and_hashes(self):
        for table, name, old, new in NEW_PAIRS:
            with self.subTest(table=table):
                source, restored = metadata(old, table, name), metadata(new, table, name)
                saved = deepcopy((source, restored))
                pairs = MODULE.compare_release_schema(source, restored, strict_base, {})
                self.assertEqual((source, restored), saved)
                self.assertEqual(pairs, [dict(kind='constraint', table=table, name=name,
                    source_definition=old, restored_definition=new,
                    source_sha256=hashlib.sha256(old.encode()).hexdigest(),
                    restored_sha256=hashlib.sha256(new.encode()).hexdigest())])
                self.assertEqual(MODULE.compare_release_schema(source, source, strict_base, {}), [])
                self.assertEqual(MODULE.compare_release_schema(restored, restored, strict_base, {}), [])

    def test_0142_pairs_reject_reverse_near_match_labels_order_and_cast_mutations(self):
        for table, name, old, new in NEW_PAIRS:
            labels = ['reminder', 'reminder_email'] if table == ADMISSION_TABLE else ['pending', 'attempting']
            first, second = labels
            reordered = new.replace(f"'{first}'", "'placeholder'").replace(f"'{second}'", f"'{first}'").replace("'placeholder'", f"'{second}'")
            for before, after in (
                (new, old), (old + ' ', new), (old, new + ' '),
                (old, new.replace('ANY', 'ALL')), (old, reordered),
                (old, new.replace(f"'{first}'", "'unreviewed'")),
                (old.replace(f"'{first}'", "'unreviewed'"), new.replace(f"'{first}'", "'unreviewed'")),
                (old, new.replace(f", '{second}'::character varying::text", '')),
                (old, new.replace(']))', ", 'extra'::character varying::text]))")),
                (old, new.replace('character varying::text', 'text')),
            ):
                with self.subTest(table=table, before=before, after=after), self.assertRaises(RuntimeError):
                    MODULE.compare_release_schema(metadata(before, table, name), metadata(after, table, name), strict_base, {})

    def test_0142_pairs_reject_metadata_missing_duplicates_and_unrelated_ddl(self):
        for table, name, old, new in NEW_PAIRS:
            for index, value in ((0, 'other_table'), (1, name + '_other'), (2, 'u'), (4, True), (5, True), (6, False)):
                restored = metadata(new, table, name)
                restored['constraints'][0][index] = value
                with self.subTest(table=table, index=index), self.assertRaises(RuntimeError):
                    MODULE.compare_release_schema(metadata(old, table, name), restored, strict_base, {})
            for side in ('source', 'restored'):
                source, restored = metadata(old, table, name), metadata(new, table, name)
                target = source if side == 'source' else restored
                target['constraints'].append(deepcopy(target['constraints'][0]))
                with self.subTest(table=table, duplicate=side), self.assertRaises(RuntimeError):
                    MODULE.compare_release_schema(source, restored, strict_base, {})
                target['constraints'] = []
                with self.subTest(table=table, missing=side), self.assertRaises(RuntimeError):
                    MODULE.compare_release_schema(source, restored, strict_base, {})
            for category in ('functions', 'indexes', 'columns', 'triggers'):
                source, restored = metadata(old, table, name), metadata(new, table, name)
                source[category], restored[category] = ['unchanged'], ['changed']
                with self.subTest(table=table, category=category), self.assertRaises(RuntimeError):
                    MODULE.compare_release_schema(source, restored, strict_base, {})

    def test_admission_alternatives_cannot_mix_eight_and_ten_action_definitions(self):
        for old, new in ((ADMISSION_OLD, ADMISSION_TEN_NEW), (ADMISSION_TEN_OLD, ADMISSION_NEW)):
            with self.subTest(old=old), self.assertRaises(RuntimeError):
                MODULE.compare_release_schema(metadata(old, ADMISSION_TABLE, ADMISSION_NAME),
                    metadata(new, ADMISSION_TABLE, ADMISSION_NAME), strict_base, {})

    def test_three_observed_constraints_coexist_without_duplicate_admission_pairs(self):
        source, restored = metadata(OLD), metadata(NEW)
        for table, name, old, new in NEW_PAIRS:
            source['constraints'] += metadata(old, table, name)['constraints']
            restored['constraints'] += metadata(new, table, name)['constraints']
        pairs = MODULE.compare_release_schema(source, restored, strict_base, {})
        self.assertEqual(len(pairs), 3)
        self.assertEqual(len({(pair['table'], pair['name']) for pair in pairs}), 3)

    def test_observed_0142_raw_definitions_only_replace_the_two_exact_dump_lines(self):
        compact = (
            (ADMISSION_TABLE, ADMISSION_NAME, ADMISSION_TEN_OLD, ADMISSION_TEN_NEW,
             "CHECK (((action)::text = ANY ((ARRAY['otp_send'::character varying, 'otp_verify'::character varying, 'checkout'::character varying, 'feedback'::character varying, 'review'::character varying, 'profile'::character varying, 'search'::character varying, 'cart'::character varying, 'reminder'::character varying, 'reminder_email'::character varying])::text[])))",
             "CHECK (((action)::text = ANY (ARRAY[('otp_send'::character varying)::text, ('otp_verify'::character varying)::text, ('checkout'::character varying)::text, ('feedback'::character varying)::text, ('review'::character varying)::text, ('profile'::character varying)::text, ('search'::character varying)::text, ('cart'::character varying)::text, ('reminder'::character varying)::text, ('reminder_email'::character varying)::text])))"),
            (STATE_TABLE, STATE_NAME, STATE_OLD, STATE_NEW,
             "CHECK (((state)::text = ANY ((ARRAY['pending'::character varying, 'attempting'::character varying, 'retry'::character varying, 'sent'::character varying, 'dry_run'::character varying, 'uncertain'::character varying, 'cancelled'::character varying, 'completed'::character varying, 'expired'::character varying, 'suppressed'::character varying])::text[])))",
             "CHECK (((state)::text = ANY (ARRAY[('pending'::character varying)::text, ('attempting'::character varying)::text, ('retry'::character varying)::text, ('sent'::character varying)::text, ('dry_run'::character varying)::text, ('uncertain'::character varying)::text, ('cancelled'::character varying)::text, ('completed'::character varying)::text, ('expired'::character varying)::text, ('suppressed'::character varying)::text])))"),
        )
        source, restored = dict(constraints=[]), dict(constraints=[])
        old_constraints, new_constraints = {}, {}
        old_lines, new_lines = [], []
        for table, name, old, new, raw_old, raw_new in compact:
            source['constraints'] += metadata(old, table, name)['constraints']
            restored['constraints'] += metadata(new, table, name)['constraints']
            old_constraints[table + ':' + name] = raw_old
            new_constraints[table + ':' + name] = raw_new
            old_lines.append('    CONSTRAINT ' + name + ' ' + raw_old + ',\n')
            new_lines.append('    CONSTRAINT ' + name + ' ' + raw_new + ',\n')
        pairs = MODULE.compare_release_schema(source, restored, strict_base, {})
        before, after = ''.join(old_lines).encode(), ''.join(new_lines).encode()
        MODULE.verify_raw_schema(before, after, pairs, old_constraints, new_constraints, {}, {})
        for mutated in (after + b'ALTER TABLE protected DROP COLUMN id;\n',
                        after.replace(b"'suppressed'", b"'unreviewed'"),
                        after.replace(b'character varying', b'character'),
                        after + b'CREATE FUNCTION unreviewed() RETURNS int AS \'SELECT 1\' LANGUAGE SQL;\n'):
            with self.subTest(mutated=mutated), self.assertRaises(RuntimeError):
                MODULE.verify_raw_schema(before, mutated, pairs, old_constraints, new_constraints, {}, {})
        with self.assertRaises(RuntimeError):
            MODULE.verify_raw_schema(before + old_lines[0].encode(), after, pairs,
                                     old_constraints, new_constraints, {}, {})

    def test_private_schema_metadata_survives_comparator_failure_without_overwrite(self):
        source, restored = metadata(STATE_OLD, STATE_TABLE, STATE_NAME), metadata('unreviewed', STATE_TABLE, STATE_NAME)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            MODULE.save_schema_metadata(output, source, restored)
            with self.assertRaises(RuntimeError):
                MODULE.compare_release_schema(source, restored, strict_base, {})
            for name, value in (('before-schema.json', source), ('after-schema.json', restored)):
                path = output / name
                self.assertEqual(json.loads(path.read_text()), value)
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                MODULE.save_schema_metadata(output, {}, {})
            self.assertEqual(json.loads((output / 'before-schema.json').read_text()), source)

    def test_main_saves_schema_metadata_before_finite_comparator_execution(self):
        calls = [node for node in ast.walk(ast.parse(inspect.getsource(MODULE.main))) if isinstance(node, ast.Call)]
        save = next(node for node in calls if isinstance(node.func, ast.Name) and node.func.id == 'save_schema_metadata')
        compare = next(node for node in calls if isinstance(node.func, ast.Name) and node.func.id == 'execute'
            and any(isinstance(child, ast.Name) and child.id == 'FINITE_COMPARISON' for child in ast.walk(node)))
        self.assertLess(save.lineno, compare.lineno)

    def test_exact_observed_admission_pair_preserves_inputs_and_only_accepts_its_identity(self):
        source = metadata(ADMISSION_OLD, ADMISSION_TABLE, ADMISSION_NAME)
        restored = metadata(ADMISSION_NEW, ADMISSION_TABLE, ADMISSION_NAME)
        saved = deepcopy(source)
        pairs = MODULE.compare_release_schema(source, restored, strict_base, {})
        self.assertEqual(source, saved)
        self.assertEqual(pairs, [dict(kind='constraint', table=ADMISSION_TABLE, name=ADMISSION_NAME,
                                     source_definition=ADMISSION_OLD, restored_definition=ADMISSION_NEW,
                                     source_sha256=hashlib.sha256(ADMISSION_OLD.encode()).hexdigest(),
                                     restored_sha256=hashlib.sha256(ADMISSION_NEW.encode()).hexdigest())])
        for old, new in ((ADMISSION_NEW, ADMISSION_OLD), (ADMISSION_OLD + ' ', ADMISSION_NEW),
                         (ADMISSION_OLD, ADMISSION_NEW.replace('ANY', 'ALL')),
                         (ADMISSION_OLD, ADMISSION_NEW.replace("'cart'", "'other'")),
                         (ADMISSION_OLD, ADMISSION_NEW.replace(", 'cart'::character varying::text", ''))):
            with self.subTest(old=old, new=new), self.assertRaises(RuntimeError):
                MODULE.compare_release_schema(metadata(old, ADMISSION_TABLE, ADMISSION_NAME),
                                              metadata(new, ADMISSION_TABLE, ADMISSION_NAME), strict_base, {})

    def test_admission_pair_never_accepts_metadata_or_unrelated_schema_drift(self):
        for index, value in ((0, 'other_table'), (1, ADMISSION_NAME + '_other'), (2, 'u'),
                             (4, True), (5, True), (6, False)):
            restored = metadata(ADMISSION_NEW, ADMISSION_TABLE, ADMISSION_NAME)
            restored['constraints'][0][index] = value
            with self.subTest(index=index), self.assertRaises(RuntimeError):
                MODULE.compare_release_schema(metadata(ADMISSION_OLD, ADMISSION_TABLE, ADMISSION_NAME), restored, strict_base, {})
        for change in ('duplicate', 'function'):
            restored = metadata(ADMISSION_NEW, ADMISSION_TABLE, ADMISSION_NAME)
            if change == 'duplicate':
                restored['constraints'].append(deepcopy(restored['constraints'][0]))
            else:
                restored['functions'] = ['changed']
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                MODULE.compare_release_schema(metadata(ADMISSION_OLD, ADMISSION_TABLE, ADMISSION_NAME), restored, strict_base, {})

    def test_both_audited_pairs_can_coexist_without_hiding_extra_raw_ddl(self):
        source, restored = metadata(OLD), metadata(NEW)
        source['constraints'] += metadata(ADMISSION_OLD, ADMISSION_TABLE, ADMISSION_NAME)['constraints']
        restored['constraints'] += metadata(ADMISSION_NEW, ADMISSION_TABLE, ADMISSION_NAME)['constraints']
        pairs = MODULE.compare_release_schema(source, restored, strict_base, {})
        self.assertEqual(len(pairs), 2)
        admission_old = "CHECK (((action)::text = ANY ((ARRAY['otp_send'::character varying, 'otp_verify'::character varying, 'checkout'::character varying, 'feedback'::character varying, 'review'::character varying, 'profile'::character varying, 'search'::character varying, 'cart'::character varying])::text[])))"
        admission_new = "CHECK (((action)::text = ANY (ARRAY[('otp_send'::character varying)::text, ('otp_verify'::character varying)::text, ('checkout'::character varying)::text, ('feedback'::character varying)::text, ('review'::character varying)::text, ('profile'::character varying)::text, ('search'::character varying)::text, ('cart'::character varying)::text])))"
        admission_pairs = [pair for pair in pairs if pair['table'] == ADMISSION_TABLE]
        before = ('    CONSTRAINT ' + ADMISSION_NAME + ' ' + admission_old + '\n').encode()
        after = ('    CONSTRAINT ' + ADMISSION_NAME + ' ' + admission_new + '\n').encode()
        constraints_old = {ADMISSION_TABLE + ':' + ADMISSION_NAME: admission_old}
        constraints_new = {ADMISSION_TABLE + ':' + ADMISSION_NAME: admission_new}
        MODULE.verify_raw_schema(before, after, admission_pairs, constraints_old, constraints_new, {}, {})
        with self.assertRaisesRegex(RuntimeError, 'Unrecognized raw schema'):
            MODULE.verify_raw_schema(before, after + b'ALTER TABLE protected DROP COLUMN id;\n',
                                     admission_pairs, constraints_old, constraints_new, {}, {})

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
