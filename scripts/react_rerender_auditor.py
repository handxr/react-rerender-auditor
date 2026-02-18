#!/usr/bin/env python3
"""React Re-render & Performance Auditor.

Scans React components for patterns that cause unnecessary re-renders:
- Inline object/array/function creation in JSX props
- Context.Provider with unstable value references
- useEffect anti-patterns (async, missing deps, setState loops)
- Expensive computations in render body (unmemoized)
- Component complexity issues (too many props/state, too large)

Usage:
    python react_rerender_auditor.py <file_or_dir> [--json] [--strict]

Arguments:
    file_or_dir   Path to a file or directory to scan
    --json        Output raw JSON (default: human-readable)
    --strict      Include low-severity hints (default: warnings + errors only)
"""

import json
import re
import sys
from pathlib import Path

SUPPORTED_EXTENSIONS = {".jsx", ".tsx", ".js", ".ts"}
EXCLUDED_DIRS = {
    "node_modules", ".next", "dist", "build", ".git", "vendor",
    "__tests__", "coverage", ".turbo", ".cache", ".expo",
}

# Props that are safe to skip in inline detection
SKIP_PROPS = {"key", "ref"}


# ── Helpers ───────────────────────────────────────────────────────────

def parse_args():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)
    return args[0], "--json" in args, "--strict" in args


def find_files(target):
    p = Path(target)
    if p.is_file():
        return [p]
    if p.is_dir():
        files = []
        for ext in SUPPORTED_EXTENSIONS:
            files.extend(p.rglob(f"*{ext}"))
        files = [f for f in files if not any(part in EXCLUDED_DIRS for part in f.parts)]
        return sorted(set(files))
    print(f"Error: {target} is not a file or directory", file=sys.stderr)
    sys.exit(1)


def line_at(content, pos):
    """Return 1-based line number for a character position."""
    return content[:pos].count("\n") + 1


def find_matching_brace(content, start):
    """Find position of matching closing brace, handling strings."""
    depth = 0
    i = start
    in_str = None
    length = len(content)
    while i < length:
        c = content[i]
        # skip escaped chars
        if i > 0 and content[i - 1] == "\\":
            i += 1
            continue
        # string tracking
        if c in ('"', "'", "`"):
            if in_str == c:
                in_str = None
            elif in_str is None:
                in_str = c
        if in_str is None:
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return None


# ── Component finder ──────────────────────────────────────────────────

def find_components(content):
    """Find React component boundaries (function declarations + arrow fns)."""
    comps = []

    # function Name(props) { ... }
    for m in re.finditer(
        r"^[ \t]*(?:export\s+(?:default\s+)?)?function\s+([A-Z]\w*)\s*\(([^)]*)\)",
        content, re.MULTILINE,
    ):
        _add_component(comps, content, m, m.group(1), m.group(2))

    # const Name = (props) => { ... }  or  const Name: FC = (props) => { ... }
    for m in re.finditer(
        r"^[ \t]*(?:export\s+(?:default\s+)?)?(?:const|let)\s+([A-Z]\w*)"
        r"(?:\s*:\s*[^=]+?)?\s*=\s*(?:\([^)]*\)|[a-z_]\w*)\s*(?::[^=]*?)?\s*=>\s*\{",
        content, re.MULTILINE,
    ):
        params_m = re.search(r"=\s*\(([^)]*)\)", content[m.start() : m.end()])
        params = params_m.group(1) if params_m else ""
        _add_component(comps, content, m, m.group(1), params)

    return comps


def _add_component(comps, content, m, name, params):
    brace_pos = content.find("{", m.end() - 1)
    if brace_pos == -1:
        brace_pos = content.find("{", m.start())
    if brace_pos == -1:
        return
    end = find_matching_brace(content, brace_pos)
    if end is None:
        return
    body = content[brace_pos : end + 1]
    comps.append({
        "name": name,
        "start_line": line_at(content, m.start()),
        "end_line": line_at(content, end),
        "params": params.strip(),
        "body": body,
    })


