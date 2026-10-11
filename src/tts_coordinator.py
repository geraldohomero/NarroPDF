"""TTS synthesis, lookahead pre-buffering, and real-time audio-visual clock coordination."""

from __future__ import annotations

import asyncio
import bisect
import json
import logging
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import wave
from dataclasses import dataclass
from typing import Callable, Any

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import GLib

try:
    import edge_tts
except ImportError:
    edge_tts = None

from .tts_segmenter import TtsSegmenter, TtsWord, TtsSentence, TtsParagraph
from .constants import DEFAULT_LANGUAGE, LANGUAGE_TO_VOICES, PIPER_VOICES

log = logging.getLogger(__name__)


@dataclass
class WordBoundaryInfo:
    """Time information for a spoken word."""
    time: float      # Start time in seconds
    duration: float  # Duration in seconds
    text: str
    word_index: int  # Index in sentence.words


def align_word_boundaries(
    words: list[TtsWord], raw_boundaries: list[dict]
) -> list[WordBoundaryInfo]:
    """Align raw TTS WordBoundary chunks with the sentence's TtsWord objects."""
    aligned: list[WordBoundaryInfo] = []
    if not words or not raw_boundaries:
        return aligned

    num_words = len(words)
    for idx, chunk in enumerate(raw_boundaries):
        w_idx = min(idx, num_words - 1)
        offset_sec = chunk.get("offset", 0) / 10_000_000.0
        duration_sec = chunk.get("duration", 0) / 10_000_000.0
        text = chunk.get("text", "")
        aligned.append(
            WordBoundaryInfo(
                time=offset_sec,
                duration=duration_sec,
                text=text,
                word_index=w_idx,
            )
        )
    return aligned


def interpolate_word_boundaries(
    words: list[TtsWord], total_duration: float
) -> list[WordBoundaryInfo]:
    """Calculate interpolated word boundary timings for engines without native timestamps (e.g. Piper)."""
    if not words:
        return []

    total_duration = max(0.2, total_duration)
    weights = [max(1, len(w.text)) for w in words]
    total_weight = sum(weights)

    boundaries: list[WordBoundaryInfo] = []
    current_time = 0.0

    for idx, (w, weight) in enumerate(zip(words, weights)):
        duration = (weight / total_weight) * total_duration
        boundaries.append(
            WordBoundaryInfo(
                time=current_time,
                duration=duration,
                text=w.text,
                word_index=idx,
            )
        )
        current_time += duration

    return boundaries


def find_boundary_index_at_time(
    boundaries: list[WordBoundaryInfo], current_time: float
) -> int:
    """Perform binary search to find the active word boundary index at the current playback time."""
    if not boundaries:
        return 0

    times = [b.time for b in boundaries]
    idx = bisect.bisect_right(times, current_time) - 1
    return max(0, min(idx, len(boundaries) - 1))


@dataclass
class SynthesizedAudioItem:
    """Pre-synthesized sentence audio and associated boundary metadata."""
    audio_path: str
    boundaries: list[WordBoundaryInfo]
    sentence: TtsSentence


