"""Staff password hashing."""

from app.core.passwords import MAX_BYTES, hash_password, spend_the_same_time, verify_password


def test_a_password_verifies_against_its_hash_and_nothing_else():
    hashed = hash_password("correct horse battery")
    assert hashed != "correct horse battery"
    assert verify_password("correct horse battery", hashed)
    assert not verify_password("correct horse batterx", hashed)


def test_the_same_password_hashes_differently_each_time():
    assert hash_password("correct horse battery") != hash_password("correct horse battery")


def test_a_password_longer_than_bcrypt_reads_is_wrong_not_an_error():
    hashed = hash_password("correct horse battery")
    assert not verify_password("x" * (MAX_BYTES + 1), hashed)


def test_multibyte_characters_count_as_bytes():
    # 37 two-byte characters is 74 bytes, over the limit even though it is only 37 characters
    assert not verify_password("é" * 37, hash_password("correct horse battery"))


def test_a_stored_value_that_is_not_bcrypt_never_matches():
    assert not verify_password("correct horse battery", "not-a-bcrypt-hash")


def test_the_decoy_check_runs_without_error_for_any_input():
    spend_the_same_time("anything")
    spend_the_same_time("x" * 500)
