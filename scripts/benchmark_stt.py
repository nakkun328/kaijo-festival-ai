"""Compare cached Whisper CPU/GPU latency on a synthetic voice fixture."""
import argparse
import json
import os
import time
from pathlib import Path

from faster_whisper import WhisperModel
from faster_whisper.audio import decode_audio


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tmp' / 'daily-voice-fixture.wav'
SNAPSHOT_ROOT = ROOT / 'data' / 'whisper-models' / 'models--Systran--faster-whisper-small' / 'snapshots'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--device', choices=('cpu', 'cuda'), required=True)
    args = parser.parse_args()
    snapshots = list(SNAPSHOT_ROOT.iterdir()) if SNAPSHOT_ROOT.exists() else []
    if not snapshots or not FIXTURE.is_file():
        raise SystemExit('キャッシュ済みモデルと合成音声が必要です。')
    audio = decode_audio(str(FIXTURE))[:int(16000 * 3.0)]
    compute_type = 'int8' if args.device == 'cpu' else 'float16'
    cuda_dll_handle = None
    if args.device == 'cuda' and os.name == 'nt':
        ollama_cuda = Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs' / 'Ollama' / 'lib' / 'ollama' / 'cuda_v12'
        if ollama_cuda.is_dir():
            os.environ['PATH'] = str(ollama_cuda) + os.pathsep + os.environ.get('PATH', '')
            cuda_dll_handle = os.add_dll_directory(str(ollama_cuda))
    started = time.perf_counter()
    model = WhisperModel(str(snapshots[0]), device=args.device, compute_type=compute_type)
    load_seconds = round(time.perf_counter() - started, 2)
    results = []
    for _ in range(3):
        started = time.perf_counter()
        segments, _ = model.transcribe(audio, language='ja', beam_size=1, vad_filter=True,
                                       condition_on_previous_text=False, without_timestamps=True,
                                       initial_prompt='日常の雑談、相談、アイデアの壁打ち、天気について話す自然な日本語の会話です。',
                                       hotwords='リク アイデア 壁打ち 天気')
        text = ''.join(segment.text for segment in segments).strip()
        results.append({'seconds':round(time.perf_counter() - started, 2), 'text':text})
    print(json.dumps({'device':args.device, 'loadSeconds':load_seconds, 'runs':results}, ensure_ascii=False))
    if cuda_dll_handle:
        cuda_dll_handle.close()


if __name__ == '__main__':
    main()