class TtsCoordinator:
    """Coordinates reading in sequence, pre-buffering next sentences, and tracking the audio clock."""

    def __init__(self) -> None:
        self.doc: Any | None = None
        self.page_sentences: dict[int, list[TtsSentence]] = {}
        self.page_paragraphs: dict[int, list[TtsParagraph]] = {}

        # Playback configuration
        self.current_page: int = 0
        self.current_sentence_idx: int = 0
        self.voice: str = ""
        self.language: str = DEFAULT_LANGUAGE
        self.speed_factor: float = 1.0
        self.engine: str = "edge"

        # State
        self.is_playing: bool = False
        self.is_paused: bool = False
        self._stop_requested: bool = False
        self._playback_token: int = 0  # Invalidates stale async workers

        # Active item
        self.active_sentence: TtsSentence | None = None
        self.active_word_index: int = 0
        self.active_boundaries: list[WordBoundaryInfo] = []
        self._last_notified_word_idx: int = -1

        # Lookahead pre-buffered item
        self._prebuffered_item: SynthesizedAudioItem | None = None
        self._prebuffer_lock = threading.Lock()

        # mpv process and IPC
        self._audio_process: subprocess.Popen | None = None
        self._temp_audio_files: list[str] = []
        self._mpv_ipc_path: str = os.path.join(
            tempfile.gettempdir(), f"narro_tts_coord_mpv_{os.getpid()}.sock"
        )
        self._clock_timer_id: int | None = None

        # Callbacks
        self.on_highlight_update: Callable[[int, int, int], None] | None = None
        self.on_status_update: Callable[[str], None] | None = None
        self.on_state_changed: Callable[[], None] | None = None
        self.on_page_change_requested: Callable[[int], None] | None = None

    def set_document(self, doc: Any) -> None:
        """Assign document and invalidate segment cache."""
        self.stop()
        self.doc = doc
        self.page_sentences.clear()
        self.page_paragraphs.clear()

    def set_callbacks(
        self,
        on_highlight_update: Callable[[int, int, int], None] | None = None,
        on_status_update: Callable[[str], None] | None = None,
        on_state_changed: Callable[[], None] | None = None,
        on_page_change_requested: Callable[[int], None] | None = None,
    ) -> None:
        self.on_highlight_update = on_highlight_update
        self.on_status_update = on_status_update
        self.on_state_changed = on_state_changed
        self.on_page_change_requested = on_page_change_requested

    # ------------------------------------------------------------------
    # Page Segmentation & Access
    # ------------------------------------------------------------------

    def get_sentences_for_page(self, page_idx: int) -> list[TtsSentence]:
        """Retrieve or compute sentences for a given page index."""
        if page_idx in self.page_sentences:
            return self.page_sentences[page_idx]

        if not self.doc or not (0 <= page_idx < len(self.doc)):
            return []

        page = self.doc.load_page(page_idx)
        paras, sents = TtsSegmenter.segment_page(page, page_idx)
        self.page_paragraphs[page_idx] = paras
        self.page_sentences[page_idx] = sents
        return sents

    def get_paragraphs_for_page(self, page_idx: int) -> list[TtsParagraph]:
        """Retrieve or compute paragraphs for a given page index."""
        if page_idx in self.page_paragraphs:
            return self.page_paragraphs[page_idx]

        self.get_sentences_for_page(page_idx)
        return self.page_paragraphs.get(page_idx, [])

    # ------------------------------------------------------------------
    # Playback Control API
    # ------------------------------------------------------------------

    def start_playback(
        self,
        page_idx: int,
        sentence_idx: int,
        voice: str,
        language: str = DEFAULT_LANGUAGE,
        speed_factor: float = 1.0,
        engine: str = "edge",
    ) -> None:
        """Start reading aloud from the given page and sentence index."""
        self.stop()
        self._stop_requested = False
        self._playback_token += 1

        self.current_page = page_idx
        self.current_sentence_idx = sentence_idx
        self.voice = voice
        self.language = language
        self.speed_factor = speed_factor
        self.engine = engine

        self.is_playing = True
        self.is_paused = False
        self._emit_state_changed()

        self._play_current_sentence(self._playback_token)

    def pause(self) -> None:
        """Pause playback."""
        if not self.is_playing:
            return
        if self._send_mpv_command(["set_property", "pause", True]):
            self.is_paused = True
            self._emit_state_changed()
            self._emit_status("Leitura pausada.")

    def resume(self) -> None:
        """Resume paused playback."""
        if not self.is_playing:
            return
        if self._send_mpv_command(["set_property", "pause", False]):
            self.is_paused = False
            self._emit_state_changed()
            self._emit_status("Leitura retomada.")

    def toggle_pause(self) -> None:
        if self.is_paused:
            self.resume()
        else:
            self.pause()

    def stop(self) -> None:
        """Stop playback and clear highlighting."""
        self._stop_requested = True
        self._playback_token += 1

        self._stop_clock_timer()
        self._terminate_mpv()

        with self._prebuffer_lock:
            self._prebuffered_item = None

        self._cleanup_temp_files()

        self.is_playing = False
        self.is_paused = False
        self.active_sentence = None
        self.active_word_index = 0
        self.active_boundaries = []
        self._last_notified_word_idx = -1

        self._emit_state_changed()
        self._emit_status("Leitura parada.")
        if self.on_highlight_update:
            self.on_highlight_update(self.current_page, -1, -1)

    def update_speed(self, speed_factor: float) -> None:
        """Dynamically update playback speed."""
        self.speed_factor = speed_factor
        self._send_mpv_command(["set_property", "speed", speed_factor])

    def next_sentence(self) -> None:
        """Advance to the next sentence."""
        sentences = self.get_sentences_for_page(self.current_page)
        if self.current_sentence_idx + 1 < len(sentences):
            self.start_playback(
                self.current_page,
                self.current_sentence_idx + 1,
                self.voice,
                self.language,
                self.speed_factor,
                self.engine,
            )
        elif self.doc and self.current_page + 1 < len(self.doc):
            self._advance_to_page(self.current_page + 1, 0)

    def prev_sentence(self) -> None:
        """Go back to the previous sentence."""
        if self.current_sentence_idx > 0:
            self.start_playback(
                self.current_page,
                self.current_sentence_idx - 1,
                self.voice,
                self.language,
                self.speed_factor,
                self.engine,
            )
        elif self.current_page > 0:
            prev_sentences = self.get_sentences_for_page(self.current_page - 1)
            target_idx = max(0, len(prev_sentences) - 1)
            self._advance_to_page(self.current_page - 1, target_idx)

    def next_paragraph(self) -> None:
        """Jump to the start of the next paragraph."""
        sentences = self.get_sentences_for_page(self.current_page)
        if not sentences or self.current_sentence_idx >= len(sentences):
            return

        current_para = sentences[self.current_sentence_idx].paragraph_index
        for idx in range(self.current_sentence_idx + 1, len(sentences)):
            if sentences[idx].paragraph_index > current_para:
                self.start_playback(
                    self.current_page, idx, self.voice, self.language, self.speed_factor, self.engine
                )
                return

        # If not found on current page, go to next page
        if self.doc and self.current_page + 1 < len(self.doc):
            self._advance_to_page(self.current_page + 1, 0)

    def prev_paragraph(self) -> None:
        """Jump to the start of the previous paragraph."""
        sentences = self.get_sentences_for_page(self.current_page)
        if not sentences or self.current_sentence_idx >= len(sentences):
            return

        current_para = sentences[self.current_sentence_idx].paragraph_index
        # If currently past the first sentence of current paragraph, jump to its start
        first_of_current = -1
        for idx, s in enumerate(sentences):
            if s.paragraph_index == current_para:
                first_of_current = idx
                break

        if first_of_current != -1 and self.current_sentence_idx > first_of_current:
            self.start_playback(
                self.current_page, first_of_current, self.voice, self.language, self.speed_factor, self.engine
            )
            return

        # Jump to previous paragraph on this page
        prev_para_start = -1
        for idx in range(self.current_sentence_idx - 1, -1, -1):
            if sentences[idx].paragraph_index < current_para:
                # Find start of that paragraph
                p_idx = sentences[idx].paragraph_index
                for p_start in range(0, idx + 1):
                    if sentences[p_start].paragraph_index == p_idx:
                        prev_para_start = p_start
                        break
                break

        if prev_para_start != -1:
            self.start_playback(
                self.current_page, prev_para_start, self.voice, self.language, self.speed_factor, self.engine
            )
        elif self.current_page > 0:
            prev_sentences = self.get_sentences_for_page(self.current_page - 1)
            target_idx = max(0, len(prev_sentences) - 1)
            self._advance_to_page(self.current_page - 1, target_idx)

    # ------------------------------------------------------------------
    # Internal Synthesis & Playback Loop
    # ------------------------------------------------------------------

    def _play_current_sentence(self, token: int) -> None:
        """Synthesize and play the current sentence, using pre-buffered audio if matching."""
        sentences = self.get_sentences_for_page(self.current_page)
        if not sentences or self.current_sentence_idx >= len(sentences):
            # Check if there is a next page
            if self.doc and self.current_page + 1 < len(self.doc):
                self._advance_to_page(self.current_page + 1, 0)
            else:
                self.stop()
            return

        sentence = sentences[self.current_sentence_idx]
        self.active_sentence = sentence
        self.active_word_index = 0
        self._last_notified_word_idx = -1

        # Check pre-buffered item
        prebuffered = None
        with self._prebuffer_lock:
            if (
                self._prebuffered_item
                and self._prebuffered_item.sentence.page_index == self.current_page
                and self._prebuffered_item.sentence.sentence_index == self.current_sentence_idx
            ):
                prebuffered = self._prebuffered_item
                self._prebuffered_item = None

        if prebuffered:
            self._start_audio_playback(prebuffered, token)
        else:
            self._emit_status(
                f"Sintetizando frase {sentence.sentence_index + 1} de {len(sentences)}..."
            )

            def worker() -> None:
                try:
                    item = self._synthesize_sentence_sync(sentence)
                    if token != self._playback_token or self._stop_requested:
                        return
                    GLib.idle_add(self._start_audio_playback, item, token)
                except Exception as exc:
                    log.error("TTS synthesis error: %s", exc)
                    if token == self._playback_token:
                        GLib.idle_add(self._emit_status, f"Erro na síntese: {exc}")
                        GLib.idle_add(self.stop)

            threading.Thread(target=worker, daemon=True).start()

    def _start_audio_playback(self, item: SynthesizedAudioItem, token: int) -> None:
        if token != self._playback_token or self._stop_requested:
            return

        self.active_boundaries = item.boundaries
        self._last_notified_word_idx = -1

        sentences = self.get_sentences_for_page(self.current_page)
        self._emit_status(
            f"Frase {self.current_sentence_idx + 1} de {len(sentences)} (Pág. {self.current_page + 1})"
        )

        # Notify initial highlight on first word
        if self.on_highlight_update:
            self.on_highlight_update(self.current_page, self.current_sentence_idx, 0)

        # Start mpv process
        self._start_mpv(item.audio_path)
        self._start_clock_timer()

        # Trigger background lookahead pre-buffer of next sentence
        self._trigger_lookahead_prebuffer(token)

    def _trigger_lookahead_prebuffer(self, token: int) -> None:
        """Asynchronously pre-synthesize the sentence after the current one."""
        next_page = self.current_page
        next_sentence_idx = self.current_sentence_idx + 1

        sentences = self.get_sentences_for_page(next_page)
        if next_sentence_idx >= len(sentences):
            if self.doc and next_page + 1 < len(self.doc):
                next_page += 1
                next_sentence_idx = 0
                sentences = self.get_sentences_for_page(next_page)
            else:
                return

        if not sentences or next_sentence_idx >= len(sentences):
            return

        next_sentence = sentences[next_sentence_idx]

        def prebuffer_worker() -> None:
            try:
                item = self._synthesize_sentence_sync(next_sentence)
                if token != self._playback_token or self._stop_requested:
                    return
                with self._prebuffer_lock:
                    self._prebuffered_item = item
            except Exception as exc:
                log.debug("Prebuffer synthesis failed: %s", exc)

        threading.Thread(target=prebuffer_worker, daemon=True).start()

    def _advance_to_page(self, page_idx: int, sentence_idx: int) -> None:
        """Advance reading to another page."""
        self.current_page = page_idx
        self.current_sentence_idx = sentence_idx
        if self.on_page_change_requested:
            self.on_page_change_requested(page_idx)
        self.start_playback(
            page_idx,
            sentence_idx,
            self.voice,
            self.language,
            self.speed_factor,
            self.engine,
        )

    # ------------------------------------------------------------------
    # Synthesis Implementations (Edge TTS / Piper)
    # ------------------------------------------------------------------

    def _synthesize_sentence_sync(self, sentence: TtsSentence) -> SynthesizedAudioItem:
        """Synchronously synthesize a sentence and compute boundaries."""
        if self.engine == "edge":
            return self._synthesize_edge_sync(sentence)
        else:
            return self._synthesize_piper_sync(sentence)

    def _synthesize_edge_sync(self, sentence: TtsSentence) -> SynthesizedAudioItem:
        if not edge_tts:
            raise RuntimeError("edge-tts library not available")

        voice = self.voice
        if not voice:
            voices = LANGUAGE_TO_VOICES.get(self.language, LANGUAGE_TO_VOICES[DEFAULT_LANGUAGE])
            voice = voices[0]

        fd, output_path = tempfile.mkstemp(prefix="narro_edge_", suffix=".mp3")
        os.close(fd)
        self._temp_audio_files.append(output_path)

        raw_boundaries: list[dict] = []
        audio_data = bytearray()

        async def run_comm():
            communicate = edge_tts.Communicate(
                text=sentence.text,
                voice=voice,
                rate="+0%",
                boundary="WordBoundary",
            )
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_data.extend(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    raw_boundaries.append(chunk)

        asyncio.run(run_comm())

        with open(output_path, "wb") as f:
            f.write(audio_data)

        aligned = align_word_boundaries(sentence.words, raw_boundaries)
        if not aligned:
            aligned = interpolate_word_boundaries(sentence.words, 1.5)

        return SynthesizedAudioItem(
            audio_path=output_path,
            boundaries=aligned,
            sentence=sentence,
        )

    def _synthesize_piper_sync(self, sentence: TtsSentence) -> SynthesizedAudioItem:
        piper_path = shutil.which("piper") or os.path.expanduser("~/.local/bin/piper")
        if not shutil.which(piper_path):
            raise RuntimeError("piper command not found")

        voices_dir = os.path.expanduser("~/.local/share/narro-pdf/voices/")
        model_path = os.path.join(voices_dir, f"{self.voice}.onnx")
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model file {model_path} not found")

        fd, output_path = tempfile.mkstemp(prefix="narro_piper_", suffix=".wav")
        os.close(fd)
        self._temp_audio_files.append(output_path)

        cmd = [piper_path, "--model", model_path, "--output_file", output_path]
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        _, stderr = proc.communicate(input=sentence.text)
        if proc.returncode != 0:
            raise RuntimeError(f"Piper error: {stderr}")

        # Extract duration from WAV
        duration = 1.0
        try:
            with wave.open(output_path, "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                if rate > 0:
                    duration = frames / float(rate)
        except Exception:
            pass

        boundaries = interpolate_word_boundaries(sentence.words, duration)
        return SynthesizedAudioItem(
            audio_path=output_path,
            boundaries=boundaries,
            sentence=sentence,
        )

    # ------------------------------------------------------------------
    # mpv Process and Audio Clock Synchronization
    # ------------------------------------------------------------------

    def _start_mpv(self, audio_path: str) -> None:
        self._terminate_mpv()
        self._cleanup_ipc()

        cmd = [
            "mpv",
            "--no-video",
            "--quiet",
            f"--input-ipc-server={self._mpv_ipc_path}",
            f"--speed={self.speed_factor}",
            audio_path,
        ]

        self._audio_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        token = self._playback_token

        def monitor() -> None:
            proc = self._audio_process
            if proc:
                proc.wait()
                GLib.idle_add(self._on_mpv_finished, token)

        threading.Thread(target=monitor, daemon=True).start()

    def _start_clock_timer(self) -> None:
        self._stop_clock_timer()
        # ~40 FPS timer
        self._clock_timer_id = GLib.timeout_add(25, self._on_clock_tick)

    def _stop_clock_timer(self) -> None:
        if self._clock_timer_id is not None:
            GLib.source_remove(self._clock_timer_id)
            self._clock_timer_id = None

    def _on_clock_tick(self) -> bool:
        if not self.is_playing or self.is_paused or self._stop_requested:
            return True

        current_time = self._query_mpv_time_pos()
        if current_time is None:
            return True

        if not self.active_boundaries:
            return True

        idx = find_boundary_index_at_time(self.active_boundaries, current_time)
        word_info = self.active_boundaries[idx]
        actual_word_idx = word_info.word_index

        if actual_word_idx != self._last_notified_word_idx:
            self._last_notified_word_idx = actual_word_idx
            self.active_word_index = actual_word_idx
            if self.on_highlight_update:
                self.on_highlight_update(
                    self.current_page, self.current_sentence_idx, actual_word_idx
                )

        return True

    def _query_mpv_time_pos(self) -> float | None:
        if not os.path.exists(self._mpv_ipc_path):
            return None
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(0.02)
            sock.connect(self._mpv_ipc_path)
            cmd = {"command": ["get_property", "time-pos"]}
            sock.sendall((json.dumps(cmd) + "\n").encode())
            data = sock.recv(1024).decode()
            sock.close()
            res = json.loads(data.strip().split("\n")[0])
            val = res.get("data")
            return float(val) if val is not None else None
        except Exception:
            return None

    def _send_mpv_command(self, cmd_args: list) -> bool:
        if not os.path.exists(self._mpv_ipc_path):
            return False
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(0.05)
            sock.connect(self._mpv_ipc_path)
            cmd = {"command": cmd_args}
            sock.sendall((json.dumps(cmd) + "\n").encode())
            sock.close()
            return True
        except Exception:
            return False

    def _on_mpv_finished(self, token: int) -> None:
        if token != self._playback_token or self._stop_requested:
            return

        self._stop_clock_timer()
        # Automatically advance to next sentence!
        self.next_sentence()

    def _terminate_mpv(self) -> None:
        if self._audio_process and self._audio_process.poll() is None:
            self._send_mpv_command(["quit"])
            try:
                self._audio_process.terminate()
            except OSError:
                pass
        self._audio_process = None

    def _cleanup_ipc(self) -> None:
        if os.path.exists(self._mpv_ipc_path):
            try:
                os.remove(self._mpv_ipc_path)
            except OSError:
                pass

    def _cleanup_temp_files(self) -> None:
        for path in self._temp_audio_files:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        self._temp_audio_files.clear()

    def cleanup(self) -> None:
        """Full cleanup on window destruction."""
        self.stop()
        self._cleanup_ipc()
        self._cleanup_temp_files()

    def _emit_status(self, message: str) -> None:
        if self.on_status_update:
            self.on_status_update(message)

    def _emit_state_changed(self) -> None:
        if self.on_state_changed:
            self.on_state_changed()
