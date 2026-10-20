import test_english_wrapper as fixture


class ContentWrapperTests(fixture.EnglishWrapperTests):
    wrapper_name = 'run-shop-content-backfill.sh'
    helper_name = 'apply-shop-content-backfill.py'

    def test_private_recovery_pair_uses_new_operator_bound_to_pending_release(self):
        # Content recovery remains restricted to its exact release tools.
        result, calls, backend, _, _ = self.exercise(recovery=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])
        self.assertTrue(backend)
