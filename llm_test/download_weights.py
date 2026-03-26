"""
download_weights.py
Pre-downloads all 15 benchmark model weights to the local cache directory.
Run this script before executing ai_prototype.ipynb so that all model
weights are available offline.

Usage:
    python download_weights.py
"""

from pathlib import Path
import time
import sys

CACHE_DIR = Path(__file__).resolve().parent / "cache" / "huggingface-models"

MODEL_REGISTRY = [
    {"modelId": "Qwen/Qwen2.5-0.5B-Instruct", "category": "Ultra-Light", "params": "0.5B"},
    {"modelId": "LiquidAI/LFM2-350M", "category": "Ultra-Light", "params": "0.35B"},
    {"modelId": "HuggingFaceTB/SmolLM2-135M-Instruct", "category": "Ultra-Light", "params": "0.135B"},
    {"modelId": "Qwen/Qwen3.5-0.8B", "category": "Small", "params": "0.8B"},
    {"modelId": "LiquidAI/LFM2-700M", "category": "Small", "params": "0.7B"},
    {"modelId": "Qwen/Qwen3-0.6B", "category": "Small", "params": "0.6B"},
    {"modelId": "Qwen/Qwen3.5-2B", "category": "Medium", "params": "2B"},
    {"modelId": "TinyLlama/TinyLlama-1.1B-Chat-v1.0", "category": "Medium", "params": "1.1B"},
    {"modelId": "microsoft/phi-2", "category": "Medium", "params": "2.7B"},
    {"modelId": "Qwen/Qwen3.5-4B", "category": "Large", "params": "4B"},
    {"modelId": "microsoft/Phi-3.5-mini-instruct", "category": "Large", "params": "3.8B"},
    {"modelId": "microsoft/Phi-4-mini-instruct", "category": "Large", "params": "3.8B"},
    {"modelId": "Qwen/Qwen3-8B", "category": "Extra-Large", "params": "8.2B"},
    {"modelId": "mistralai/Mistral-7B-Instruct-v0.2", "category": "Extra-Large", "params": "7B"},
    {"modelId": "Qwen/Qwen2.5-7B-Instruct", "category": "Extra-Large", "params": "7.6B"},
]


def sanitizeModelId(modelId):
    return modelId.replace("/", "__").replace(".", "_")


def downloadModel(modelId, modelCacheDir):
    from transformers import AutoTokenizer, AutoModelForCausalLM

    tokenizerStart = time.time()
    AutoTokenizer.from_pretrained(
        modelId,
        cache_dir=str(modelCacheDir),
        trust_remote_code=True,
    )
    tokenizerElapsed = round(time.time() - tokenizerStart, 1)

    modelStart = time.time()
    AutoModelForCausalLM.from_pretrained(
        modelId,
        cache_dir=str(modelCacheDir),
        trust_remote_code=True,
        low_cpu_mem_usage=True,
    )
    modelElapsed = round(time.time() - modelStart, 1)

    return tokenizerElapsed, modelElapsed


def main():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    total = len(MODEL_REGISTRY)
    succeeded = 0
    failed = []

    for idx, entry in enumerate(MODEL_REGISTRY, start=1):
        modelId = entry["modelId"]
        category = entry["category"]
        params = entry["params"]
        slug = sanitizeModelId(modelId)
        modelCacheDir = CACHE_DIR / slug

        header = f"[{idx}/{total}] {modelId} ({params}, {category})"
        print(f"\n{'=' * 80}")
        print(header)
        print(f"{'=' * 80}")
        print(f"Cache path: {modelCacheDir}")

        try:
            tokenizerTime, modelTime = downloadModel(modelId, modelCacheDir)
            totalTime = round(tokenizerTime + modelTime, 1)
            print(f"Tokenizer: {tokenizerTime}s | Model: {modelTime}s | Total: {totalTime}s")
            succeeded += 1
        except Exception as exc:
            print(f"FAILED: {exc}", file=sys.stderr)
            failed.append(modelId)

    print(f"\n{'=' * 80}")
    print(f"Download complete: {succeeded}/{total} succeeded")
    if failed:
        print(f"Failed models: {', '.join(failed)}")
    print(f"Cache directory: {CACHE_DIR}")
    print(f"{'=' * 80}")

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
