"""RVC (Retrieval-based Voice Conversion) inference engine.

Provides real-time voice conversion using RVC models with:
- Hubert feature extraction
- Multiple F0 extraction methods (harvest, crepe, rmvpe)
- Optional FAISS index lookup for voice retrieval
- Real-time audio chunk processing

Dependencies: torch, transformers, librosa, faiss-cpu, praat-parselmouth, scipy
"""

from __future__ import annotations

import logging
import os
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# HuggingFace 官方域名在此环境不可直连，默认走镜像，避免模型下载时卡死
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")


def _default_device() -> str:
    """返回可用的计算设备：优先 CUDA，否则 CPU。"""
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


def _gram_sample_length(model_sr: int) -> int:
    """Return the number of samples per gram for a given sample rate."""
    if model_sr in (32000,):
        return 3200
    if model_sr in (40000, 48000):
        return 4800
    return 4800


# ---------------------------------------------------------------------------
# F0 extraction backends
# ---------------------------------------------------------------------------

class HarvestF0:
    """Pitch extraction using the Harvest algorithm (WORLD vocoder)."""

    def __init__(self) -> None:
        self._world = None

    def _ensure_world(self):
        if self._world is None:
            try:
                import pyworld
                self._world = pyworld
            except ImportError:
                raise ImportError(
                    "pyworld is required for harvest F0 extraction.\n"
                    "Install it: pip install pyworld"
                )
        return self._world

    def extract(self, audio: np.ndarray, sample_rate: int, filter_radius: int = 3) -> np.ndarray:
        world = self._ensure_world()
        audio_64 = audio.astype(np.float64)
        f0, t = world.harvest(audio_64, sample_rate)
        if filter_radius > 0:
            f0 = self._median_filter(f0, filter_radius)
        return f0.astype(np.float32)

    @staticmethod
    def _median_filter(data: np.ndarray, kernel_size: int) -> np.ndarray:
        if kernel_size <= 1:
            return data
        pad = kernel_size // 2
        padded = np.pad(data, (pad, pad), mode="edge")
        result = np.empty_like(data)
        for i in range(len(data)):
            result[i] = np.median(padded[i : i + kernel_size])
        return result


class CrepeF0:
    """Pitch extraction using the CREPE neural network."""

    def __init__(self) -> None:
        self._crepe = None

    def _ensure_crepe(self):
        if self._crepe is None:
            try:
                import crepe
                self._crepe = crepe
            except ImportError:
                raise ImportError(
                    "crepe is required for crepe F0 extraction.\n"
                    "Install it: pip install crepe"
                )
        return self._crepe

    def extract(self, audio: np.ndarray, sample_rate: int, filter_radius: int = 3) -> np.ndarray:
        crepe = self._ensure_crepe()
        time_, frequency, confidence, activation = crepe.predict(
            audio.astype(np.float32), sample_rate, viterbi=True, center=True
        )
        if filter_radius > 0:
            frequency = self._median_filter(frequency, filter_radius)
        return frequency.astype(np.float32)

    @staticmethod
    def _median_filter(data: np.ndarray, kernel_size: int) -> np.ndarray:
        if kernel_size <= 1:
            return data
        pad = kernel_size // 2
        padded = np.pad(data, (pad, pad), mode="edge")
        result = np.empty_like(data)
        for i in range(len(data)):
            result[i] = np.median(padded[i : i + kernel_size])
        return result


class RMVPF0:
    """Pitch extraction using RMVPE (Robust Model for Vocal Pitch Estimation).

    Requires the rmvpe model weights file. The ``model_path`` should point to
    a ``rmvpe.pt`` file.  If *None* is passed, the engine will attempt to
    download the default weights via ``huggingface_hub``.
    """

    def __init__(self, model_path: str | None = None) -> None:
        self._model = None
        self._model_path = model_path

    def _ensure_model(self, device: str = "cpu"):
        if self._model is not None:
            return self._model

        try:
            from rmvpe import RMVPE as _RMVPE
        except ImportError:
            raise ImportError(
                "rmvpe is required for rmvpe F0 extraction.\n"
                "Install it: pip install rmvpe"
            )

        model_path = self._model_path
        if model_path is None:
            try:
                from huggingface_hub import hf_hub_download
                model_path = hf_hub_download(
                    repo_id="lj1995/VoiceConversionWebUI",
                    filename="rmvpe.pt",
                )
            except Exception:
                raise FileNotFoundError(
                    "Cannot locate rmvpe.pt weights. "
                    "Please provide model_path or install huggingface_hub."
                )

        self._model = _RMVPE(model_path, is_half=False, device=device)
        return self._model

    def extract(self, audio: np.ndarray, sample_rate: int, device: str = "cpu") -> np.ndarray:
        import torch
        model = self._ensure_model(device)
        audio_tensor = torch.from_numpy(audio).float().unsqueeze(0)
        if device != "cpu":
            audio_tensor = audio_tensor.to(device)
        with torch.no_grad():
            f0 = model(audio_tensor, sample_rate)
        if isinstance(f0, torch.Tensor):
            f0 = f0.cpu().numpy()
        return f0.squeeze().astype(np.float32)


