"""The chord track, the project file, and the appliance config."""
from __future__ import annotations

from dataclasses import replace

import pytest

from core.bass import BassSpec
from core.chords import VoicingSpec, parse_chord
from core.chordset import diatonic
from core.config import AppConfig, load_config
from core.events import PPQN, TICKS_PER_BAR
from core.project import (EXTENSION, Project, default_project, list_projects,
                          style_from_dict, style_to_dict)
from core.song import (ChordStep, Song, from_symbols, quantize_position,
                       valid_section)
from core.style import MAIN_A, MAIN_B
from data.styles import factory_styles


# --- song ---------------------------------------------------------------------

def test_a_new_song_is_empty_and_says_so():
    assert Song().empty
    assert Song().chord_at(0) is None


def test_steps_are_kept_in_position_order_however_they_were_added():
    song = Song(steps=(ChordStep(4, 0, parse_chord("G")),
                       ChordStep(0, 0, parse_chord("C")),
                       ChordStep(2, 2, parse_chord("F"))))
    assert [(s.bar, s.beat) for s in song.steps] == [(0, 0), (2, 2), (4, 0)]


def test_the_chord_in_force_is_the_latest_change_at_or_before_the_position():
    song = from_symbols(["C", "F", "G", "C"])
    assert song.chord_at(0).symbol() == "C"
    assert song.chord_at(1, 3).symbol() == "F"
    assert song.chord_at(9).symbol() == "C"     # past the end, still the last


def test_a_song_has_no_chord_before_its_first_change():
    song = Song(steps=(ChordStep(2, 0, parse_chord("C")),))
    assert song.chord_at(0) is None
    assert song.chord_at(2).symbol() == "C"


def test_the_lookahead_wraps_for_a_looping_song():
    song = from_symbols(["C", "F"])
    assert song.next_chord_after(0).symbol() == "F"
    assert song.next_chord_after(1).symbol() == "C"


def test_the_lookahead_runs_out_for_a_one_shot_song():
    song = replace(from_symbols(["C", "F"]), loop=False)
    assert song.next_chord_after(1) is None


def test_section_markers_are_sticky_until_the_next_one():
    song = Song(steps=(ChordStep(0, 0, parse_chord("C"), section=MAIN_A),
                       ChordStep(2, 0, parse_chord("F")),
                       ChordStep(4, 0, parse_chord("G"), section=MAIN_B)))
    assert song.section_at(0) == MAIN_A
    assert song.section_at(3) == MAIN_A
    assert song.section_at(5) == MAIN_B
    assert song.markers() == ((0, MAIN_A), (4, MAIN_B))


def test_writing_past_the_end_grows_the_song():
    song = from_symbols(["C"]).with_step(ChordStep(11, 0, parse_chord("G")))
    assert song.bars == 12


def test_writing_at_an_occupied_position_replaces_it():
    song = from_symbols(["C", "F"])
    song = song.with_step(ChordStep(1, 0, parse_chord("Ab7")))
    assert song.chord_at(1).symbol() == "Ab7"
    assert len(song.steps) == 2


def test_erasing_and_clearing():
    song = from_symbols(["C", "F", "G"])
    assert len(song.without_step(1).steps) == 2
    assert song.cleared().empty


def test_transposing_a_song_moves_every_chord():
    song = from_symbols(["C", "F"]).transposed(2)
    assert [s.chord.symbol() for s in song.steps] == ["D", "G"]


def test_songs_round_trip_through_their_dict_form():
    song = from_symbols(["Cmaj7", "F#m7b5", "G7"], name="TUNE")
    restored = Song.from_dict(song.to_dict())
    assert restored.name == song.name
    assert [s.chord.symbol() for s in restored.steps] == \
        [s.chord.symbol() for s in song.steps]


def test_quantize_snaps_a_live_tap_to_the_nearest_bar():
    assert quantize_position(TICKS_PER_BAR - 10) == (1, 0)
    assert quantize_position(10) == (0, 0)
    assert quantize_position(TICKS_PER_BAR + PPQN, grid_beats=1) == (1, 1)


def test_valid_section_rejects_invented_names():
    assert valid_section(MAIN_A)
    assert not valid_section("chorus")


# --- project ------------------------------------------------------------------

def test_a_default_project_is_playable():
    project = default_project()
    assert project.style.has(MAIN_A)
    assert project.chordset.chord_at(0) is not None


