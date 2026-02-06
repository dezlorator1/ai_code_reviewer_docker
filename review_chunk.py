import argparse
import re
from pathlib import Path
import uuid
import logging
import requests
from datetime import datetime
import yaml

# Определяем путь к конфигу
config_path = Path(__file__).parent / "config.yml"

# --- Читаем конфиг ---
with open(config_path) as f:
    config = yaml.safe_load(f)

# ==== LOG CONFIG ====
SCRIPT_NAME = Path(__file__).name
LOG_FILE    = Path(config['paths']['LOG_FILE'])
MR_CONTEXT_FILE = Path(config['paths']['OUT_DIR']) / "mr_context.md"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, mode="a"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(SCRIPT_NAME)

# ==== CONFIG ====
API_URL = config['llm']['api_url']
MODEL = config['llm']['model']
MAX_TOKENS = config['llm']['max_tokens']

# ==== PROMPT ====
PROMPT_TEMPLATE = """You are an expert code reviewer for an OpenSearch plugin that provides Splunk-like query language.

PROJECT CONTEXT:
- Language: Java
- Product: OpenSearch plugin with custom query language
- Critical: Changes in query parsing/execution affect enterprise customers
- Users: Large companies relying on query stability

⚠️ CRITICAL UNDERSTANDING: ORIGINAL FILE vs DIFF

You receive TWO inputs:
1. **ORIGINAL FILE** - current state of the file in dev branch (BEFORE the MR changes)
2. **GIT DIFF** - what changes this MR introduces

Lines in diff:
- Lines with `+` are ADDED by this MR
- Lines with `-` are REMOVED by this MR
- Lines without +/- are context (unchanged)

🚨 MOST COMMON MISTAKE TO AVOID:

❌ WRONG:
"The diff adds `private int timeout;` at line 50"
"The original file already has `private int timeout;` at line 50"
"This is a DUPLICATE!"

✅ CORRECT:
"The original file does NOT have `private int timeout;`"
"The diff ADDS it at line 50"
"After applying this MR, the file WILL have this field"
"This is NORMAL - not a duplicate"

RULE: If something appears in BOTH original file AND diff with `+`, then YES it's a duplicate!
If something appears ONLY in diff with `+`, it's a NEW addition (not a duplicate).

---

MR GLOBAL CONTEXT:
{mr_context}

---

CURRENT FILE BEING REVIEWED: {filename}

GIT DIFF (changes in this MR):
```diff
{diff}
```

ORIGINAL FILE (state in dev branch BEFORE this MR):
```
{original}
```

---

REVIEW PRIORITIES:

🔴 CRITICAL - Must catch:
1. **Query Language Breaking Changes**
   - Changed query syntax that breaks existing queries
   - Modified query execution semantics
   - Altered aggregation behavior
   - Changed system settings
   - Changed language commands behavior

2. **Data Integrity**
   - Null pointer exceptions in query execution path
   - Missing validation of query parameters
   - Incorrect data type handling

3. **Security**
   - Query injection vulnerabilities
   - Missing access control checks
   - Unsafe data operations

🟡 HIGH - Important:
1. **Business Logic Changes**
   - Modified query results for same input
   - Changed default behaviors
   - Performance degradation in hot paths

2. **API Compatibility**
   - Breaking changes in public methods
   - Changed method signatures without deprecation

3. **Error Handling**
   - Missing try-catch in critical paths
   - Poor error messages for query parsing failures

🟢 MEDIUM:
- Missing input validation
- Code smells
- Inconsistent naming
- Missing null checks

⚪ LOW:
- Style issues
- Minor optimizations
- Documentation

---

SPECIAL CHECKS FOR QUERY LANGUAGE FILES:

If file path contains: `query`, `parser`, `executor`, `aggregation`, `function`, `command`:

⚠️ FLAG if you see:
- Changes to operator precedence
- Modified parsing logic for existing commands
- Altered aggregation calculation formulas
- Removed support for query syntax without deprecation
- Altered language command params

✅ APPROVE if:
- Added new query features (backward compatible)
- Fixed bugs that produce incorrect results
- Performance improvements without semantic changes

---

CROSS-FILE DEPENDENCY CHECK:

Before flagging "method X not found" or "class Y doesn't exist":
1. Check MR_CONTEXT section "Files Changed"
2. If the missing item is added in another file in this MR → NOT an issue
3. Only flag if missing item is NOT part of this MR

---

OUTPUT FORMAT:

### {filename}

**Summary:** [1-2 sentences: what changed in this file]

**Query Language Impact:** [BREAKING / COMPATIBLE / NONE]
[If changes affect query parsing/execution, describe impact on users]

#### Issues Found: [count]

[For each issue:]

**[SEVERITY] [Category]** Line <line_number>
- **Issue:** [What's wrong - be specific]
- **Impact:** [How this affects users/system]
- **Suggestion:** [How to fix]
- **Code:**
```java
[relevant code snippet]
```

Categories: Bug | Security | Performance | API Breaking | Query Breaking | Concurrency | Style

---

[If no issues:]
#### ✅ No Issues Detected

The changes look good. [Optional: mention positive aspects]

---

SEVERITY CALIBRATION:

**CRITICAL:**
- Query language breaking changes affecting production queries
- Null pointer that WILL crash
- Data loss/corruption risk
- Security vulnerability

**HIGH:**
- Query results change for existing queries (without breaking)
- Potential crashes in edge cases
- Missing critical error handling
- Performance regression >20%

**MEDIUM:**
- Missing validation
- Code smells affecting maintainability
- Inconsistent patterns

**LOW:**
- Style issues
- Minor optimizations

---

BEFORE SUBMITTING:
1. ✓ Did I check if "missing" dependencies are added in other files (MR_CONTEXT)?
2. ✓ Did I distinguish between ORIGINAL file and DIFF correctly?
3. ✓ Did I flag query language changes appropriately?
4. ✓ Did I avoid false positives (e.g., flagging newly added code as duplicate)?
"""

