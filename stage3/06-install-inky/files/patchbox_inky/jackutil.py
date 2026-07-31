"""JACK graph helpers via jack_lsp / jack_connect / jack_disconnect."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field


def _run(cmd: list[str], timeout: float = 3.0) -> str:
    try:
        return subprocess.check_output(
            cmd, stderr=subprocess.DEVNULL, timeout=timeout, text=True
        ).strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def is_running() -> bool:
    # jack_lsp exits 0 when the server is up (even with zero ports).
    try:
        subprocess.check_call(
            ["jack_lsp"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return bool(_run(["pgrep", "-x", "jackd"]) or _run(["pgrep", "-x", "jackdbus"]))


def sample_rate() -> str:
    out = _run(["jack_samplerate"])
    return f"{out} Hz" if out.isdigit() else "—"


def buffer_size() -> str:
    out = _run(["jack_bufsize"])
    return f"{out} f" if out.isdigit() else "—"


@dataclass
class JackGraph:
    outputs: list[str] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    connections: list[tuple[str, str]] = field(default_factory=list)
    ports: list[str] = field(default_factory=list)
    error: str | None = None


def _parse_ports_with_props() -> tuple[list[str], list[str], list[str]]:
    """Return (outputs, inputs, all_ports) using `jack_lsp -p`."""
    text = _run(["jack_lsp", "-p"])
    if not text:
        plain = [ln.strip() for ln in _run(["jack_lsp"]).splitlines() if ln.strip()]
        # Heuristic fallback when -p unavailable
        outs = [p for p in plain if any(k in p.lower() for k in ("capture", "out", "playback_out", "send"))]
        ins = [p for p in plain if any(k in p.lower() for k in ("playback", "in", "return", "recv"))]
        # Avoid double-counting "playback" as both — prefer property parse.
        if not outs and not ins:
            outs = plain
            ins = plain
        return outs, ins, plain

    outs: list[str] = []
    ins: list[str] = []
    all_ports: list[str] = []
    current: str | None = None
    props = ""

    def flush() -> None:
        nonlocal current, props
        if not current:
            return
        all_ports.append(current)
        pl = props.lower()
        # Prefer audio ports; still include MIDI so users can see it
        is_out = "output" in pl
        is_in = "input" in pl
        if is_out:
            outs.append(current)
        if is_in:
            ins.append(current)
        current = None
        props = ""

    for raw in text.splitlines():
        if not raw.strip():
            continue
        if raw.startswith("\t") or raw.startswith(" "):
            props += " " + raw.strip()
        else:
            flush()
            current = raw.strip()
            props = ""
    flush()
    return outs, ins, all_ports


def fetch_graph() -> JackGraph:
    if not is_running():
        return JackGraph(error="JACK not running")

    outs, ins, all_ports = _parse_ports_with_props()

    # Prefer audio-only for the patchbay columns when we can tell.
    # jack_lsp -p lines look like: properties: output,physical,terminal,
    # type is sometimes on a separate tool; filter common MIDI client noise lightly.
    def is_probably_midi(p: str) -> bool:
        pl = p.lower()
        return "midi" in pl or pl.endswith(":midi_in") or pl.endswith(":midi_out")

    audio_outs = [p for p in outs if not is_probably_midi(p)] or outs
    audio_ins = [p for p in ins if not is_probably_midi(p)] or ins

    # Connections via jack_lsp -c
    connections: list[tuple[str, str]] = []
    current: str | None = None
    for raw in _run(["jack_lsp", "-c"]).splitlines():
        if not raw.strip():
            continue
        if raw[0] in (" ", "\t"):
            peer = raw.strip()
            if current and peer:
                connections.append((current, peer))
        else:
            current = raw.strip()

    out_set = set(audio_outs)
    directed: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for a, b in connections:
        if a in out_set:
            edge = (a, b)
        elif b in out_set:
            edge = (b, a)
        else:
            # unknown direction — keep as listed once
            edge = (a, b)
        rev = (edge[1], edge[0])
        if edge in seen or rev in seen:
            continue
        seen.add(edge)
        directed.append(edge)

    return JackGraph(
        outputs=sorted(audio_outs),
        inputs=sorted(audio_ins),
        connections=sorted(directed),
        ports=sorted(set(all_ports)),
    )


def connect(src: str, dst: str) -> tuple[bool, str]:
    try:
        subprocess.check_call(
            ["jack_connect", src, dst],
            stderr=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            timeout=3,
        )
        return True, f"Linked {_short(src)} → {_short(dst)}"
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return False, f"Connect failed: {exc}"


def disconnect(src: str, dst: str) -> tuple[bool, str]:
    try:
        subprocess.check_call(
            ["jack_disconnect", src, dst],
            stderr=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            timeout=3,
        )
        return True, f"Unlinked {_short(src)} → {_short(dst)}"
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return False, f"Disconnect failed: {exc}"


def toggle(src: str, dst: str, graph: JackGraph | None = None) -> tuple[bool, str]:
    g = graph or fetch_graph()
    if (src, dst) in g.connections:
        return disconnect(src, dst)
    return connect(src, dst)


def _short(port: str, maxlen: int = 28) -> str:
    if ":" in port:
        client, name = port.split(":", 1)
        client = (
            client.replace("Pure Data", "PD")
            .replace("SuperCollider", "SC")
            .replace("pisound", "pisnd")
        )
        s = f"{client}:{name}"
    else:
        s = port
    return s if len(s) <= maxlen else s[: maxlen - 1] + "…"


def short(port: str, maxlen: int = 28) -> str:
    return _short(port, maxlen)