# ── Detectors ─────────────────────────────────────────────────────────

def detect_inline_objects(content, filepath):
    """prop={{ ... }} — new object reference every render."""
    issues = []
    for m in re.finditer(r"(\w+)\s*=\s*\{\s*\{", content):
        prop = m.group(1)
        if prop in SKIP_PROPS:
            continue
        sev = "warning" if prop == "style" else "error"
        issues.append({
            "type": "inline-object",
            "severity": sev,
            "line": line_at(content, m.start()),
            "file": str(filepath),
            "prop": prop,
            "message": f"Inline object in prop '{prop}' creates new reference every render",
            "suggestion": (
                f"Extract to a variable outside render, or useMemo if dynamic: "
                f"const {prop}Value = useMemo(() => ({{ ... }}), [deps])"
            ),
        })
    return issues


def detect_inline_arrays(content, filepath):
    """prop={[ ... ]} — new array reference every render."""
    issues = []
    for m in re.finditer(r"(\w+)\s*=\s*\{\s*\[", content):
        prop = m.group(1)
        if prop in SKIP_PROPS:
            continue
        issues.append({
            "type": "inline-array",
            "severity": "error",
            "line": line_at(content, m.start()),
            "file": str(filepath),
            "prop": prop,
            "message": f"Inline array in prop '{prop}' creates new reference every render",
            "suggestion": f"Extract to a constant or useMemo: const {prop}Value = useMemo(() => [...], [deps])",
        })
    return issues


def detect_inline_functions(content, filepath):
    """prop={() => ...} or prop={function() ...} — new function every render."""
    issues = []
    # Arrow functions in JSX props
    for m in re.finditer(r"(\w+)\s*=\s*\{\s*(?:\([^)]*\)|[a-z_]\w*)\s*=>", content):
        prop = m.group(1)
        if prop in SKIP_PROPS or prop in ("className", "children"):
            continue
        # Skip variable assignments (const x = () => ...) — not JSX props
        before = content[max(0, m.start() - 30) : m.start()].strip()
        if before.endswith(("const", "let", "var", "=")):
            continue
        issues.append({
            "type": "inline-function",
            "severity": "warning",
            "line": line_at(content, m.start()),
            "file": str(filepath),
            "prop": prop,
            "message": f"Inline function in prop '{prop}' creates new reference every render",
            "suggestion": "Extract to useCallback: const handler = useCallback((...) => { ... }, [deps])",
        })
    # Function expressions
    for m in re.finditer(r"(\w+)\s*=\s*\{\s*function\s*\(", content):
        prop = m.group(1)
        issues.append({
            "type": "inline-function",
            "severity": "warning",
            "line": line_at(content, m.start()),
            "file": str(filepath),
            "prop": prop,
            "message": f"Inline function expression in prop '{prop}' — new reference every render",
            "suggestion": "Extract to useCallback or a const handler",
        })
    return issues


def detect_context_provider_value(content, filepath):
    """<Provider value={{ ... }}> — all consumers re-render every parent render."""
    issues = []
    for m in re.finditer(
        r"<(\w*(?:Context\.Provider|Provider))\s[^>]*value\s*=\s*\{\s*\{", content
    ):
        issues.append({
            "type": "context-inline-value",
            "severity": "error",
            "line": line_at(content, m.start()),
            "file": str(filepath),
            "provider": m.group(1),
            "message": f"'{m.group(1)}' value is inline object — ALL consumers re-render on every parent render",
            "suggestion": "Wrap with useMemo: const value = useMemo(() => ({ ... }), [deps])",
        })
    return issues


