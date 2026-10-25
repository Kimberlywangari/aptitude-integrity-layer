from app.services.events import clean_payload


def test_a_screenshot_event_keeps_only_a_known_key_combination():
    assert clean_payload("screenshot_attempt", {"combo": "Win+Shift+S", "x": 1}) == {
        "combo": "Win+Shift+S"
    }
    assert clean_payload("screenshot_attempt", {"combo": "anything the page makes up"}) is None
    assert clean_payload("screenshot_attempt", {"combo": 5}) is None
