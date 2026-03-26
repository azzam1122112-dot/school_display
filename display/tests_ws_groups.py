from django.test import SimpleTestCase

from display.ws_groups import (
    is_valid_ws_group_name,
    school_group_name,
    token_group_name,
)


class WsGroupNameTests(SimpleTestCase):
    def test_school_group_name_is_safe(self):
        name = school_group_name(5)
        self.assertEqual(name, "school_5")
        self.assertNotIn(":", name)
        self.assertTrue(is_valid_ws_group_name(name))

    def test_school_group_name_sanitizes_invalid_chars(self):
        name = school_group_name("5:west wing")
        self.assertEqual(name, "school_5_west_wing")
        self.assertNotIn(":", name)
        self.assertTrue(is_valid_ws_group_name(name))

    def test_token_group_name_is_deterministic_and_safe(self):
        token = "bc7a21db4013547bbd0535f2878af777bb9253a43e6a4350979e1c61f9a5a6af"
        a = token_group_name(token)
        b = token_group_name(token)
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("token_"))
        self.assertNotIn(":", a)
        self.assertTrue(is_valid_ws_group_name(a))

    def test_token_group_accepts_prehashed_sha256_input(self):
        digest = "a" * 64
        name = token_group_name(digest, hash_len=16)
        self.assertEqual(name, "token_" + ("a" * 16))
        self.assertTrue(is_valid_ws_group_name(name))