# ---------------------------------------------------------------------------
# Hubert feature extractor
# ---------------------------------------------------------------------------

class HubertFeatureExtractor:
    """Extract semantic features from audio using a Hubert model."""

    def __init__(self, model_path: str | None = None, device: str = "cpu", is_half: bool = False):
        self.model_path = model_path
        self.device = device
        self.is_half = is_half
        self._model = None
        self._feat_extractor = None

    def load(self) -> None:
        if self._model is not None:
            return

        from transformers import HubertModel, Wav2Vec2FeatureExtractor

        model_path = self.model_path
        if model_path is None or not Path(model_path).exists():
            model_path = "facebook/hubert-base-ls960"

        logger.info("Loading Hubert model from %s", model_path)
        self._feat_extractor = Wav2Vec2FeatureExtractor.from_pretrained(model_path)
        self._model = HubertModel.from_pretrained(model_path).to(self.device)
        self._model.eval()
        if self.is_half:
            self._model.half()
        logger.info("Hubert model loaded successfully")

    def extract(
        self,
        audio: np.ndarray,
        sample_rate: int,
        index: object | None = None,
        index_rate: float = 0.0,
    ) -> np.ndarray:
        import torch

        if self._model is None:
            self.load()

        # Resample to 16kHz if needed
        if sample_rate != 16000:
            import librosa
            audio_16k = librosa.resample(audio, orig_sr=sample_rate, target_sr=16000)
        else:
            audio_16k = audio.copy()

        # Normalize
        max_val = np.abs(audio_16k).max()
        if max_val > 1.0:
            audio_16k = audio_16k / max_val

        # Extract features
        inputs = self._feat_extractor(
            audio_16k,
            sampling_rate=16000,
            return_tensors="pt",
            padding=True,
        )
        input_values = inputs.input_values.to(self.device)
        if self.is_half:
            input_values = input_values.half()

        with torch.no_grad():
            outputs = self._model(input_values, output_hidden_states=True)
            feats = outputs.hidden_states[-1]

        # (1, T, D) -> (D, T)
        feats = feats.squeeze(0).transpose(0, 1).float().cpu().numpy()

        # Optional index retrieval
        if index is not None and index_rate > 0:
            try:
                import faiss
                npy_feats = feats.T.astype(np.float32)  # (T, D)
                score, ix = index.search(npy_feats, k=8)
                weight = np.square(1 / score)
                npy_feats = np.sum(index.reconstruct(ix.flatten()).reshape(npy_feats.shape[0], 8, -1) * weight.reshape(-1, 8, 1), axis=1)
                npy_feats = npy_feats.T  # (D, T)
                feats = feats * (1 - index_rate) + npy_feats * index_rate
            except Exception as e:
                logger.warning("Index retrieval failed: %s", e)

        return feats


# ---------------------------------------------------------------------------
# RVC voice conversion model
# ---------------------------------------------------------------------------

