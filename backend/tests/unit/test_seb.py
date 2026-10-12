from app.core.seb import (
    CONFIG_KEY_HEADER,
    REQUEST_HASH_HEADER,
    check_seb,
    request_hash,
)

URL = "http://localhost:5173/api/session/start"
KEY = "a1b2c3d4e5f6"


def test_known_url_key_and_hash_passes():
    headers = {REQUEST_HASH_HEADER: request_hash(URL, KEY)}
    result = check_seb(URL, headers, [KEY])
    assert result.verified and result.reason == "ok"


def test_hash_is_sha256_of_url_followed_by_key():
    # Independent of request_hash(): this is the SEB algorithm written out.
    import hashlib

    assert request_hash(URL, KEY) == hashlib.sha256((URL + KEY).encode()).hexdigest()


def test_config_key_header_is_accepted_too():
    headers = {CONFIG_KEY_HEADER: request_hash(URL, KEY)}
    assert check_seb(URL, headers, [KEY]).verified


def test_wrong_url_fails():
    headers = {REQUEST_HASH_HEADER: request_hash(URL, KEY)}
    result = check_seb(URL + "?x=1", headers, [KEY])
    assert not result.verified and result.reason == "mismatch"


def test_wrong_key_fails():
    headers = {REQUEST_HASH_HEADER: request_hash(URL, "some-other-key")}
    assert not check_seb(URL, headers, [KEY]).verified


def test_any_allowed_key_may_match():
    headers = {REQUEST_HASH_HEADER: request_hash(URL, "second")}
    assert check_seb(URL, headers, ["first", "second"]).verified


def test_missing_header_and_missing_keys_are_distinguished():
    assert check_seb(URL, {}, [KEY]).reason == "no_header"
    assert check_seb(URL, {REQUEST_HASH_HEADER: "x"}, []).reason == "no_keys_configured"


def test_hash_case_is_ignored():
    headers = {REQUEST_HASH_HEADER: request_hash(URL, KEY).upper()}
    assert check_seb(URL, headers, [KEY]).verified
