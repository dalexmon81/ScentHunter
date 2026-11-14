import unittest

from gtin import is_valid_gtin


def _with_check_digit(body: str) -> str:
    total = 0
    weight = 3
    for digit in reversed(body):
        total += int(digit) * weight
        weight = 1 if weight == 3 else 3
    return body + str((10 - total % 10) % 10)


class GTINValidationTests(unittest.TestCase):
    def test_accepts_all_supported_gs1_lengths(self):
        for length in (8, 12, 13, 14):
            with self.subTest(length=length):
                value = _with_check_digit("1234567"[:length - 1] if length == 8 else "1" * (length - 1))
                self.assertTrue(is_valid_gtin(value))

    def test_rejects_wrong_check_digit(self):
        self.assertFalse(is_valid_gtin("4006381333932"))

    def test_rejects_unsupported_lengths_and_non_ascii_digits(self):
        self.assertFalse(is_valid_gtin("1234567890"))
        self.assertFalse(is_valid_gtin("１２３４５６７８"))


if __name__ == "__main__":
    unittest.main()
