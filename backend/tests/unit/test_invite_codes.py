"""Short invitation codes: generation, the forgiving input rule, and display format.

The same rule lives in frontend/src/lib/inviteCode.ts; the cases here mirror its tests.
"""

import hashlib

from app.core.security import (
    INVITE_ALPHABET,
    INVITE_LENGTH,
    format_invite_code,
    invite_code_from_digest,
    new_invite_code,
    normalise_invite_code,
)


def test_new_codes_are_short_and_use_only_the_typeable_alphabet():
    codes = {new_invite_code() for _ in range(200)}
    assert len(codes) > 190  # 40 bits: repeats are vanishingly unlikely
    for code in codes:
        assert len(code) == INVITE_LENGTH
        assert set(code) <= set(INVITE_ALPHABET)


def test_the_alphabet_has_no_lookalikes():
    assert not set("ILOU") & set(INVITE_ALPHABET)
    assert len(set(INVITE_ALPHABET)) == 32


def test_a_digest_maps_to_the_same_code_every_time():
    digest = hashlib.sha256(b"invite:42:1").digest()
    assert invite_code_from_digest(digest) == invite_code_from_digest(digest)
    assert len(invite_code_from_digest(digest)) == INVITE_LENGTH
    assert invite_code_from_digest(bytes(5)) == "0" * INVITE_LENGTH
    assert invite_code_from_digest(b"\xff" * 5) == INVITE_ALPHABET[-1] * INVITE_LENGTH


def test_normalise_ignores_case_dashes_spaces_and_underscores():
    assert normalise_invite_code("abcd-efgh") == "ABCDEFGH"
    assert normalise_invite_code("  ab cd_ef gh ") == "ABCDEFGH"


def test_normalise_reads_lookalikes_as_digits():
    assert normalise_invite_code("O0O0-1I1L") == "00001111"


def test_normalise_leaves_the_long_hex_tokens_from_the_first_seed_alone():
    legacy = "a3f9c1d2e4b5a6f7c8d9e0f1"
    assert normalise_invite_code(legacy) == legacy
    assert normalise_invite_code(f"  {legacy}  ") == legacy


def test_normalise_leaves_other_input_as_typed_but_trimmed():
    assert normalise_invite_code(" ABCDEFGU ") == "ABCDEFGU"  # U is not in the alphabet
    assert normalise_invite_code("ABC") == "ABC"
    assert normalise_invite_code("ßßßß") == "ßßßß"  # not ASCII: never folded to SSSSSSSS


def test_every_generated_code_survives_normalisation_and_formatting():
    for _ in range(50):
        code = new_invite_code()
        assert normalise_invite_code(code) == code
        assert normalise_invite_code(format_invite_code(code)) == code
        assert normalise_invite_code(code.lower()) == code


def test_format_shows_a_short_code_as_two_groups_and_nothing_else():
    assert format_invite_code("ABCDEFGH") == "ABCD-EFGH"
    assert format_invite_code("a3f9c1d2e4b5a6f7c8d9e0f1") == "a3f9c1d2e4b5a6f7c8d9e0f1"
