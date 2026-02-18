# React Re-render Rules Reference

## Why Re-renders Matter

React re-renders the entire subtree when a component's state or props change. Unnecessary re-renders
cause jank, wasted CPU, and poor UX — especially on low-end devices or large component trees.

## Detection Categories

### 1. Inline Creations (re-render triggers)

Every render creates a **new reference** for inline objects, arrays, and functions.
Children receiving these as props will ALWAYS re-render, even with React.memo.

| Pattern | Problem | Fix |
|---------|---------|-----|
| `prop={{ key: val }}` | New object every render | `useMemo` or extract to const |
| `prop={[1, 2, 3]}` | New array every render | `useMemo` or extract to const |
| `onClick={() => fn()}` | New function every render | `useCallback` |
| `date={new Date()}` | New instance every render | `useMemo` or extract |

**Why it matters**: React uses `Object.is()` for prop comparison. `{} !== {}` always, so
even identical-looking objects trigger re-renders.

**Exception**: If the child component does NOT use `React.memo` and does NOT implement
`shouldComponentUpdate`, inline props don't cause *additional* re-renders — the child
re-renders anyway when the parent does. However, fixing inline props is still best practice
because it enables memoization when you need it later.

### 2. Context Provider Issues

```jsx
// BAD: Every parent render creates new value object
<ThemeContext.Provider value={{ theme, toggle }}>

// GOOD: Memoized value only changes when deps change
const value = useMemo(() => ({ theme, toggle }), [theme, toggle]);
<ThemeContext.Provider value={value}>
```

**Impact**: ALL consumers of the context re-render when the provider value changes reference.
This can cascade through hundreds of components.

### 3. useEffect Anti-patterns

| Pattern | Severity | Problem |
|---------|----------|---------|
| `useEffect(async () => ...)` | Error | Returns Promise, not cleanup fn |
| `useEffect(() => { setState(...) })` (no deps) | Error | Infinite loop |
| `useEffect` with 3+ setState calls | Warning | Cascading re-renders |

**async useEffect**: React expects the callback to return either nothing or a cleanup function.
An async function returns a Promise, which React ignores — meaning cleanup never runs.

**setState without deps**: Without a dependency array, the effect runs after EVERY render.
If it calls setState, that triggers another render, which triggers the effect again = infinite loop.

### 4. Expensive Render Operations

Operations that run on every render without memoization:

| Operation | Why expensive | Fix |
|-----------|--------------|-----|
| `JSON.parse()/stringify()` | O(n) serialization | `useMemo` |
| `.sort()` | O(n log n) + mutates | `useMemo` with spread |
| `.filter().map()` | Double iteration | `useMemo` the filter |
| `new RegExp()` | Compilation cost | Module scope or `useMemo` |

### 5. Component Complexity

| Signal | Threshold | Why it matters |
|--------|-----------|----------------|
| Component > 250 lines | Warning | Hard to optimize, too many concerns |
| Component > 150 lines | Info | Approaching complexity ceiling |
| Props > 10 | Warning | API too complex, likely doing too much |
| Props > 7 | Info | Consider simplification |
| useState > 5 | Warning | State explosion, use useReducer |
| useState > 3 | Info | Consider grouping related state |
| `{...props}` spreading | Info | Forwards unknown re-render triggers |

## Severity Levels

- **Error** (`!!`): Will cause bugs or severe performance problems (infinite loops, broken cleanup)
- **Warning** (`!~`): Causes unnecessary re-renders in practice
- **Info** (`~~`): Code smell that may cause issues as the codebase grows (only shown with `--strict`)

## When NOT to Optimize

Not every inline creation needs fixing. Consider:

1. **Leaf components**: If a component has no children, inline props won't cascade
2. **Rarely-rendered components**: Modal that opens once doesn't need memoization
3. **React Compiler**: If using React 19's compiler, it auto-memoizes — many of these become unnecessary
4. **Premature optimization**: Profile first. Only optimize what you can measure as slow

## React 19 Considerations

React 19's compiler automatically memoizes components and hooks. If your project uses the React Compiler:
- Inline object/array/function warnings become less critical
- Context value memoization is still important (compiler doesn't optimize providers)
- useEffect anti-patterns remain bugs regardless of compiler
- Component complexity issues remain architectural concerns
