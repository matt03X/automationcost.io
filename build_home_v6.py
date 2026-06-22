#!/usr/bin/env python3
"""
build_home_v6.py — fills the DATA marker blocks in home-v6.html from the SOURCES
OF TRUTH (the existing calculators). Same principle as the other WizardCost
builds: the blocks between markers are GENERATED, never hand-edited.

Strategy (parity-safe): copy the relevant marker blocks VERBATIM out of the
existing calculator files, so home-v6 carries the exact same verified data —
no second hand-maintained copy of prices.

  home-v6 block              <-  source file / source block
  ---------------------------------------------------------------------------
  DATA:TOOLS                 <-  automation/calculator.html  DATA:TOOLS
  DATA:SCORING_AUTO          <-  automation/calculator.html  DATA:SCORING
  DATA:MODELS                <-  llm/calculator.html          DATA:MODELS
  DATA:SCORING_LLM           <-  llm/calculator.html          DATA:SCORING (renamed
                                 SCORE_W/ROLE_WEIGHTS -> L_SCORE_W/L_ROLE_WEIGHTS
                                 so they don't collide with the automation block)

Run:  python build_home_v6.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HOME = ROOT / "home-v6.html"
AUTO = ROOT / "automation" / "calculator.html"
LLM = ROOT / "llm" / "calculator.html"


def extract_block(text, name):
    """Return the inner content between /* DATA:<name>:START */ and END (exclusive of markers)."""
    m = re.search(
        r"/\*\s*DATA:" + re.escape(name) + r":START\s*\*/(.*?)/\*\s*DATA:" + re.escape(name) + r":END\s*\*/",
        text, re.S)
    if not m:
        raise SystemExit(f"ERROR: source block DATA:{name} not found")
    return m.group(1)


def replace_block(text, name, inner):
    """Replace the inner content of home-v6's DATA:<name> block, keeping the marker comments."""
    pat = re.compile(
        r"(/\*\s*DATA:" + re.escape(name) + r":START\s*\*/)(.*?)(/\*\s*DATA:" + re.escape(name) + r":END\s*\*/)",
        re.S)
    if not pat.search(text):
        raise SystemExit(f"ERROR: target block DATA:{name} not found in home-v6.html")
    # keep the START marker line (with its trailing comment), drop the old body, inject the new one
    def _sub(m):
        start = m.group(1)
        # strip any trailing inline comment after START on the same line in the original target,
        # but we only have the marker itself in group(1); preserve it verbatim.
        return start + "\n" + inner.rstrip("\n") + "\n" + m.group(3)
    return pat.sub(_sub, text, count=1)


def main():
    auto = AUTO.read_text(encoding="utf-8")
    llm = LLM.read_text(encoding="utf-8")
    home = HOME.read_text(encoding="utf-8")

    # 1) TOOLS (verbatim)
    tools = extract_block(auto, "TOOLS").strip("\n")
    # drop the leading "/* generováno ... */" comment line if present (it's the marker's own comment)
    tools = re.sub(r"^\s*/\*[^*]*generov[^*]*\*/\s*", "", tools, count=1)

    # 2) automation SCORING (verbatim) -> SCORING_AUTO
    scoring_auto = extract_block(auto, "SCORING").strip("\n")
    scoring_auto = re.sub(r"^\s*/\*[^*]*generov[^*]*\*/\s*", "", scoring_auto, count=1)

    # 3) MODELS (verbatim, includes MODELS const + MODELS_REVIEWED)
    models = extract_block(llm, "MODELS").strip("\n")
    models = re.sub(r"^\s*/\*[^*]*generov[^*]*\*/\s*", "", models, count=1)

    # 4) llm SCORING -> SCORING_LLM, rename colliding consts
    scoring_llm = extract_block(llm, "SCORING").strip("\n")
    scoring_llm = re.sub(r"^\s*/\*[^*]*generov[^*]*\*/\s*", "", scoring_llm, count=1)
    # rename const declarations that collide with the automation block
    scoring_llm = re.sub(r"\bconst\s+SCORE_W\b", "const L_SCORE_W", scoring_llm)
    scoring_llm = re.sub(r"\bconst\s+ROLE_WEIGHTS\b", "const L_ROLE_WEIGHTS", scoring_llm)
    # UC_ROLE and MODEL_SCORES are unique to LLM -> keep names

    home = replace_block(home, "TOOLS", tools)
    home = replace_block(home, "SCORING_AUTO", scoring_auto)
    home = replace_block(home, "MODELS", models)
    home = replace_block(home, "SCORING_LLM", scoring_llm)

    HOME.write_text(home, encoding="utf-8")

    # sanity report
    n_tools = len(re.findall(r"slug:\s*\"", tools))
    n_models = len(re.findall(r"\{\s*n:\s*\"", models))
    rev = re.search(r'MODELS_REVIEWED\s*=\s*"([^"]+)"', models)
    print("home-v6.html DATA blocks rebuilt:")
    print(f"  DATA:TOOLS        -> {n_tools} tools")
    print(f"  DATA:SCORING_AUTO -> {'SCORE_W' if 'SCORE_W' in scoring_auto else '??'}, ROLE_WEIGHTS, TOOL_SCORES")
    print(f"  DATA:MODELS       -> {n_models} models (reviewed {rev.group(1) if rev else '?'})")
    print(f"  DATA:SCORING_LLM  -> L_SCORE_W, L_ROLE_WEIGHTS, UC_ROLE, MODEL_SCORES")
    if "const L_SCORE_W" not in scoring_llm or "const L_ROLE_WEIGHTS" not in scoring_llm:
        print("WARNING: LLM scoring rename did not apply as expected", file=sys.stderr)


if __name__ == "__main__":
    main()