class RVCModel:
    """Thin wrapper around an RVC SynthesizerTrn model."""

    def __init__(
        self,
        net: torch.nn.Module,
        device: str = "cpu",
        is_half: bool = False,
        sample_rate: int = 40000,
    ):
        self.net = net
        self.device = device
        self.is_half = is_half
        self.sample_rate = sample_rate

    @classmethod
    def load_from_file(
        cls,
        model_path: str,
        device: str = "cpu",
        is_half: bool = False,
    ) -> "RVCModel":
        """Load an RVC ``.pth`` model file."""
        import torch

        logger.info("Loading RVC model from %s", model_path)
        state = torch.load(model_path, map_location="cpu", weights_only=False)

        # Determine sample rate (RVC v2 配置里 config[17] 是采样率，state["sr"] 形如 "48k")
        config = state.get("config", None)
        sample_rate = 40000
        if config and len(config) > 17 and isinstance(config[17], int):
            sample_rate = config[17]
        else:
            sr_sym = state.get("sr")
            if isinstance(sr_sym, str):
                try:
                    sample_rate = int(sr_sym.strip().rstrip("kK")) * 1000
                except ValueError:
                    sample_rate = 40000
            elif isinstance(sr_sym, int):
                sample_rate = sr_sym
            else:
                sample_rate = int(state.get("sample_rate", 40000))

        # Try to import the SynthesizerTrn architecture
        net = _try_import_synthesizer(config, sample_rate, is_half)
        if net is None:
            raise RuntimeError(
                "Cannot import SynthesizerTrn architecture. "
                "Please ensure the RVC model architecture is available. "
                "You can place an SynthesizerTrn.py in app/services/ or "
                "install an RVC package that provides it."
            )

        # Load weights
        model_state = state.get("weight", state)
        # Remove 'enc.' prefix if present (some RVC saves prefix it)
        cleaned = {}
        for k, v in model_state.items():
            cleaned[k.replace("enc.", "", 1) if k.startswith("enc.") else k] = v
        net.load_state_dict(cleaned, strict=False)
        net.eval().to(device)

        if is_half:
            net.half()

        logger.info("RVC model loaded (sr=%d, device=%s, half=%s)", sample_rate, device, is_half)
        return cls(net=net, device=device, is_half=is_half, sample_rate=sample_rate)

    def convert(
        self,
        feats: np.ndarray,
        pitch: np.ndarray | None,
        pitchf: np.ndarray | None,
        pitch_shift: int = 0,
        return_length2: int | None = None,
    ) -> np.ndarray:
        """Run voice conversion on extracted features.

        Parameters
        ----------
        feats : np.ndarray
            Hubert features (D, T).
        pitch : np.ndarray or None
            Pitch bin indices (1, 1, T).
        pitchf : np.ndarray or None
            Continuous pitch in Hz (1, 1, T).
        pitch_shift : int
            Pitch shift in semitones.

        Returns
        -------
        np.ndarray
            Converted audio waveform (1, T_out).
        """
        import torch

        with torch.inference_mode():
            t = feats.shape[1]
            p_len = torch.LongTensor([t]).to(self.device)

            # Shift pitch
            if pitch is not None and pitchf is not None:
                if pitch_shift != 0:
                    pitch = pitch.copy()
                    pitchf = pitchf.copy()
                    pitch += pitch_shift
                    pitchf *= 2 ** (pitch_shift / 12)

                pitch = torch.LongTensor(pitch).to(self.device)       # (1, 1, T)
                pitchf = torch.FloatTensor(pitchf).squeeze(1).to(self.device)  # (1, T)
            else:
                pitch = None
                pitchf = None

            feats_t = torch.FloatTensor(feats).unsqueeze(0).transpose(1, 2).to(self.device)
            if self.is_half:
                feats_t = feats_t.half()
                if pitchf is not None:
                    pitchf = pitchf.half()

            sid = torch.LongTensor([0]).to(self.device)
            pitch2 = pitch.squeeze(1) if pitch is not None else None
            output = self.net.infer(feats_t, p_len, pitch2, pitchf, sid)
            audio = output[0][0, 0].cpu().float().numpy()
            return audio