def test_projects_round_trip_through_json(tmp_path):
    project = replace(
        default_project(), name="TUNE", bpm=97.5,
        chordset=diatonic(9, "minor", sevenths=True),
        song=from_symbols(["Am7", "D7", "Gmaj7"]),
        voicing=VoicingSpec(style="drop2", dial=2, octave=-1),
        bass=BassSpec(mode="walk", pattern="x.x.x.x.x.x.x.x.", dial=1),
        strum=4, latch=False, song_mode=True)
    path = tmp_path / f"tune{EXTENSION}"
    project.save(path)
    loaded = Project.load(path)
    assert loaded.name == "TUNE" and loaded.bpm == 97.5
    assert loaded.voicing == project.voicing
    assert loaded.bass == project.bass
    assert loaded.strum == 4 and loaded.latch is False and loaded.song_mode
    assert [s.chord.symbol() for s in loaded.song.steps] == \
        ["Am7", "D7", "Gmaj7"]


def test_saving_is_atomic(tmp_path):
    path = tmp_path / f"a{EXTENSION}"
    default_project().save(path)
    assert [p.name for p in tmp_path.iterdir()] == [f"a{EXTENSION}"]


def test_every_factory_style_survives_a_full_round_trip():
    for style in factory_styles():
        restored = style_from_dict(style_to_dict(style))
        assert restored.name == style.name
        assert restored.swing == style.swing
        assert tuple(p.id for p in restored.parts) == \
            tuple(p.id for p in style.parts)
        for name, section in style.sections.items():
            other = restored.sections[name]
            assert other.bars == section.bars
            for part_id, phrase in section.phrases.items():
                assert other.phrases[part_id].notes == phrase.notes


def test_a_style_reference_by_name_resolves_to_the_factory_style():
    style = style_from_dict({"name": "FUNK"})
    assert style.name == "FUNK" and style.has(MAIN_B)


def test_an_unknown_style_name_falls_back_rather_than_raising():
    assert style_from_dict({"name": "NOPE"}).name == factory_styles()[0].name


def test_a_newer_schema_loads_with_unknown_fields_ignored():
    data = default_project().to_dict()
    data["schema_version"] = 99
    data["future_feature"] = {"nothing": True}
    assert Project.from_dict(data).name == "INIT"


def test_list_projects_is_newest_first(tmp_path):
    import os
    import time
    for index, name in enumerate(("a", "b", "c")):
        path = tmp_path / f"{name}{EXTENSION}"
        default_project().save(path)
        os.utime(path, (time.time() + index, time.time() + index))
    assert [p.stem for p in list_projects(tmp_path)] == ["c", "b", "a"]


def test_list_projects_copes_with_a_missing_directory(tmp_path):
    assert list_projects(tmp_path / "nope") == ()


# --- config -------------------------------------------------------------------

def test_no_config_file_yields_defaults():
    config = load_config(None)
    assert config.display.width == 1280
    assert config.midi.backend == "auto"


def test_a_missing_file_yields_defaults(tmp_path):
    assert load_config(tmp_path / "absent.toml") == AppConfig()


def test_a_config_file_overrides_only_what_it_names(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("""
[display]
width = 480
height = 800
fullscreen = true

[paths]
data_dir = "/var/lib/chordranger"

[midi]
out_port = "pisound"
prefer = ["pisound", "usb"]

[engine]
rt_priority = 55

[button]
enabled = true
[button.map]
click_1 = "play_stop"
HOLD_5S = "panic"
""")
    config = load_config(path)
    assert (config.display.width, config.display.height) == (480, 800)
    assert config.display.fullscreen is True
    assert config.display.theme == "industrial"         # untouched default
    assert config.paths.projects_dir.as_posix() == \
        "/var/lib/chordranger/projects"
    assert config.midi.out_port == "pisound"
    assert config.midi.prefer == ("pisound", "usb")
    assert config.engine.rt_priority == 55
    assert config.button.map == {"CLICK_1": "play_stop", "HOLD_5S": "panic"}


def test_unknown_keys_are_ignored_so_a_newer_config_still_boots(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[display]\nwidth = 800\nhologram = true\n')
    assert load_config(path).display.width == 800


def test_a_malformed_config_fails_loudly(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[display\nwidth = ")
    with pytest.raises(Exception):
        load_config(path)