def detect_useeffect_issues(content, filepath):
    """useEffect anti-patterns: async, setState loops, missing deps."""
    issues = []

    # 1) useEffect(async ...) — returns Promise, not cleanup
    for m in re.finditer(r"useEffect\s*\(\s*async\s", content):
        issues.append({
            "type": "useeffect-async",
            "severity": "error",
            "line": line_at(content, m.start()),
            "file": str(filepath),
            "message": "useEffect callback is async — returns Promise instead of cleanup function",
            "suggestion": "Define async fn inside: useEffect(() => { const fn = async () => { ... }; fn(); }, [deps])",
        })

    # 2) useEffect with setState + no deps array = infinite loop
    for m in re.finditer(r"useEffect\s*\(\s*(?:\(\)\s*=>|function\s*\(\))\s*\{", content):
        brace = m.end() - 1
        end = find_matching_brace(content, brace)
        if end is None:
            continue
        body = content[brace : end + 1]
        set_calls = re.findall(r"\bset[A-Z]\w*\s*\(", body)
        if not set_calls:
            continue

        # Check for deps array after closing brace
        after = content[end + 1 : end + 20].strip()
        has_no_deps = after.startswith(")") or after.startswith(";")

        ln = line_at(content, m.start())
        if has_no_deps:
            issues.append({
                "type": "useeffect-setstate-no-deps",
                "severity": "error",
                "line": ln,
                "file": str(filepath),
                "message": "useEffect with setState and NO dependency array — causes infinite re-render loop",
                "suggestion": "Add dependency array: useEffect(() => { ... }, [deps])",
            })
        elif len(set_calls) >= 3:
            issues.append({
                "type": "useeffect-multi-setstate",
                "severity": "warning",
                "line": ln,
                "file": str(filepath),
                "message": f"useEffect with {len(set_calls)} setState calls — cascading re-renders",
                "suggestion": "Batch with useReducer or combine into single state object",
            })

    return issues


def detect_expensive_render_ops(content, filepath):
    """Expensive operations in render body without memoization."""
    issues = []

    patterns = [
        (r"\bJSON\.(parse|stringify)\s*\(", "JSON.{op}() in render — expensive on every render",
         "Wrap with useMemo: useMemo(() => JSON.{op}(...), [deps])"),
        (r"\.sort\s*\(", ".sort() in render — mutates array and runs every render",
         "Memoize: useMemo(() => [...items].sort(...), [items])"),
        (r"\bnew\s+RegExp\s*\(", "new RegExp() in render — recreated every render",
         "Move to module scope or useMemo"),
        (r"\.filter\s*\([^)]*\)\s*\.map\s*\(", ".filter().map() chain — iterates array twice every render",
         "Memoize filtered result: useMemo(() => items.filter(...), [items])"),
    ]

    for pat, msg_tpl, sug_tpl in patterns:
        for m in re.finditer(pat, content):
            # Skip if inside useMemo/useCallback
            preceding = content[max(0, m.start() - 300) : m.start()]
            if "useMemo" in preceding or "useCallback" in preceding:
                continue
            op = m.group(1) if m.lastindex else ""
            msg = msg_tpl.replace("{op}", op)
            sug = sug_tpl.replace("{op}", op)
            issues.append({
                "type": "expensive-render-op",
                "severity": "warning",
                "line": line_at(content, m.start()),
                "file": str(filepath),
                "message": msg,
                "suggestion": sug,
            })

    return issues