def _try_import_synthesizer(config, sample_rate, is_half):
    """Attempt to import SynthesizerTrn from various sources."""
    def _cfg(idx: int, default):
        if isinstance(config, list) and len(config) > idx:
            return config[idx]
        return default

    # Try 1: local file in the same directory
    try:
        from app.services.synthesizer_trn import SynthesizerTrn
        net = SynthesizerTrn(
            spec_channels=_cfg(0, 1025),
            segment_size=_cfg(1, 32),
            inter_channels=_cfg(2, 192),
            hidden_channels=_cfg(3, 192),
            filter_channels=_cfg(4, 768),
            n_heads=_cfg(5, 2),
            n_layers=_cfg(6, 6),
            kernel_size=_cfg(7, 3),
            p_dropout=_cfg(8, 0),
            resblock=_cfg(9, "1"),
            resblock_kernel_sizes=_cfg(10, [3, 7, 11]),
            resblock_dilation_sizes=_cfg(11, [[1, 3, 5]]),
            upsample_rates=_cfg(12, [10, 10, 2, 2]),
            upsample_initial_channel=_cfg(13, 512),
            upsample_kernel_sizes=_cfg(14, [16, 16, 4, 4]),
            spk_embed_dim=_cfg(15, 109),
            gin_channels=_cfg(16, 256),
            sr=sample_rate,
            is_half=is_half,
        )
        return net
    except Exception:
        pass

    # Try 2: synthesizer_trn.py in cwd or parent dirs
    try:
        import importlib.util
        for search_dir in [Path.cwd(), Path.cwd().parent, Path(__file__).parent]:
            candidate = search_dir / "SynthesizerTrn.py"
            if candidate.exists():
                spec = importlib.util.spec_from_file_location("synthesizer_trn", str(candidate))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                net = mod.SynthesizerTrn(
                    spec_channels=_cfg(0, 1025),
                    segment_size=_cfg(1, 32),
                    inter_channels=_cfg(2, 192),
                    hidden_channels=_cfg(3, 192),
                    filter_channels=_cfg(4, 768),
                    n_heads=_cfg(5, 2),
                    n_layers=_cfg(6, 6),
                    kernel_size=_cfg(7, 3),
                    p_dropout=_cfg(8, 0),
                    resblock=_cfg(9, "1"),
                    resblock_kernel_sizes=_cfg(10, [3, 7, 11]),
                    resblock_dilation_sizes=_cfg(11, [[1, 3, 5]]),
                    upsample_rates=_cfg(12, [10, 10, 2, 2]),
                    upsample_initial_channel=_cfg(13, 512),
                    upsample_kernel_sizes=_cfg(14, [16, 16, 4, 4]),
                    spk_embed_dim=_cfg(15, 109),
                    gin_channels=_cfg(16, 256),
                    sr=sample_rate,
                    is_half=is_half,
                )
                return net
    except Exception:
        pass

    return None


# ---------------------------------------------------------------------------
# High-level conversion helpers
# ---------------------------------------------------------------------------

def load_audio(path: str, sr: int = 16000) -> tuple[np.ndarray, int]:
    """Load audio file and return (waveform, sample_rate)."""
    import librosa
    audio, orig_sr = librosa.load(path, sr=sr, mono=True)
    return audio, sr


def change_speed(audio: np.ndarray, speed: float) -> np.ndarray:
    """Resample audio to change playback speed."""
    import librosa
    return librosa.resample(audio, orig_sr=48000, target_sr=int(48000 * speed))


def get_f0(
    audio: np.ndarray,
    sample_rate: int,
    method: str,
    filter_radius: int = 3,
    model_path: str | None = None,
    device: str = "cpu",
) -> np.ndarray:
    """Extract F0 (pitch) from audio.

    Parameters
    ----------
    audio : np.ndarray
        Audio waveform, mono, float32.
    sample_rate : int
        Audio sample rate.
    method : str
        One of: 'harvest', 'crepe', 'rmvpe'.
    filter_radius : int
        Median filter radius for smoothing.
    model_path : str or None
        Path to RMVPE model weights (only used for rmvpe method).
    device : str
        Device for neural network inference.

    Returns
    -------
    np.ndarray
        F0 values in Hz, one per frame.
    """
    try:
        if method == "harvest":
            return HarvestF0().extract(audio, sample_rate, filter_radius)
        elif method == "crepe":
            return CrepeF0().extract(audio, sample_rate, filter_radius)
        elif method == "rmvpe":
            return RMVPF0(model_path).extract(audio, sample_rate, device)
    except Exception:
        # 所选音高提取后端不可用时回退到 harvest（pyworld），保证至少能变声
        pass
    return HarvestF0().extract(audio, sample_rate, filter_radius)


