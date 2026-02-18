---
name: react-rerender-auditor
description: Audit React components for unnecessary re-renders, inline object/array/function creation in JSX props, Context.Provider with unstable values, useEffect anti-patterns (async callbacks, setState loops, missing deps), expensive unmemoized render operations, and component complexity issues. Use when reviewing React performance, debugging slow components, auditing a codebase for re-render issues, or when a user asks to check their React code for performance problems, find unnecessary re-renders, optimize components, or audit hook usage. Triggers on tasks involving .jsx/.tsx/.js/.ts files with React components.
---

# React Re-render & Performance Auditor

Static analysis tool that scans React code for patterns causing unnecessary re-renders.

## Workflow

1. Identify target file or directory to audit
2. Run the auditor script
3. Review findings by severity (errors first, then warnings)
4. Apply fixes starting with highest-impact issues (context providers > inline creations > hooks)
5. Re-run to verify fixes

## Running the Auditor

```bash
# Single file
python scripts/react_rerender_auditor.py src/components/Dashboard.tsx

# Entire project
python scripts/react_rerender_auditor.py src/

# Include low-severity hints
python scripts/react_rerender_auditor.py src/ --strict

# Machine-readable output
python scripts/react_rerender_auditor.py src/ --json
```

## What It Detects

### Inline Creations (highest impact)
- `prop={{ key: val }}` — inline objects create new reference every render
- `prop={[1, 2, 3]}` — inline arrays create new reference every render
- `onClick={() => fn()}` — inline functions create new reference every render
- `date={new Date()}` — new instances in JSX props

### Context Issues (cascading impact)
- `<Provider value={{ ... }}>` — inline value re-renders ALL consumers

### useEffect Anti-patterns (bugs)
- `useEffect(async () => ...)` — returns Promise instead of cleanup
- `useEffect(() => { setState() })` without deps — infinite loop
- useEffect with 3+ setState calls — cascading re-renders

### Expensive Render Operations
- `JSON.parse()`/`JSON.stringify()` without useMemo
- `.sort()` in render body (mutates + expensive)
- `.filter().map()` chains without memoization
- `new RegExp()` recreated every render

### Component Complexity
- Components over 250 lines (should split)
- Components with 10+ props (API too complex)
- Components with 5+ useState hooks (use useReducer)
- `{...props}` spreading (forwards unknown re-render triggers)

## Interpreting Results

- `!!` **Error**: Will cause bugs or severe performance problems — fix immediately
- `!~` **Warning**: Causes unnecessary re-renders in practice — fix in hot paths
- `~~` **Info**: Code smell, may cause issues at scale (only with `--strict`)

## Fix Priority

1. **Context providers** — one fix eliminates re-renders across entire subtrees
2. **useEffect bugs** — async effects and infinite loops are correctness issues
3. **Inline creations in lists** — `items.map(item => <Child config={{ ... }} />)` is N re-renders
4. **Expensive operations** — `JSON.parse` and `.sort()` in frequently-rendered components
5. **Component complexity** — architectural improvements for long-term maintainability

## Detailed Rules

Read [references/rerender-rules.md](references/rerender-rules.md) for full documentation on each detection rule, including React 19 considerations and when NOT to optimize.
