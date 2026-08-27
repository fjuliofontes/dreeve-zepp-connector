from dreeve_zepp_connector.config import _parse_device_names


def test_parse_device_names_parses_multiple_entries():
    mapping = _parse_device_names("9568513=Amazfit Balance 2;1234567=Old Watch")

    assert mapping == {"9568513": "Amazfit Balance 2", "1234567": "Old Watch"}


def test_parse_device_names_returns_empty_when_unset():
    assert _parse_device_names(None) == {}
    assert _parse_device_names("") == {}


def test_parse_device_names_skips_malformed_entries():
    # A bad mapping should degrade to "no device name for that entry," not
    # crash the whole export.
    mapping = _parse_device_names("9568513=Balance 2;no-equals-sign;=empty-id;1234567=")

    assert mapping == {"9568513": "Balance 2"}
