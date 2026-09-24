"""Profile templates (#38): what one carries, and what applying it leaves alone."""

from qres_gui import templates

GAME = {
    "name": "Counter Test", "store": "steam", "enabled": True,
    "width": 1920, "height": 1080, "refresh": 120, "display": r"\\.\DISPLAY2",
    "hdr": True, "scaling": "aspect", "audio_device": "headset", "quick_restore": True,
    "commands": {"before": "taskkill /im Discord.exe", "after": ""},
    "watch": ["cs.exe"], "extra_args": "-novid", "engine_args": {"engine": "unity", "fullscreen": "on"},
    "launch": {"type": "uri", "uri": "steam://rungameid/10"}, "install_dir": r"C:\Games\Counter",
}


def test_a_template_carries_the_display_audio_and_commands_only():
    template = templates.make("  Couch  ", GAME)
    assert template == {
        "name": "Couch", "display": r"\\.\DISPLAY2", "width": 1920, "height": 1080, "refresh": 120,
        "hdr": True, "scaling": "aspect", "audio_device": "headset", "quick_restore": True,
        "commands": {"before": "taskkill /im Discord.exe"},
    }


def test_a_template_spells_out_leave_it_alone():
    """So applying it makes a game match, rather than keep bits of what it had."""
    template = templates.make("Plain", {"width": 2560, "height": 1440})
    assert template == {"name": "Plain", "display": "", "width": 2560, "height": 1440, "refresh": 0, "hdr": None,
                        "scaling": None, "audio_device": None, "quick_restore": False, "commands": {}}


def test_applying_leaves_the_games_identity_and_hooks_alone():
    other = {
        "name": "Stardew Valley", "store": "gog", "enabled": False,
        "width": 3440, "height": 1440, "refresh": 0, "hdr": False, "commands": {"after": "echo old"},
        "watch": ["Stardew Valley.exe"], "extra_args": "--skip", "install_dir": r"C:\Games\Stardew",
        "launch": {"type": "exe", "path": r"C:\Games\Stardew\Stardew Valley.exe", "args": "", "cwd": ""},
    }
    before = dict(other)
    templates.apply(other, templates.make("Couch", GAME))
    for key in ("name", "store", "enabled", "watch", "extra_args", "install_dir", "launch"):
        assert other[key] == before[key]
    assert "engine_args" not in other
    assert templates.settings_of(other) == templates.settings_of(GAME)


def test_applying_a_template_without_commands_clears_the_games():
    game = {"width": 1, "height": 1, "commands": {"before": "x"}}
    templates.apply(game, templates.make("Plain", {"width": 2560, "height": 1440}))
    assert "commands" not in game and (game["width"], game["hdr"]) == (2560, None)


def test_applying_copies_rather_than_shares():
    template = templates.make("Couch", GAME)
    game = {"width": 1, "height": 1}
    templates.apply(game, template)
    game["commands"]["before"] = "changed"
    assert template["commands"]["before"] == "taskkill /im Discord.exe"


def test_templates_from_a_hand_edited_config_are_checked():
    cfg = {"templates": [
        {"name": "Good", "width": "2560", "height": 1440, "hdr": "yes", "scaling": "sideways",
         "commands": {"before": 5, "after": " echo hi "}, "launch": {"uri": "not carried"}},
        {"name": "", "width": 1920, "height": 1080},
        {"name": "No size"},
        {"name": "Negative", "width": -1, "height": 1080},
        "not a template",
    ]}
    assert templates.load(cfg) == [{
        "name": "Good", "display": "", "width": 2560, "height": 1440, "refresh": 0, "hdr": None,
        "scaling": None, "audio_device": None, "quick_restore": False, "commands": {"after": "echo hi"},
    }]
    assert templates.load({}) == []


def test_names_match_whatever_their_case():
    saved = [templates.make("Couch", GAME), templates.make("Desk", GAME)]
    assert templates.find(saved, " desk ") == 1
    assert templates.find(saved, "Bed") == -1


def test_the_summary_shows_commands_word_for_word(monkeypatch):
    monkeypatch.setattr(templates.audio, "name", lambda device_id: "Headset")
    assert templates.summary(templates.make("Couch", GAME)) == [
        "1920 × 1080 @ 120 Hz", "Display 2", "HDR on", "Scaling: Keep aspect ratio", "Playback device: Headset",
        "Switches back the moment the game closes", "Before switching: taskkill /im Discord.exe",
    ]
    assert templates.summary(templates.make("Plain", {"width": 2560, "height": 1440})) == [
        "2560 × 1440, same refresh rate as the desktop", "Primary display",
    ]