def detect_component_complexity(content, filepath):
    """Large components, too many props, excessive useState."""
    issues = []
    for comp in find_components(content):
        lines = comp["end_line"] - comp["start_line"] + 1
        name = comp["name"]
        ln = comp["start_line"]

        # Size check
        if lines > 250:
            issues.append({
                "type": "large-component", "severity": "warning",
                "line": ln, "file": str(filepath), "component": name,
                "message": f"Component '{name}' is {lines} lines — consider splitting",
                "suggestion": "Extract sub-components, custom hooks, or utilities",
            })
        elif lines > 150:
            issues.append({
                "type": "large-component", "severity": "info",
                "line": ln, "file": str(filepath), "component": name,
                "message": f"Component '{name}' is {lines} lines — approaching threshold",
                "suggestion": "Consider extracting custom hooks or sub-components",
            })

        # Props count
        if comp["params"]:
            pm = re.search(r"\{\s*([^}]+)\}", comp["params"])
            if pm:
                props = [p.strip() for p in pm.group(1).split(",")
                         if p.strip() and not p.strip().startswith("...")]
                ct = len(props)
                if ct > 10:
                    issues.append({
                        "type": "too-many-props", "severity": "warning",
                        "line": ln, "file": str(filepath), "component": name,
                        "message": f"Component '{name}' has {ct} props — API too complex",
                        "suggestion": "Group related props, use composition, or split component",
                    })
                elif ct > 7:
                    issues.append({
                        "type": "too-many-props", "severity": "info",
                        "line": ln, "file": str(filepath), "component": name,
                        "message": f"Component '{name}' has {ct} props",
                        "suggestion": "Consider grouping related props",
                    })

        # useState count
        if comp["body"]:
            sc = len(re.findall(r"\buseState\s*[<(]", comp["body"]))
            if sc > 5:
                issues.append({
                    "type": "too-many-state", "severity": "warning",
                    "line": ln, "file": str(filepath), "component": name,
                    "message": f"Component '{name}' has {sc} useState hooks — excessive state",
                    "suggestion": "Combine with useReducer or extract into custom hook",
                })
            elif sc > 3:
                issues.append({
                    "type": "too-many-state", "severity": "info",
                    "line": ln, "file": str(filepath), "component": name,
                    "message": f"Component '{name}' has {sc} useState hooks",
                    "suggestion": "Consider combining related state",
                })

    return issues


def detect_new_in_jsx(content, filepath):
    """new X() in JSX prop — new instance every render."""
    issues = []
    for m in re.finditer(r"=\s*\{\s*new\s+(\w+)\s*\(", content):
        cls = m.group(1)
        issues.append({
            "type": "inline-new",
            "severity": "warning",
            "line": line_at(content, m.start()),
            "file": str(filepath),
            "message": f"new {cls}() in JSX prop — new instance every render",
            "suggestion": f"Move to useMemo: const inst = useMemo(() => new {cls}(...), [])",
        })
    return issues


def detect_spread_props(content, filepath):
    """{...props} spreading may forward re-render triggers to children."""
    issues = []
    for m in re.finditer(r"<[A-Z]\w*[^>]*\{\s*\.\.\.(\w+)\s*\}", content):
        var = m.group(1)
        if var in ("props", "rest", "restProps", "otherProps"):
            issues.append({
                "type": "prop-spreading",
                "severity": "info",
                "line": line_at(content, m.start()),
                "file": str(filepath),
                "message": f"Spreading {{...{var}}} forwards unknown props — may trigger child re-renders",
                "suggestion": "Destructure only needed props explicitly",
            })
    return issues


# ── Main analysis ─────────────────────────────────────────────────────

def analyze_file(filepath, strict):
    try:
        content = filepath.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"file": str(filepath), "error": str(e), "issues": []}

    # Quick React heuristic
    if not any(kw in content for kw in ("React", "useState", "useEffect", "jsx", "className")):
        return {"file": str(filepath), "summary": _empty_summary(), "issues": []}

    all_issues = []
    for detector in (
        detect_inline_objects,
        detect_inline_arrays,
        detect_inline_functions,
        detect_context_provider_value,
        detect_useeffect_issues,
        detect_expensive_render_ops,
        detect_component_complexity,
        detect_new_in_jsx,
        detect_spread_props,
    ):
        all_issues.extend(detector(content, filepath))

    if not strict:
        all_issues = [i for i in all_issues if i["severity"] != "info"]

    return {"file": str(filepath), "summary": _build_summary(all_issues), "issues": all_issues}


def _empty_summary():
    return {k: 0 for k in (
        "inline_objects", "inline_arrays", "inline_functions",
        "context_issues", "useeffect_issues", "expensive_ops",
        "complexity", "total_issues",
    )}


