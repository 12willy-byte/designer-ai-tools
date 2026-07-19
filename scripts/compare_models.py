"""Multi-model comparison driver for the MVP concept-package pipeline.

For each requested provider, runs the full MVP pipeline in a subprocess with
AI_PROVIDER set (ai_client reads env at runtime, so no pipeline changes are
needed), copies the artifacts to outputs/model-compare/<provider>/, and writes
a summary JSON with per-step success and approximate timings.

Usage:
    python3 scripts/compare_models.py --providers deepseek,openai

API keys are read from the environment only; nothing sensitive is logged.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.ai_client import PROVIDER_PRESETS  # noqa: E402

# Pipeline step -> artifact files used to detect success and approximate timing
STEP_ARTIFACTS = {
    # 设计定位.txt is rewritten by the mood-board step, so only the JSON
    # reliably marks the brief step's completion time.
    "design_brief": ["设计定位.json"],
    "color_palette": ["色彩方案色板.json", "色彩方案.png"],
    "material_board": ["材质方案.json", "材质方案.png"],
    "mood_board": ["风格意向板.png"],
    "layout": ["布局方案.json"],
    "pptx": ["概念方案.pptx"],
}


def _provider_model(provider, model=None):
    if model:
        return model
    env_model = os.environ.get("AI_MODEL") or os.environ.get(f"{provider.upper()}_MODEL")
    return env_model or PROVIDER_PRESETS[provider]["model"]


def run_provider(provider, conditions_path, out_root, model=None, label=None):
    """Run the MVP pipeline once for one provider; return a result dict."""
    label = label or provider
    provider_dir = os.path.join(out_root, label)
    work_dir = os.path.join(provider_dir, "_work")
    if os.path.exists(provider_dir):
        shutil.rmtree(provider_dir)
    os.makedirs(work_dir, exist_ok=True)

    # Isolate the run: concept_output/ lands next to the conditions copy.
    work_conditions = os.path.join(work_dir, "design_conditions.json")
    shutil.copy2(conditions_path, work_conditions)
    pptx_path = os.path.join(work_dir, "concept_output", "概念方案.pptx")

    env = dict(os.environ)
    env["AI_PROVIDER"] = provider
    if model:
        env["AI_MODEL"] = model
    env.pop("AI_DEMO_MODE", None)  # force real-model mode

    started = time.time()
    proc = subprocess.run(
        [sys.executable, "-m", "modules.m2_concept_design.mvp_pipeline",
         work_conditions, pptx_path],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=900,
    )
    total_seconds = round(time.time() - started, 1)

    concept_out = os.path.join(work_dir, "concept_output")
    steps = {}
    prev_mtime = started
    for step, files in STEP_ARTIFACTS.items():
        paths = [os.path.join(concept_out, f) for f in files]
        existing = [p for p in paths if os.path.exists(p)]
        mtime = max((os.path.getmtime(p) for p in existing), default=None)
        approx = round(mtime - prev_mtime, 1) if mtime else None
        if approx is not None and approx < 0:
            approx = None  # mtime ordering unreliable; do not report bogus deltas
        steps[step] = {
            "ok": bool(existing),
            "files": [os.path.basename(p) for p in existing],
            # Approximate: file mtimes mark step completion order.
            "approx_seconds": approx,
        }
        if mtime:
            prev_mtime = mtime

    # Promote artifacts to outputs/model-compare/<provider>/
    copied = []
    if os.path.isdir(concept_out):
        for name in os.listdir(concept_out):
            src = os.path.join(concept_out, name)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(provider_dir, name))
                copied.append(name)
    shutil.rmtree(work_dir, ignore_errors=True)

    return {
        "provider": provider,
        "model": _provider_model(provider, model),
        "label": label,
        "ok": proc.returncode == 0,
        "total_seconds": total_seconds,
        "steps": steps,
        "artifacts": sorted(copied),
        # stderr tail only for diagnosis; API keys are never printed by the client.
        "error_tail": (proc.stderr or "")[-800:] if proc.returncode != 0 else "",
    }


def _parse_spec(spec):
    """Parse 'provider' or 'provider@model' into (provider, model, label)."""
    if "@" in spec:
        provider, model = spec.split("@", 1)
        return provider.strip().lower(), model.strip(), f"{provider.strip().lower()}@{model.strip()}"
    return spec.strip().lower(), None, spec.strip().lower()


def main():
    parser = argparse.ArgumentParser(description="MVP pipeline multi-model comparison")
    parser.add_argument("--providers", default="deepseek",
                        help="Comma-separated specs, e.g. deepseek,openai or deepseek@deepseek-reasoner")
    parser.add_argument("--conditions",
                        default=os.path.join(ROOT, "templates", "design_conditions.sample.json"))
    parser.add_argument("--out", default=os.path.join(ROOT, "outputs", "model-compare"))
    args = parser.parse_args()

    specs = [_parse_spec(s) for s in args.providers.split(",") if s.strip()]
    unknown = [p for p, _, _ in specs if p not in PROVIDER_PRESETS]
    if unknown:
        raise SystemExit(f"Unknown providers: {unknown}. Supported: {sorted(PROVIDER_PRESETS)}")

    os.makedirs(args.out, exist_ok=True)
    results = []
    for provider, model, label in specs:
        print(f"[compare] running provider={provider} model={_provider_model(provider, model)} ...", flush=True)
        try:
            result = run_provider(provider, args.conditions, args.out, model=model, label=label)
        except Exception as exc:  # keep comparison going for remaining providers
            result = {"provider": provider, "model": _provider_model(provider, model),
                      "label": label, "ok": False, "total_seconds": None, "steps": {},
                      "artifacts": [], "error_tail": f"{type(exc).__name__}: {exc}"}
        results.append(result)
        status = "OK" if result["ok"] else "FAILED"
        print(f"[compare] {label}: {status} in {result['total_seconds']}s", flush=True)

    summary = {
        "conditions": os.path.relpath(args.conditions, ROOT),
        "providers": results,
    }
    summary_path = os.path.join(args.out, "compare-summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"[compare] summary -> {summary_path}")


if __name__ == "__main__":
    main()
