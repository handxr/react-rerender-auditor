# React Re-render & Performance Auditor

A [Claude Code](https://docs.anthropic.com/en/docs/claude-code) skill that statically analyzes React components for patterns causing unnecessary re-renders and performance issues.

## What it does

Scans your React codebase and detects 5 categories of performance issues:

| Category | Severity | Example |
|----------|----------|---------|
| **Inline objects** | Error | `config={{ dark: true }}` — new ref every render |
| **Inline arrays** | Error | `options={["a", "b"]}` — new ref every render |
| **Inline functions** | Warning | `onClick={() => save()}` — new ref every render |
| **Context value** | Error | `<Provider value={{ theme }}>` — re-renders ALL consumers |
| **async useEffect** | Error | `useEffect(async () => ...)` — broken cleanup |
| **setState no deps** | Error | `useEffect(() => { setState() })` — infinite loop |
| **Multi setState** | Warning | 3+ setState in one useEffect — cascading re-renders |
| **JSON.parse in render** | Warning | `JSON.parse(...)` without useMemo |
| **.sort() in render** | Warning | Mutates + runs every render |
| **.filter().map()** | Warning | Double iteration without memoization |
| **new RegExp in render** | Warning | Recompiled every render |
| **Large component** | Warning | Component > 250 lines |
| **Too many props** | Warning | Component with > 10 props |
| **Too many useState** | Warning | 5+ useState hooks in one component |
| **Prop spreading** | Info | `{...props}` forwards unknown re-render triggers |

## Supported file types

`.jsx` `.tsx` `.js` `.ts`

Detects components defined as function declarations (`function App()`) and arrow functions (`const App = () =>`), including exported and default-exported variants.

## Installation

### Via skills.sh (recommended)

```bash
npx skills add handxr/react-rerender-auditor
```

This installs the skill across all supported AI coding agents (Claude Code, Cursor, Windsurf, Codex, Gemini CLI, GitHub Copilot, Continue, Antigravity, OpenCode).

### Standalone script

The Python auditor works independently without any AI agent:

```bash
# Single file
python3 scripts/react_rerender_auditor.py src/components/Dashboard.tsx

# Entire project
python3 scripts/react_rerender_auditor.py src/

# Include low-severity hints (prop spreading, approaching thresholds)
python3 scripts/react_rerender_auditor.py src/ --strict

# Machine-readable output for CI/tooling
python3 scripts/react_rerender_auditor.py src/ --json
```

No dependencies required — uses only Python 3 standard library.

## Example output

```
================================================================
  React Re-render Audit: src/components/Dashboard.tsx
================================================================
  obj:3 | arr:2 | fn:5 | ctx:1 | effect:3 | expensive:3 | complexity:2 = 20 total

  Inline Creations (re-render triggers):
  !! L68: Inline object in prop 'config' creates new reference every render
     -> Extract to a variable outside render, or useMemo if dynamic
  !! L71: Inline array in prop 'options' creates new reference every render
     -> Extract to a constant or useMemo
  !~ L74: Inline function in prop 'onChange' creates new reference every render
     -> Extract to useCallback: const handler = useCallback((...) => { ... }, [deps])

  Context Issues:
  !! L83: 'ThemeContext.Provider' value is inline object — ALL consumers re-render on every parent render
     -> Wrap with useMemo: const value = useMemo(() => ({ ... }), [deps])

  useEffect Anti-patterns:
  !! L30: useEffect callback is async — returns Promise instead of cleanup function
     -> Define async fn inside: useEffect(() => { const fn = async () => { ... }; fn(); }, [deps])
  !! L37: useEffect with setState and NO dependency array — causes infinite re-render loop
     -> Add dependency array: useEffect(() => { ... }, [deps])

  Expensive Render Operations:
  !~ L52: JSON.parse() in render — expensive on every render
     -> Wrap with useMemo: useMemo(() => JSON.parse(...), [deps])
  !~ L55: .sort() in render — mutates array and runs every render
     -> Memoize: useMemo(() => [...items].sort(...), [items])

  Component Complexity:
  !~ L8: Component 'Dashboard' has 12 props — API too complex
     -> Group related props, use composition, or split component
```

## Severity levels

| Icon | Level | Meaning |
|------|-------|---------|
| `!!` | Error | Bugs or severe performance problems — fix immediately |
| `!~` | Warning | Unnecessary re-renders in practice — fix in hot paths |
| `~~` | Info | Code smell, may cause issues at scale (only with `--strict`) |

## JSON output structure

```json
{
  "file": "src/components/Dashboard.tsx",
  "summary": {
    "inline_objects": 3,
    "inline_arrays": 2,
    "inline_functions": 5,
    "context_issues": 1,
    "useeffect_issues": 3,
    "expensive_ops": 3,
    "complexity": 2,
    "total_issues": 20
  },
  "issues": [
    {
      "type": "inline-object",
      "severity": "error",
      "line": 68,
      "file": "src/components/Dashboard.tsx",
      "prop": "config",
      "message": "Inline object in prop 'config' creates new reference every render",
      "suggestion": "Extract to a variable outside render, or useMemo if dynamic"
    }
  ]
}
```

## Fix priority guide

When facing many issues, fix in this order for maximum impact:

1. **Context providers** — one fix eliminates re-renders across entire subtrees
2. **useEffect bugs** — async effects and infinite loops are correctness issues
3. **Inline creations in lists** — `.map(item => <Child config={{ ... }} />)` creates N new objects
4. **Expensive operations** — JSON.parse and .sort() in frequently-rendered components
5. **Component complexity** — architectural improvements for long-term maintainability

## React 19 note

If your project uses React 19's compiler, it auto-memoizes many patterns. However:
- Context provider values still need manual memoization
- useEffect anti-patterns are bugs regardless of compiler
- Component complexity remains an architectural concern

See [references/rerender-rules.md](references/rerender-rules.md) for detailed rules and edge cases.

## License

MIT
