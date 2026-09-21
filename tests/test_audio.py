import pytest

from qres_gui import audio


class _Endpoint:
    def __init__(self, ident, name):
        self.id, self.FriendlyName = ident, name


class _Utilities:
    devices = [_Endpoint("z", "Z speakers"), _Endpoint("a", "A headset")]
    selected = []

    @classmethod
    def GetAllDevices(cls, flow, state):
        assert flow == 0 and state == 1
        return cls.devices

    @classmethod
    def GetSpeakers(cls):
        return cls.devices[0]

    @classmethod
    def SetDefaultDevice(cls, ident, roles):
        cls.selected.append((ident, roles))


class _Flow:
    class eRender:
        value = 0


class _State:
    class ACTIVE:
        value = 1


class _Roles:
    eConsole = "console"
    eMultimedia = "media"
    eCommunications = "calls"


@pytest.fixture(autouse=True)
def fake_audio(monkeypatch):
    _Utilities.devices = [_Endpoint("z", "Z speakers"), _Endpoint("a", "A headset")]
    _Utilities.selected = []
    monkeypatch.setattr(audio, "_api", lambda: (_Utilities, _Flow, _State, _Roles))


def test_outputs_are_active_playback_devices_sorted_by_name():
    assert audio.outputs() == [audio.Device("a", "A headset"), audio.Device("z", "Z speakers")]


def test_no_active_outputs_is_a_valid_empty_list():
    _Utilities.devices = []
    assert audio.outputs() == []


def test_default_id_and_friendly_name():
    assert audio.default_id() == "z"
    assert audio.name("a") == "A headset"
    assert audio.name("missing") == "missing"


def test_set_default_sets_every_playback_role():
    audio.set_default("a")
    assert _Utilities.selected == [("a", ["console", "media", "calls"])]


def test_audio_errors_are_a_small_safe_surface(monkeypatch):
    monkeypatch.setattr(audio, "_api", lambda: (_ for _ in ()).throw(OSError("audio service down")))
    with pytest.raises(audio.AudioError, match="audio service down"):
        audio.outputs()