def voice_conversion(
    model: RVCModel,
    audio: np.ndarray,
    sample_rate: int,
    f0_method: str,
    pitch_shift: int = 0,
    index_rate: float = 0.0,
    rms_mix_rate: float = 0.25,
    resample_sr: int = 0,
    filter_radius: int = 3,
    protect_voiceless: bool = True,
    hubert: HubertFeatureExtractor | None = None,
    index: object | None = None,
    f0_model_path: str | None = None,
) -> tuple[np.ndarray, int]:
    """Perform RVC voice conversion on an audio waveform.

    Returns
    -------
    tuple[np.ndarray, int]
        (converted_audio, output_sample_rate)
    """
    if hubert is None:
        hubert = HubertFeatureExtractor(device=model.device, is_half=model.is_half)

    # Extract hubert features
    feats = hubert.extract(audio, sample_rate, index=index, index_rate=index_rate)

    # Extract f0
    f0 = get_f0(audio, sample_rate, f0_method, filter_radius, f0_model_path, model.device)

    # 模型期望的特征帧数（约 100 帧/秒），把特征和 f0 对齐到这个长度
    t = feats.shape[1]
    p_len = max(int(round(audio.shape[0] / model.sample_rate * 100)), t)
    if t != p_len:
        x_old = np.linspace(0.0, 1.0, t)
        x_new = np.linspace(0.0, 1.0, p_len)
        feats = np.stack(
            [np.interp(x_new, x_old, feats[c]) for c in range(feats.shape[0])],
            axis=0,
        ).astype(np.float32)
    f0 = _align_f0_to_feats(f0, p_len)

    # Build pitch tensors：先按半音移调 f0(Hz)，再重新分箱（RVC 官方做法）
    f0_shifted = f0.copy()
    if pitch_shift != 0:
        voiced = f0_shifted > 0
        f0_shifted[voiced] = f0_shifted[voiced] * (2.0 ** (pitch_shift / 12.0))
    pitch = np.zeros_like(f0_shifted, dtype=np.int64)
    voiced = f0_shifted > 0
    pitch[voiced] = _hz_to_bin(f0_shifted[voiced], model.sample_rate)
    pitch = pitch.reshape(1, -1)
    f0_tensor = f0_shifted.reshape(1, -1).astype(np.float32)

    # Voice conversion
    audio_out = model.convert(
        feats, pitch, f0_tensor, pitch_shift=0, return_length2=len(audio)
    )

    # RMS matching
    if rms_mix_rate < 1.0:
        rms_audio = np.sqrt(np.mean(audio ** 2))
        rms_out = np.sqrt(np.mean(audio_out ** 2))
        if rms_out > 1e-6:
            audio_out = audio_out * (rms_audio / rms_out) * (1 - rms_mix_rate) + audio_out * rms_mix_rate

    # Resample
    out_sr = model.sample_rate
    if resample_sr > 0 and resample_sr != model.sample_rate:
        import librosa
        audio_out = librosa.resample(audio_out, orig_sr=model.sample_rate, target_sr=resample_sr)
        out_sr = resample_sr

    # 保证输出长度和输入一致（模型自然输出长度可能与块长略有偏差，重采样对齐）
    if len(audio_out) != len(audio):
        from scipy.signal import resample as _sig_resample
        audio_out = _sig_resample(audio_out.astype(np.float64), len(audio)).astype(np.float32)

    return audio_out, out_sr


def _align_f0_to_feats(f0: np.ndarray, n_feats: int) -> np.ndarray:
    """Resample f0 array to match the number of feature frames."""
    if len(f0) == 0:
        return np.zeros(n_feats, dtype=np.float32)
    if len(f0) == n_feats:
        return f0
    indices = np.linspace(0, len(f0) - 1, n_feats)
    return np.interp(indices, np.arange(len(f0)), f0).astype(np.float32)


def _hz_to_bin(hz: np.ndarray, sample_rate: int, n_bins: int = 256) -> np.ndarray:
    """Convert Hz to RVC pitch bin index.

    RVC 使用梅尔刻度分箱（见官方 f0_to_coarse），不是简单的对数分箱；
    用错映射会让模型收到完全错误的音高条件，导致吐字不清、音色糊。
    """
    f_min = 50.0
    f_max = 1100.0
    f_mel_min = 1127.0 * np.log(1.0 + f_min / 700.0)
    f_mel_max = 1127.0 * np.log(1.0 + f_max / 700.0)
    hz = np.clip(hz, f_min, f_max)
    mel = 1127.0 * np.log(1.0 + hz / 700.0)
    mel = (mel - f_mel_min) * (n_bins - 2) / (f_mel_max - f_mel_min) + 1.0
    mel = np.clip(mel, 1, n_bins - 1)
    return np.round(mel).astype(np.int64)


# ---------------------------------------------------------------------------
# Real-time engine (used by the audio callback)
# ---------------------------------------------------------------------------

