"""Text-to-Speech engine wrapping Edge-TTS synthesis and mpv playback."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib

try:
    import edge_tts
except ImportError:
    edge_tts = None

from .constants import DEFAULT_LANGUAGE, LANGUAGE_TO_VOICES

log = logging.getLogger(__name__)


class TtsEngine:
    """Manages TTS synthesis via Edge-TTS and audio playback via mpv/ffplay.

    Emits state changes through callbacks so the UI can react without
    tight coupling to internal details.
    """

    def __init__(self) -> None:
        self._audio_process: subprocess.Popen | None = None
        self._temp_audio_path: str | None = None
        self._paused: bool = False
        self._mpv_ipc_path: str = os.path.join(
            tempfile.gettempdir(), f"tts_pdf_mpv_{os.getpid()}.sock"
        )

        # Callbacks the UI can register
        self._on_status: Callable[[str], None] | None = None
        self._on_state_changed: Callable[[], None] | None = None

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def is_available(self) -> bool:
        """Whether the edge-tts library is installed."""
        return edge_tts is not None

    @property
    def is_playing(self) -> bool:
        return (
            self._audio_process is not None
            and self._audio_process.poll() is None
        )

    @property
    def is_paused(self) -> bool:
        return self._paused

    # ------------------------------------------------------------------
    # Callback registration
    # ------------------------------------------------------------------

    def set_status_callback(self, callback: Callable[[str], None]) -> None:
        self._on_status = callback

    def set_state_changed_callback(self, callback: Callable[[], None]) -> None:
        self._on_state_changed = callback

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def read_aloud(
        self,
        text: str,
        voice: str,
        language: str = DEFAULT_LANGUAGE,
        speed_factor: float = 1.0,
    ) -> None:
        """Synthesize *text* and begin playback asynchronously."""
        if not self.is_available:
            self._emit_status("edge-tts não encontrado. Instale: pip install edge-tts")
            return

        self.stop()
        self._paused = False
        self._emit_state_changed()
        self._emit_status("Gerando áudio com Edge TTS...")

        if not voice:
            voices = LANGUAGE_TO_VOICES.get(language, LANGUAGE_TO_VOICES[DEFAULT_LANGUAGE])
            voice = voices[0]

        def worker() -> None:
            try:
                fd, output_path = tempfile.mkstemp(prefix="edge_tts_", suffix=".mp3")
                os.close(fd)
                asyncio.run(self._synthesize(text, voice, output_path))
                GLib.idle_add(self._start_playback, output_path, speed_factor)
            except Exception as exc:
                GLib.idle_add(self._emit_status, f"Erro no TTS: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def _send_mpv_command(self, cmd_args: list) -> bool:
        if not os.path.exists(self._mpv_ipc_path):
            return False
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(self._mpv_ipc_path)
            cmd = {"command": cmd_args}
            sock.sendall((json.dumps(cmd) + "\n").encode())
            sock.close()
            return True
        except Exception as exc:
            log.warning("Error sending mpv command %s: %s", cmd_args, exc)
            return False

    def pause(self) -> None:
        """Pause current playback."""
        if not self.is_playing:
            return
        if self._send_mpv_command(["set_property", "pause", True]):
            self._paused = True
            self._emit_state_changed()
            self._emit_status("Áudio pausado.")
        else:
            try:
                os.kill(self._audio_process.pid, signal.SIGSTOP)
                self._paused = True
                self._emit_state_changed()
                self._emit_status("Áudio pausado.")
            except OSError as exc:
                self._emit_status(f"Erro ao pausar áudio: {exc}")

    def resume(self) -> None:
        """Resume paused playback."""
        if not self.is_playing:
            return
        if self._send_mpv_command(["set_property", "pause", False]):
            self._paused = False
            self._emit_state_changed()
            self._emit_status("Áudio retomado.")
        else:
            try:
                os.kill(self._audio_process.pid, signal.SIGCONT)
                self._paused = False
                self._emit_state_changed()
                self._emit_status("Áudio retomado.")
            except OSError as exc:
                self._emit_status(f"Erro ao retomar áudio: {exc}")

    def toggle_pause(self) -> None:
        """Toggle between paused and playing state."""
        if self._paused:
            self.resume()
        else:
            self.pause()

    def stop(self) -> None:
        """Stop playback and clean up."""
        if self._audio_process and self._audio_process.poll() is None:
            if not self._send_mpv_command(["quit"]):
                self._audio_process.terminate()
        self._audio_process = None
        self._paused = False
        self._emit_state_changed()
        self._cleanup_ipc()

    def update_speed(self, speed_factor: float) -> None:
        """Dynamically update playback speed via mpv IPC socket."""
        if not self.is_playing:
            return
        if not os.path.exists(self._mpv_ipc_path):
            return
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(self._mpv_ipc_path)
            cmd = {"command": ["set_property", "speed", speed_factor]}
            sock.sendall((json.dumps(cmd) + "\n").encode())
            sock.close()
        except Exception as exc:
            log.warning("Error updating mpv speed: %s", exc)

    def cleanup(self) -> None:
        """Full cleanup for application shutdown."""
        self.stop()
        if self._temp_audio_path and os.path.exists(self._temp_audio_path):
            try:
                os.remove(self._temp_audio_path)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Private methods
    # ------------------------------------------------------------------

    async def _synthesize(self, text: str, voice: str, output_path: str) -> None:
        """Run edge-tts synthesis at normal speed (mpv handles speed)."""
        communicate = edge_tts.Communicate(text=text, voice=voice, rate="+0%")
        await communicate.save(output_path)

    def _start_playback(self, audio_path: str, speed_factor: float) -> None:
        """Start mpv or ffplay to play the synthesized audio."""
        # Clean up previous temp file
        if self._temp_audio_path and os.path.exists(self._temp_audio_path):
            try:
                os.remove(self._temp_audio_path)
            except OSError:
                pass

        self._temp_audio_path = audio_path
        self._cleanup_ipc()

        candidates = [
            [
                "mpv", "--no-video", "--quiet",
                f"--input-ipc-server={self._mpv_ipc_path}",
                f"--speed={speed_factor}",
                audio_path,
            ],
            [
                "ffplay", "-nodisp", "-autoexit",
                "-loglevel", "quiet",
                audio_path,
            ],
        ]

        cmd = None
        for candidate in candidates:
            if shutil.which(candidate[0]):
                cmd = candidate
                break

        if not cmd:
            self._emit_status("Instale mpv ou ffplay para reproduzir áudio.")
            return

        self._audio_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._paused = False
        self._emit_state_changed()

        # Start process monitor thread
        def monitor_process(process: subprocess.Popen) -> None:
            process.wait()
            GLib.idle_add(self._on_process_exited, process)

        threading.Thread(target=monitor_process, args=(self._audio_process,), daemon=True).start()

    def _on_process_exited(self, process: subprocess.Popen) -> None:
        if self._audio_process == process:
            self.stop()

    def _cleanup_ipc(self) -> None:
        if os.path.exists(self._mpv_ipc_path):
            try:
                os.remove(self._mpv_ipc_path)
            except OSError:
                pass

    def _emit_status(self, message: str) -> None:
        if self._on_status:
            self._on_status(message)

    def _emit_state_changed(self) -> None:
        if self._on_state_changed:
            self._on_state_changed()