# ==== FUNCTIONS ====
def load_mr_context():
    """Load MR global context if available."""
    if MR_CONTEXT_FILE.exists():
        context = MR_CONTEXT_FILE.read_text(errors="ignore")
        log.info(f"MR_CONTEXT LOADED size={len(context)} bytes")
        return context
    else:
        log.warning(f"MR_CONTEXT FILE NOT FOUND: {MR_CONTEXT_FILE}")
        return "MR context not available - reviewing file in isolation."

def extract_file_from_diff(diff_text):
    m = re.search(r"diff --git a/(.*?) b/", diff_text)
    return m.group(1) if m else None

def load_original(project_root, file_path):
    full_path = Path(project_root) / file_path
    if not full_path.exists():
        log.warning(f"ORIGINAL FILE NOT FOUND: {full_path}")
        return "<FILE NOT FOUND>"
    return full_path.read_text(errors="ignore")

def call_llm(prompt):
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "You are a strict code reviewer for OpenSearch plugin with query language expertise."},
            {"role": "user", "content": prompt}
        ],
        "temperature": config['llm']['temperature'],
        "max_tokens": MAX_TOKENS
    }

    log.info("LLM REQUEST START")
    start = datetime.now()

    r = requests.post(API_URL, json=payload, timeout=300)
    r.raise_for_status()

    dt = (datetime.now() - start).total_seconds()
    log.info(f"LLM REQUEST FINISH time={dt}s")

    return r.json()["choices"][0]["message"]["content"]

# ==== MAIN ====
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunk", required=True)
    ap.add_argument("--project", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    log.info(f"START chunk={args.chunk}")

    # Load MR global context
    mr_context = load_mr_context()

    diff_text = Path(args.chunk).read_text()
    file_path = extract_file_from_diff(diff_text)
    log.info(f"DIFF FILE PARSED target_file={file_path}")

    original = ""
    if file_path:
        original = load_original(args.project, file_path)
        log.info(f"ORIGINAL SIZE bytes={len(original)}")

    # Smart truncation for large files
    MAX_ORIGINAL_SIZE = 50000
    if len(original) > MAX_ORIGINAL_SIZE:
        log.warning(f"ORIGINAL FILE TOO LARGE ({len(original)} bytes), TRUNCATING")
        # Keep imports (first 5000 chars) + end of file (last 40000 chars)
        # This preserves class structure and recent changes
        imports_section = original[:5000]
        relevant_code = original[-(MAX_ORIGINAL_SIZE - 5000):]
        original = imports_section + "\n\n[... middle section truncated ...]\n\n" + relevant_code
        log.info(f"TRUNCATED TO {len(original)} bytes (kept imports + tail)")

    prompt = PROMPT_TEMPLATE.format(
        filename=file_path,
        original=original,
        diff=diff_text,
        mr_context=mr_context
    )
    log.info(f"PROMPT SIZE chars={len(prompt)}")

    result = call_llm(prompt)

    Path(args.out).write_text(result)

    log.info(f"WRITE RESULT {args.out} bytes={len(result)}")
    log.info(f"END chunk={args.chunk}")

if __name__ == "__main__":
    main()