class RVCEngine:
    """High-level engine that manages RVC model state for real-time conversion.

    Usage::

        engine = RVCEngine()
        engine.load_model("/path/to/model.pth", index_path="/path/to.index")
        # In audio callback:
        output = engine.convert_chunk(input_chunk)
    """

    def __init__(self) -> None:
        self._model: RVCModel | None = None
        self._hubert: HubertFeatureExtractor | None = None
        self._index = None
        self._model_sr: int = 40000
        self._device: str = _default_device()
        self._is_half: bool = (self._device == "cuda")
        self._loaded = False
        self._f0_cache: list[np.ndarray] = []

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def sample_rate(self) -> int:
        return self._model_sr

    def load_model(
        self,
        model_path: str,
        index_path: str | None = None,
        device: str | None = None,
        is_half: bool = False,
    ) -> None:
        """Load an RVC model and optional FAISS index.

        Parameters
        ----------
        model_path : str
            Path to the ``.pth`` RVC model file.
        index_path : str or None
            Optional path to a FAISS ``.index`` file for voice retrieval.
        device : str or None
            'cuda' / 'cuda:0' / 'cpu'. Auto-detected if None.
        is_half : bool
            Whether to use FP16 inference.
        """
        import torch

        if device is None:
            if torch.cuda.is_available():
                device = "cuda:0"  # 明确使用第一个可用 GPU
            else:
                device = "cpu"

        self._device = device
        self._is_half = is_half

        self._model = RVCModel.load_from_file(model_path, device=device, is_half=is_half)
        self._model_sr = self._model.sample_rate

        self._hubert = HubertFeatureExtractor(device=device, is_half=is_half)

        self._index = None
        if index_path and Path(index_path).exists():
            try:
                import faiss
                self._index = faiss.read_index(index_path)
                logger.info("Loaded FAISS index from %s", index_path)
            except ImportError:
                logger.warning("faiss-cpu not installed, skipping index")
            except Exception as e:
                logger.warning("Failed to load index: %s", e)

        self._loaded = True
        logger.info("RVC engine loaded (sr=%d, device=%s)", self._model_sr, device)

    def unload(self) -> None:
        import torch

        self._model = None
        self._hubert = None
        self._index = None
        self._loaded = False
        self._f0_cache.clear()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        logger.info("RVC engine unloaded")

    def convert_chunk(
        self,
        audio: np.ndarray,
        pitch_shift: int = 0,
        f0_method: str = "rmvpe",
        index_rate: float = 0.75,
        rms_mix_rate: float = 0.25,
        resample_sr: int = 0,
        filter_radius: int = 3,
    ) -> np.ndarray:
        """Convert a chunk of audio (float32, mono, at ``self.sample_rate``).

        Returns the converted waveform as a float32 numpy array.
        """
        if not self._loaded or self._model is None:
            return audio

        try:
            audio_out, _ = voice_conversion(
                model=self._model,
                audio=audio,
                sample_rate=self._model_sr,
                f0_method=f0_method,
                pitch_shift=pitch_shift,
                index_rate=index_rate,
                rms_mix_rate=rms_mix_rate,
                resample_sr=resample_sr,
                filter_radius=filter_radius,
                hubert=self._hubert,
                index=self._index,
            )
            return audio_out
        except Exception as e:
            logger.error("RVC conversion failed: %s\n%s", e, traceback.format_exc())
            return audio


# ---------------------------------------------------------------------------
# Convenience function: single-shot file conversion
# ---------------------------------------------------------------------------

def convert_file(
    model_path: str,
    input_path: str,
    output_path: str,
    pitch_shift: int = 0,
    f0_method: str = "rmvpe",
    index_path: str | None = None,
    index_rate: float = 0.75,
    rms_mix_rate: float = 0.25,
    resample_sr: int = 0,
    filter_radius: int = 3,
    device: str | None = None,
    is_half: bool = False,
) -> str:
    """Convert an entire audio file using an RVC model.

    Returns the path to the output file.
    """
    import torch
    import librosa
    import soundfile as sf

    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    engine = RVCEngine()
    engine.load_model(model_path, index_path=index_path, device=device, is_half=is_half)

    audio, sr = librosa.load(input_path, sr=engine.sample_rate, mono=True)
    audio_out = engine.convert_chunk(
        audio,
        pitch_shift=pitch_shift,
        f0_method=f0_method,
        index_rate=index_rate,
        rms_mix_rate=rms_mix_rate,
        resample_sr=resample_sr,
        filter_radius=filter_radius,
    )
    out_sr = resample_sr if resample_sr > 0 else engine.sample_rate
    sf.write(output_path, audio_out, out_sf := out_sr)
    logger.info("Converted %s -> %s (sr=%d)", input_path, output_path, out_sf)
    return output_path