def _build_summary(issues):
    return {
        "inline_objects": sum(1 for i in issues if i["type"] == "inline-object"),
        "inline_arrays": sum(1 for i in issues if i["type"] == "inline-array"),
        "inline_functions": sum(1 for i in issues if i["type"] == "inline-function"),
        "context_issues": sum(1 for i in issues if i["type"] == "context-inline-value"),
        "useeffect_issues": sum(1 for i in issues if i["type"].startswith("useeffect-")),
        "expensive_ops": sum(1 for i in issues if i["type"] == "expensive-render-op"),
        "complexity": sum(1 for i in issues if i["type"] in (
            "large-component", "too-many-props", "too-many-state", "prop-spreading"
        )),
        "total_issues": len(issues),
    }


# ── Output ────────────────────────────────────────────────────────────

SEVERITY_ICON = {"error": "!!", "warning": "!~", "info": "~~"}

CATEGORIES = [
    ("Inline Creations (re-render triggers)", [
        "inline-object", "inline-array", "inline-function", "inline-new",
    ]),
    ("Context Issues", ["context-inline-value"]),
    ("useEffect Anti-patterns", [
        "useeffect-async", "useeffect-multi-setstate", "useeffect-setstate-no-deps",
    ]),
    ("Expensive Render Operations", ["expensive-render-op"]),
    ("Component Complexity", [
        "large-component", "too-many-props", "too-many-state", "prop-spreading",
    ]),
]


def print_report(report):
    s = report["summary"]
    print(f"\n{'=' * 64}")
    print(f"  React Re-render Audit: {report['file']}")
    print(f"{'=' * 64}")

    if "error" in report:
        print(f"  Error: {report['error']}")
        return

    if s["total_issues"] == 0:
        print("  No issues found.\n")
        return

    parts = []
    for key, label in [
        ("inline_objects", "obj"), ("inline_arrays", "arr"),
        ("inline_functions", "fn"), ("context_issues", "ctx"),
        ("useeffect_issues", "effect"), ("expensive_ops", "expensive"),
        ("complexity", "complexity"),
    ]:
        if s.get(key):
            parts.append(f"{label}:{s[key]}")
    print(f"  {' | '.join(parts)} = {s['total_issues']} total")

    for cat_name, cat_types in CATEGORIES:
        cat_issues = [i for i in report["issues"] if i["type"] in cat_types]
        if not cat_issues:
            continue
        print(f"\n  {cat_name}:")
        for issue in cat_issues:
            icon = SEVERITY_ICON.get(issue["severity"], "  ")
            print(f"  {icon} L{issue['line']}: {issue['message']}")
            if issue.get("suggestion"):
                print(f"     -> {issue['suggestion']}")
    print()


def main():
    target, json_output, strict = parse_args()
    files = find_files(target)

    if not files:
        print("No supported files found.", file=sys.stderr)
        sys.exit(1)

    reports = [analyze_file(f, strict) for f in files]
    reports = [r for r in reports if json_output or r["summary"]["total_issues"] > 0]

    if json_output:
        out = reports if len(reports) > 1 else (reports[0] if reports else {"files": 0, "issues": []})
        print(json.dumps(out, indent=2))
    else:
        if not reports:
            print("\nNo React re-render issues found. Clean codebase!")
        else:
            for r in reports:
                print_report(r)
            if len(reports) > 1:
                t = {k: sum(r["summary"].get(k, 0) for r in reports) for k in (
                    "inline_objects", "inline_arrays", "inline_functions",
                    "context_issues", "useeffect_issues", "expensive_ops",
                    "complexity", "total_issues",
                )}
                inl = t["inline_objects"] + t["inline_arrays"] + t["inline_functions"]
                print(f"{'=' * 64}")
                print(f"  TOTAL: {len(reports)} files with issues")
                print(f"  {inl} inline | {t['context_issues']} ctx | {t['useeffect_issues']} effect | {t['expensive_ops']} expensive | {t['complexity']} complexity")
                print(f"  {t['total_issues']} total issues")
                print(f"{'=' * 64}")


if __name__ == "__main__":
    main()
