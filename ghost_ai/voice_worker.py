"""
Voice-to-text workers for Ghost AI.

MicVoiceWorker  - records the user's microphone, transcribes with faster-whisper.
SysAudioWorker  - records system speaker/meeting audio via Stereo Mix / loopback (Windows),
                  transcribing so Ghost AI can auto-reply or transcribe interview questions.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional, List

import numpy as np
from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy singleton: load faster-whisper tiny model once on first transcription
# ---------------------------------------------------------------------------
_whisper_lock = threading.Lock()
_whisper_model = None


def _get_whisper():
    """Lazily load and cache the faster-whisper tiny model."""
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model
    with _whisper_lock:
        if _whisper_model is not None:
            return _whisper_model
        from faster_whisper import WhisperModel  # type: ignore
        logger.info("Loading faster-whisper tiny model...")
        _whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")
        logger.info("faster-whisper model ready.")
    return _whisper_model


def _resample_audio(audio: np.ndarray, orig_sr: int, target_sr: int = 16_000) -> np.ndarray:
    """Resample float32 mono audio to target_sr (16 kHz for Whisper)."""
    if orig_sr == target_sr or len(audio) == 0:
        return audio.astype(np.float32)
    target_len = int(round(len(audio) * float(target_sr) / orig_sr))
    try:
        from scipy.signal import resample
        return resample(audio, target_len).astype(np.float32)
    except Exception:
        x_orig = np.linspace(0, 1, len(audio), endpoint=False)
        x_target = np.linspace(0, 1, target_len, endpoint=False)
        return np.interp(x_target, x_orig, audio).astype(np.float32)


def _transcribe_audio(audio_np: np.ndarray, sample_rate: int = 16_000) -> str:
    """
    Transcribes audio array directly in memory via faster-whisper.
    Bypasses PyAV file decoding entirely to prevent metadata_errors compatibility issues.
    """
    if audio_np is None or len(audio_np) == 0:
        return ""

    # Ensure mono float32
    if audio_np.ndim > 1:
        audio_np = audio_np.mean(axis=1)
    audio_np = audio_np.flatten().astype(np.float32)

    # Resample to 16 kHz if recorded at a different hardware rate (e.g. 48 kHz Stereo Mix)
    if sample_rate != 16_000:
        audio_np = _resample_audio(audio_np, sample_rate, 16_000)

    model = _get_whisper()
    segments, _ = model.transcribe(audio_np, beam_size=5, language=None, vad_filter=True)
    return " ".join(s.text.strip() for s in segments).strip()


# ---------------------------------------------------------------------------
# MicVoiceWorker
# ---------------------------------------------------------------------------

class MicVoiceWorker(QThread):
    """
    Records the default microphone using non-blocking audio callbacks until stop()
    is called, then transcribes locally via faster-whisper.

    Signals:
        transcribed(str) -- final transcript
        error(str)       -- error message
        status(str)      -- 'recording' | 'transcribing' | 'done'
    """

    transcribed = Signal(str)
    error = Signal(str)
    status = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop_flag = threading.Event()
        self._frames: List[np.ndarray] = []

    def stop(self):
        """Signal recording loop to end and begin transcription."""
        self._stop_flag.set()

    def run(self):
        try:
            import sounddevice as sd  # type: ignore
        except ImportError:
            self.error.emit("sounddevice not installed.\nRun: pip install sounddevice faster-whisper")
            return

        self._stop_flag.clear()
        self._frames = []
        self.status.emit("recording")
        logger.info("MicVoiceWorker: recording started")

        def audio_callback(indata, frames, time_info, status_flags):
            if status_flags:
                logger.warning("Mic status: %s", status_flags)
            self._frames.append(indata.copy())

        # Determine native default input device and its sample rate
        try:
            default_input = sd.default.device[0]
            if default_input is None or default_input < 0:
                dev_info = sd.query_devices(kind="input")
            else:
                dev_info = sd.query_devices(default_input)
            sample_rate = int(dev_info.get("default_samplerate", 16000))
            channels = min(max(1, dev_info.get("max_input_channels", 1)), 2)
        except Exception:
            sample_rate = 16000
            channels = 1

        try:
            with sd.InputStream(
                samplerate=sample_rate,
                channels=channels,
                dtype="float32",
                callback=audio_callback,
            ):
                while not self._stop_flag.is_set():
                    self.msleep(50)
        except Exception as exc:
            logger.error("MicVoiceWorker recording error: %s", exc)
            self.error.emit(f"Microphone recording failed: {exc}")
            return

        if not self._frames:
            self.status.emit("done")
            return

        self.status.emit("transcribing")
        logger.info("MicVoiceWorker: transcribing recorded frames...")
        try:
            audio = np.concatenate(self._frames, axis=0)
            if audio.ndim > 1 and audio.shape[1] > 1:
                audio = audio.mean(axis=1)
            audio = audio.flatten()
            text = _transcribe_audio(audio, sample_rate)
            logger.info("MicVoiceWorker transcript: %r", text)
            if text:
                self.transcribed.emit(text)
        except Exception as exc:
            logger.error("MicVoiceWorker transcription error: %s", exc)
            self.error.emit(f"Transcription error: {exc}")
        finally:
            self.status.emit("done")


# ---------------------------------------------------------------------------
# SysAudioWorker (Stereo Mix / Loopback)
# ---------------------------------------------------------------------------

class SysAudioWorker(QThread):
    """
    Records system speaker output (WASAPI / Stereo Mix / VB-Cable) until stop() is called.
    Captures interviewer voice from Google Meet / Zoom / Microsoft Teams.

    Signals:
        transcribed(str) -- final transcript
        error(str)       -- error message
        status(str)      -- 'recording' | 'transcribing' | 'done'
    """

    transcribed = Signal(str)
    error = Signal(str)
    status = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop_flag = threading.Event()
        self._frames: List[np.ndarray] = []

    def stop(self):
        """Signal system audio recording to stop and begin transcription."""
        self._stop_flag.set()

    @staticmethod
    def find_loopback_device():
        """Find a loopback, Stereo Mix, or virtual audio cable input device."""
        try:
            import sounddevice as sd  # type: ignore
            keywords = ("stereo mix", "loopback", "what u hear", "cable output", "blackhole")
            for i, dev in enumerate(sd.query_devices()):
                if dev.get("max_input_channels", 0) < 1:
                    continue
                name = dev.get("name", "").lower()
                if any(k in name for k in keywords):
                    logger.info("Found loopback/system audio device [%d]: %s", i, dev["name"])
                    return i, dev
        except Exception as exc:
            logger.warning("Audio device query failed: %s", exc)
        return None, None

    def run(self):
        try:
            import sounddevice as sd  # type: ignore
        except ImportError:
            self.error.emit("sounddevice not installed.\nRun: pip install sounddevice faster-whisper")
            return

        self._stop_flag.clear()
        self._frames = []

        dev_idx, dev_info = self.find_loopback_device()
        if dev_idx is None:
            self.error.emit(
                "No system audio loopback device found.\n\n"
                "To capture meeting audio from Google Meet / Zoom:\n"
                "1. Right-click Speaker icon in taskbar -> 'Sound settings'\n"
                "2. Click 'More sound settings' -> 'Recording' tab\n"
                "3. Right-click empty area -> check 'Show Disabled Devices'\n"
                "4. Right-click 'Stereo Mix' -> 'Enable'\n"
                "OR install free VB-Cable (virtual audio cable)."
            )
            return

        sample_rate = int(dev_info.get("default_samplerate", 48000))
        channels = max(1, min(dev_info.get("max_input_channels", 2), 2))

        self.status.emit("recording")
        logger.info("SysAudioWorker: recording device [%d] at %d Hz, %d ch", dev_idx, sample_rate, channels)

        def audio_callback(indata, frames, time_info, status_flags):
            self._frames.append(indata.copy())

        try:
            with sd.InputStream(
                device=dev_idx,
                samplerate=sample_rate,
                channels=channels,
                dtype="float32",
                callback=audio_callback,
            ):
                while not self._stop_flag.is_set():
                    self.msleep(50)
        except Exception as exc:
            logger.error("SysAudioWorker recording error: %s", exc)
            self.error.emit(f"System audio capture failed: {exc}")
            return

        if not self._frames:
            self.status.emit("done")
            return

        self.status.emit("transcribing")
        logger.info("SysAudioWorker: transcribing recorded frames...")
        try:
            audio = np.concatenate(self._frames, axis=0)
            if audio.ndim > 1 and audio.shape[1] > 1:
                audio = audio.mean(axis=1)
            audio = audio.flatten()
            text = _transcribe_audio(audio, sample_rate)
            logger.info("SysAudioWorker transcript: %r", text)
            if text:
                self.transcribed.emit(text)
        except Exception as exc:
            logger.error("SysAudioWorker transcription error: %s", exc)
            self.error.emit(f"Transcription error: {exc}")
        finally:
            self.status.emit("done")
