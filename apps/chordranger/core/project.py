"""The project file — everything musical, in one versioned JSON document.

The split with ``core.config`` is strict and worth restating: config is
*deployment* (which panel, which paths, which MIDI backend), project is
*music* (chords, style, song, tempo). Move a project to another unit and it
plays the same; move a config and it does not follow the music at all.

Styles are stored by name when they are factory content and in full when they
have been edited, so a project referencing HOUSE stays a few kilobytes and
still survives a firmware update that improves HOUSE — while a project whose
author rewrote the bassline keeps their version regardless.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path

from core.bass import BassSpec
from core.chords import VoicingSpec
from core.chordset import Chordset, diatonic
from core.song import Song
from core.style import (Part, Phrase, PhraseNote, Section, Style,
                        SECTION_ORDER)
from core.theory import DEFAULT_SCALE

SCHEMA_VERSION = 1
EXTENSION = ".crproj"


@dataclass(frozen=True, slots=True)
class Project:
    """One song's worth of state."""

    name: str = "INIT"
    bpm: float = 110.0
    key_root: int = 0
    scale: str = DEFAULT_SCALE
    chordset: Chordset = field(default_factory=lambda: diatonic(0, "major"))
    style: Style = field(default_factory=Style)
    song: Song = field(default_factory=Song)
    voicing: VoicingSpec = field(default_factory=VoicingSpec)
    bass: BassSpec = field(default_factory=BassSpec)
    strum: int = 0
    latch: bool = True
    song_mode: bool = False
    metronome: bool = False
    clock_out: bool = False
    section_quantize: str = "bar"

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "name": self.name, "bpm": self.bpm, "key_root": self.key_root,
            "scale": self.scale,
            "chordset": self.chordset.to_dict(),
            "style": style_to_dict(self.style),
            "song": self.song.to_dict(),
            "voicing": _spec_to_dict(self.voicing),
            "bass": _spec_to_dict(self.bass),
            "strum": self.strum, "latch": self.latch,
            "song_mode": self.song_mode, "metronome": self.metronome,
            "clock_out": self.clock_out,
            "section_quantize": self.section_quantize,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Project":
        version = int(data.get("schema_version", SCHEMA_VERSION))
        if version > SCHEMA_VERSION:
            # Load it anyway: a project from a newer firmware usually differs
            # by fields this build ignores, and refusing to open a file on a
            # stage is worse than opening it with a warning in the log.
            import logging
            logging.getLogger("chordranger.project").warning(
                "project schema v%d is newer than v%d — unknown fields "
                "ignored", version, SCHEMA_VERSION)
        return cls(
            name=str(data.get("name", "INIT")),
            bpm=float(data.get("bpm", 110.0)),
            key_root=int(data.get("key_root", 0)),
            scale=str(data.get("scale", DEFAULT_SCALE)),
            chordset=(Chordset.from_dict(data["chordset"])
                      if "chordset" in data else diatonic(0, "major")),
            style=style_from_dict(data.get("style")),
            song=(Song.from_dict(data["song"]) if "song" in data else Song()),
            voicing=_spec_from_dict(VoicingSpec, data.get("voicing")),
            bass=_spec_from_dict(BassSpec, data.get("bass")),
            strum=int(data.get("strum", 0)),
            latch=bool(data.get("latch", True)),
            song_mode=bool(data.get("song_mode", False)),
            metronome=bool(data.get("metronome", False)),
            clock_out=bool(data.get("clock_out", False)),
            section_quantize=str(data.get("section_quantize", "bar")))

    def save(self, path: Path) -> None:
        """Atomic: write a sibling temp file, then rename. A project saved as
        the power goes is either the old one or the new one, never half."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=1), encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> "Project":
        return cls.from_dict(json.loads(Path(path).read_text(
            encoding="utf-8")))

    def renamed(self, name: str) -> "Project":
        return replace(self, name=name)


def default_project() -> Project:
    """What ``main.py`` boots with when nothing was asked for: the first
    factory style, a C major chordset, no song."""
    from data.styles import factory_styles
    style = factory_styles()[0]
    return Project(name="INIT", bpm=style.bpm, style=style,
                   chordset=diatonic(0, "major"))


# --- spec (de)serialisation ---------------------------------------------------

def _spec_to_dict(spec) -> dict:
    return {f: getattr(spec, f) for f in spec.__dataclass_fields__}


def _spec_from_dict(cls, data: dict | None):
    if not data:
        return cls()
    fields = cls.__dataclass_fields__
    return cls(**{k: v for k, v in data.items() if k in fields})


# --- style (de)serialisation --------------------------------------------------
# A style round-trips in full. The factory-name shortcut lives in
# ``style_from_dict``: a document that says only {"name": "HOUSE"} gets the
# shipped style, which is how an unedited project stays small.

def style_to_dict(style: Style) -> dict:
    return {
        "name": style.name, "bpm": style.bpm, "genre": style.genre,
        "swing": style.swing,
        "parts": [_part_to_dict(p) for p in style.parts],
        "sections": {name: _section_to_dict(section)
                     for name, section in style.sections.items()},
    }


def _part_to_dict(part: Part) -> dict:
    return {f: getattr(part, f) for f in part.__dataclass_fields__}


def _section_to_dict(section: Section) -> dict:
    return {"bars": section.bars,
            "phrases": {pid: _phrase_to_dict(p)
                        for pid, p in section.phrases.items()}}


def _phrase_to_dict(phrase: Phrase) -> dict:
    return {"bars": phrase.bars, "conversion": phrase.conversion,
            "source_root": phrase.source_root,
            "source_quality": phrase.source_quality,
            # Notes as flat quads: a phrase is the bulkiest thing in the file
            # and named keys would triple it for no gain a human reader gets.
            "notes": [[n.tick, n.note, n.velocity, n.length]
                      for n in phrase.notes]}


def style_from_dict(data: dict | None) -> Style:
    if not data:
        from data.styles import factory_styles
        return factory_styles()[0]
    if "sections" not in data:
        from data.styles import style_named
        return style_named(str(data.get("name", "")))
    parts = tuple(Part(**{k: v for k, v in raw.items()
                          if k in Part.__dataclass_fields__})
                  for raw in data.get("parts", ()))
    sections = {}
    for name, raw in (data.get("sections") or {}).items():
        if name not in SECTION_ORDER:
            continue
        phrases = {pid: _phrase_from_dict(p)
                   for pid, p in (raw.get("phrases") or {}).items()}
        sections[name] = Section(name=name, bars=int(raw.get("bars", 1)),
                                 phrases=phrases)
    return Style(name=str(data.get("name", "STYLE")),
                 bpm=float(data.get("bpm", 110.0)),
                 genre=str(data.get("genre", "")),
                 swing=int(data.get("swing", 0)),
                 parts=parts, sections=sections)


def _phrase_from_dict(data: dict) -> Phrase:
    notes = tuple(PhraseNote(tick=int(q[0]), note=int(q[1]),
                             velocity=int(q[2]), length=int(q[3]))
                  for q in data.get("notes", ()))
    return Phrase(notes=notes, bars=int(data.get("bars", 1)),
                  conversion=str(data.get("conversion", "")),
                  source_root=int(data.get("source_root", 0)),
                  source_quality=str(data.get("source_quality", "maj")))


# --- browsing -----------------------------------------------------------------

def list_projects(directory: Path) -> tuple[Path, ...]:
    """Projects on the data partition, newest first — the order the browser
    wants, because the file you are looking for is nearly always the last one
    you touched."""
    folder = Path(directory)
    if not folder.is_dir():
        return ()
    files = [p for p in folder.glob(f"*{EXTENSION}") if p.is_file()]
    return tuple(sorted(files, key=lambda p: p.stat().st_mtime, reverse=True))
