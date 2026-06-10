# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Generate and verify the layered CMake target dependency diagram.

Single source of truth for ``cmake/cmake-target-layers.md``. The diagram is derived from
*live* CMake: CMake emits its own dependency graph via ``cmake --graphviz`` (the only export
that includes INTERFACE libraries and that draws **direct** edges only, never the transitive
closure). We parse that graph, lay the targets out in topological layers -- each target sits
exactly one layer above its deepest direct dependency, so no two targets in a layer depend on
each other and a target only ever points at lower layers -- and render Markdown.

Typical uses::

    # CI: configure with the shared preset emits build/cmake-target-graph.dot, then:
    python3 scripts/cmake_target_layers.py --dot build/cmake-target-graph.dot --check
    python3 scripts/cmake_target_layers.py --dot build/cmake-target-graph.dot --out diagram.md

    # Local bootstrap from an already-configured build dir:
    python3 scripts/cmake_target_layers.py --build-dir build --write

``--check`` compares only the marker-delimited generated region, so the SPDX header (kept
current by the copyright-year hook) never registers as drift. On drift it prints a bannered
mismatch message, the unified diff, and how to refresh the committed copy, then exits
non-zero.
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DOC_RELPATH = "cmake/cmake-target-layers.md"
DEFAULT_GRAPH_NAME = "cmake-target-graph.dot"
PRESET_LABEL = "ci-linux"  # the configure preset the committed diagram represents

BEGIN_MARKER = "<!-- BEGIN GENERATED: cmake-target-layers (do not edit by hand) -->"
END_MARKER = "<!-- END GENERATED: cmake-target-layers -->"

# CMake graphviz node shapes -> human-readable target type (see the dot file's Legend).
SHAPE_TO_TYPE = {
    "egg": "Executable",
    "octagon": "Static library",
    "doubleoctagon": "Shared library",
    "tripleoctagon": "Module library",
    "pentagon": "Interface library",
    "hexagon": "Object library",
    "septagon": "Unknown library",
    "box": "Custom target",
    "house": "Custom target",
}

# Target types hidden from the diagram (still present in the cmake build, but not real
# CMake targets — these are raw `-l<lib>` links that CMake cannot resolve to a defined target).
# CMake's graphviz marks them with shape `septagon` ("Unknown library").
HIDDEN_TYPES: frozenset[str] = frozenset({"Unknown library"})

# Individual targets hidden from the diagram. These are programmatically injected by CMake
# helper functions (e.g. pybind11_add_module) and do not represent a user-authored dependency
# choice — they are internal plumbing of third-party build machinery.
HIDDEN_TARGETS: frozenset[str] = frozenset(
    {
        "pybind11::lto",  # LTO helper auto-injected by pybind11_add_module; not a project dep
    }
)

# CMake graphviz edge styles -> link visibility.
STYLE_TO_KIND = {"solid": "public", "dashed": "interface", "dotted": "private"}

# Stable priority when the same (consumer -> dependency) edge appears with several styles.
KIND_PRIORITY = {"public": 0, "interface": 1, "private": 2}

# Patterns that declare a first-party target somewhere in the repo's CMake files.
TARGET_DECL_RE = re.compile(
    r"\b(?:add_library|add_executable|add_custom_target"
    r"|pybind11_add_module|nanobind_add_module)\s*\(\s*([A-Za-z0-9_]+)"
)
_DECL_KEYWORDS = {
    "IMPORTED",
    "INTERFACE",
    "STATIC",
    "SHARED",
    "MODULE",
    "OBJECT",
}

# Parse a node:  "node12" [ label = "name\n(alias)", shape = octagon ];
NODE_RE = re.compile(
    r'"(node\d+)"\s*\[\s*label\s*=\s*"([^"]*)"\s*,\s*shape\s*=\s*(\w+)\s*\]'
)
# Parse an edge:  "node3" -> "node8" [ style = dashed ]   (style optional -> solid)
EDGE_RE = re.compile(
    r'"(node\d+)"\s*->\s*"(node\d+)"(?:\s*\[\s*style\s*=\s*(\w+)\s*\])?'
)


# ---------------------------------------------------------------------------
# Repo helpers
# ---------------------------------------------------------------------------


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def first_party_targets(root: Path) -> set[str]:
    """Names of targets declared in the repo's own CMake files (build/ and _deps excluded).

    Used only to colour first-party vs third-party nodes; every node is still rendered.
    """
    names: set[str] = set()
    for path in root.rglob("*"):
        if path.name == "CMakeLists.txt" or path.suffix == ".cmake":
            names |= _scan_decls(path)
    return names


def _scan_decls(path: Path) -> set[str]:
    parts = path.parts
    if "build" in parts or "_deps" in parts:
        return set()
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return set()
    return {
        m.group(1)
        for m in TARGET_DECL_RE.finditer(text)
        if m.group(1) not in _DECL_KEYWORDS
    }


# ---------------------------------------------------------------------------
# Graph extraction
# ---------------------------------------------------------------------------


def emit_graphviz(
    *, build_dir: Path | None, preset: str | None, extra: list[str]
) -> str:
    """Run CMake to (re)emit the graphviz dot and return its content."""
    root = repo_root()
    tmp = None
    if preset:
        tmp = tempfile.TemporaryDirectory(prefix="cmake-target-layers-")
        dot = Path(tmp.name) / DEFAULT_GRAPH_NAME
        cmd = ["cmake", "--preset", preset, *extra, f"--graphviz={dot}"]
    else:
        assert build_dir is not None
        dot = build_dir / DEFAULT_GRAPH_NAME
        # Reuse the dir's cached configuration; -B alone reconfigures with cached values.
        cmd = ["cmake", "-B", str(build_dir), *extra, f"--graphviz={dot}"]
    try:
        proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
        if proc.returncode != 0:
            sys.stderr.write(proc.stdout)
            sys.stderr.write(proc.stderr)
            raise SystemExit(
                f"cmake failed to emit graphviz (exit {proc.returncode}): {' '.join(cmd)}"
            )
        if not dot.exists():
            raise SystemExit(f"cmake did not produce {dot}")
        return dot.read_text(encoding="utf-8")
    finally:
        if tmp is not None:
            tmp.cleanup()


class Graph:
    """Direct-dependency graph of CMake targets."""

    def __init__(
        self,
        types: dict[str, str],
        edges: dict[tuple[str, str], str],
        node_aliases: dict[str, set[str]] | None = None,
    ):
        self.types = types  # target name -> type label
        self.edges = edges  # (consumer, dependency) -> link kind
        self.node_aliases = (
            node_aliases or {}
        )  # canonical name -> set of CMake alias forms
        self.deps: dict[str, set[str]] = {n: set() for n in types}
        for consumer, dependency in edges:
            self.deps[consumer].add(dependency)


def parse_dot(text: str) -> Graph:
    id_to_name: dict[str, str] = {}
    types: dict[str, str] = {}
    node_aliases: dict[str, set[str]] = {}
    for node_id, label, shape in NODE_RE.findall(text):
        name = label.split("\\n", 1)[0].strip()
        id_to_name[node_id] = name
        types[name] = SHAPE_TO_TYPE.get(shape, "Unknown library")
        # Labels carry CMake alias forms in parentheses, e.g. "Catch2WithMain\n(Catch2::Catch2WithMain)"
        # or multiple aliases: "openxr_loader\n(OpenXR::OpenXR)\n(OpenXR::openxr_loader)".
        aliases = re.findall(r"\(([^)]+)\)", label)
        if aliases:
            node_aliases[name] = set(aliases)

    # Drop nodes that carry no architectural information:
    #   - system pseudo-targets (raw -l<lib> links, shape=septagon)
    #   - individually denylisted build-machinery targets (e.g. pybind11::lto)
    hidden = {name for name, t in types.items() if t in HIDDEN_TYPES} | HIDDEN_TARGETS
    hidden &= set(types)  # only drop what's actually present
    for name in hidden:
        del types[name]
    node_aliases = {n: a for n, a in node_aliases.items() if n not in hidden}

    edges: dict[tuple[str, str], str] = {}
    for src, dst, style in EDGE_RE.findall(text):
        if src not in id_to_name or dst not in id_to_name:
            continue
        consumer, dependency = id_to_name[src], id_to_name[dst]
        if consumer == dependency:
            continue  # drop spurious self-loops (e.g. test exes)
        if consumer in hidden or dependency in hidden:
            continue  # drop edges to/from hidden system pseudo-targets
        kind = STYLE_TO_KIND.get(style or "solid", "public")
        key = (consumer, dependency)
        if key not in edges or KIND_PRIORITY[kind] < KIND_PRIORITY[edges[key]]:
            edges[key] = kind
    return Graph(types, edges, node_aliases)


def _transitive_reach(
    node: str, deps: dict[str, set[str]], cache: dict[str, set[str]]
) -> set[str]:
    """All nodes reachable from node at distance >= 1 (node itself excluded)."""
    if node in cache:
        return cache[node]
    result: set[str] = set()
    for child in deps.get(node, set()):
        result.add(child)
        result |= _transitive_reach(child, deps, cache)
    cache[node] = result
    return result


def transitive_reduction(graph: Graph) -> Graph:
    """Remove edges implied by transitivity, keeping only the minimal spanning set.

    Edge (u, v) is dropped when v is already reachable from u via a path of
    length >= 2 through other declared dependencies.  The resulting graph has
    the same reachability as the original, fewer arrows, and the same layer
    assignment (since redundant edges are always shorter paths).
    """
    cache: dict[str, set[str]] = {}
    for node in graph.types:
        _transitive_reach(node, graph.deps, cache)

    redundant: set[tuple[str, str]] = set()
    for u in graph.deps:
        # Nodes reachable from u at distance >= 2 (via each direct dep's own reach)
        indirect: set[str] = set()
        for v in graph.deps[u]:
            indirect |= cache[v]
        for v in graph.deps[u]:
            if v in indirect:
                redundant.add((u, v))

    new_edges = {k: kv for k, kv in graph.edges.items() if k not in redundant}
    return Graph(graph.types, new_edges, graph.node_aliases)


def trim_indirect_third_party(graph: Graph, first_party: set[str]) -> Graph:
    """Keep only third-party nodes that a first-party target directly links.

    Third-party packages expose a top-level API surface (e.g. ``pybind11::module``,
    ``Catch2WithMain``, ``openxr_loader``). Their internal sub-targets
    (``pybind11::pybind11``, ``pybind11::python_headers``, ``Catch2``, …) are
    implementation details of those packages, not module-boundary information.
    Hiding them keeps the diagram focused on the project's own dependency choices.
    """
    directly_used = {
        dep
        for (consumer, dep) in graph.edges
        if consumer in first_party and dep not in first_party
    }
    visible = (first_party | directly_used) & set(graph.types)
    new_types = {n: t for n, t in graph.types.items() if n in visible}
    new_edges = {
        (c, d): k for (c, d), k in graph.edges.items() if c in visible and d in visible
    }
    new_aliases = {n: a for n, a in graph.node_aliases.items() if n in visible}
    return Graph(new_types, new_edges, new_aliases)


def compute_layers(graph: Graph) -> dict[str, int]:
    """Longest path from each node to a leaf. Guarantees layer(consumer) > layer(dependency)."""
    layer: dict[str, int] = {}

    def visit(node: str, path: list[str]) -> int:
        if node in layer:
            return layer[node]
        if node in path:
            cycle = path[path.index(node) :] + [node]
            raise SystemExit("dependency cycle detected: " + " -> ".join(cycle))
        path.append(node)
        depth = 0
        for dep in sorted(graph.deps[node]):
            depth = max(depth, 1 + visit(dep, path))
        path.pop()
        layer[node] = depth
        return depth

    for node in sorted(graph.types):
        visit(node, [])

    # The layering invariant the whole diagram rests on.
    for consumer, dependency in graph.edges:
        if layer[consumer] <= layer[dependency]:
            raise SystemExit(
                f"layering invariant violated: {consumer} (L{layer[consumer]}) -> "
                f"{dependency} (L{layer[dependency]})"
            )
    return layer


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _barycenter_order(
    by_layer: dict[int, list[str]],
    deps: dict[str, set[str]],
    max_iter: int = 4,
) -> dict[int, list[str]]:
    """Reorder nodes within each layer using the barycenter crossing-minimisation heuristic.

    Alternates downward sweeps (each layer reordered by the positions of its consumers in
    the layer above) and upward sweeps (reordered by the positions of its dependencies in
    the layer below). Nodes with no neighbours in the fixed adjacent layer are sorted last
    in stable order so they do not displace constrained nodes.
    """
    max_lyr = max(by_layer)

    # consumers[v] = nodes in higher layers that directly depend on v
    consumers: dict[str, set[str]] = {
        n: set() for nodes in by_layer.values() for n in nodes
    }
    for u, vs in deps.items():
        if u not in consumers:
            continue
        for v in vs:
            if v in consumers:
                consumers[v].add(u)

    order: dict[int, list[str]] = {lyr: list(nodes) for lyr, nodes in by_layer.items()}

    def _reorder(
        lyr: int, nbr_map: dict[str, set[str]], fixed_pos: dict[str, float]
    ) -> None:
        def key(item: tuple[int, str]) -> tuple[float, int]:
            i, node = item
            nbrs = [fixed_pos[nb] for nb in nbr_map[node] if nb in fixed_pos]
            return (sum(nbrs) / len(nbrs) if nbrs else float("inf"), i)

        order[lyr] = [n for _, n in sorted(enumerate(order[lyr]), key=key)]

    for _ in range(max_iter):
        # Downward sweep: top → bottom, fix upper layer, reorder by consumer positions
        for lyr in range(max_lyr - 1, -1, -1):
            if lyr + 1 not in order:
                continue
            pos = {n: float(i) for i, n in enumerate(order[lyr + 1])}
            _reorder(lyr, consumers, pos)
        # Upward sweep: bottom → top, fix lower layer, reorder by dependency positions
        for lyr in range(1, max_lyr + 1):
            if lyr - 1 not in order:
                continue
            pos = {n: float(i) for i, n in enumerate(order[lyr - 1])}
            _reorder(lyr, deps, pos)

    return order


def _display_name(canonical: str, aliases: set[str]) -> str:
    """Return the best human-readable name for a node.

    Prefers the CMake alias over the raw graphviz name (e.g. ``OpenXR::headers``
    over ``headers``). When a node has multiple aliases, picks the one whose
    suffix after ``::`` most closely matches the canonical name so that e.g.
    ``OpenXR::openxr_loader`` is chosen over ``OpenXR::OpenXR``.
    """
    if not aliases:
        return canonical
    if len(aliases) == 1:
        return next(iter(aliases))
    norm = canonical.lower().replace("-", "_")

    def score(alias: str) -> tuple[int, str]:
        suffix = alias.split("::")[-1].lower().replace("-", "_")
        return (0 if suffix == norm else 1, alias)

    return min(aliases, key=score)


def _mermaid_node(node_id: str, label: str, ctype: str) -> str:
    safe = label.replace('"', "#quot;")
    if ctype == "Executable":
        return f'{node_id}(["{safe}"])'
    if ctype == "Interface library":
        return f'{node_id}{{{{"{safe}"}}}}'
    if ctype == "Module library":
        return f'{node_id}[["{safe}"]]'
    if ctype == "Object library":
        return f'{node_id}[/"{safe}"/]'
    return f'{node_id}["{safe}"]'  # static/shared/unknown libs, custom targets


def render_generated_block(
    graph: Graph, layer: dict[str, int], first_party: set[str]
) -> str:
    names = sorted(graph.types)
    disp = {
        name: _display_name(name, graph.node_aliases.get(name, set())) for name in names
    }
    # Use the sanitized display name as the node ID so that adding or removing
    # a target only touches lines that reference that target, not every edge.
    raw_ids = [re.sub(r"[^A-Za-z0-9_]", "_", disp[name]) for name in names]
    if len(set(raw_ids)) != len(raw_ids):
        raise SystemExit("sanitized Mermaid node IDs collide; check target names")
    node_id = dict(zip(names, raw_ids))
    max_layer = max(layer.values()) if layer else 0
    n_edges = len(graph.edges)
    by_layer: dict[int, list[str]] = {}
    for n in names:
        by_layer.setdefault(layer[n], []).append(n)
    by_layer = _barycenter_order(by_layer, graph.deps)

    lines: list[str] = [BEGIN_MARKER, ""]
    lines.extend(
        [
            "## Overview",
            "",
            f"- **{len(names)}** targets, **{n_edges}** direct dependencies, **{max_layer + 1}** layers.",
            f"- Generated from configure preset `{PRESET_LABEL}` (see `CMakePresets.json`).",
            "- Layer *k* contains targets whose deepest direct-dependency chain is *k* long; "
            "every dependency points to a strictly lower layer, so there are **no edges within a "
            "layer**. This is a layered DAG (shared foundations create diamonds), not a strict tree.",
            "- Raw system library links (`-ldl`, `-lstdc++fs`, …) are omitted: CMake records "
            "them as *Unknown library* nodes (not real CMake targets) and they carry no "
            "structural information about module boundaries.",
            "- Third-party nodes that no first-party target links directly are omitted (e.g. "
            "`pybind11::pybind11`, `Catch2`, `ProjectConfig`). Only the top-level API surface "
            "that this project actually links against is shown; internal sub-targets of "
            "third-party packages are implementation details of those packages. "
            "A small set of individually-named build-machinery targets (see `HIDDEN_TARGETS` in "
            "the generator script) are also omitted — these are programmatically injected by "
            "CMake helper functions and do not represent user-authored dependency choices.",
            "- **Transitive reduction applied:** edges that are already implied by a longer "
            "dependency path are omitted (e.g. if A → B → C, the redundant A → C edge is "
            "dropped). The graph has the same reachability as the raw CMake declarations; "
            "see the `CMakeLists.txt` files for every declared `target_link_libraries` call.",
            "",
            "### Legend",
            "",
            "- Node shape: `([executable])`, `[static / shared library]`, "
            "`[[module library]]`, `{{interface library}}`, `[/object library/]`, "
            "`[custom target]`.",
            "- Node colour: blue = first-party target, grey = third-party dependency.",
            "- Arrow `A --> B` means **A depends on B** (B is in a lower layer).",
            "- Link visibility (`public` / `private` / `interface`) is listed in the "
            "per-target table below.",
            "",
        ]
    )

    layer_rows = [
        (lyr, by_layer[lyr]) for lyr in range(max_layer, -1, -1) if lyr in by_layer
    ]

    # --- Mermaid diagram -----------------------------------------------------
    lines.append("## Layered dependency graph")
    lines.append("")
    lines.append("```mermaid")
    lines.append(
        '%%{init: {"flowchart": {"rankSpacing": 120}, "themeVariables": {"fontSize": "24pt"}} }%%'
    )
    lines.append("flowchart TD")
    for lyr, members in layer_rows:
        if lyr == max_layer:
            title = f"Layer {lyr} - top (consumers)"
        elif lyr == 0:
            title = f"Layer {lyr} - foundation"
        else:
            title = f"Layer {lyr}"
        lines.append(f'  subgraph LYR{lyr}["{title}"]')
        for name in members:
            lines.append(
                "    " + _mermaid_node(node_id[name], disp[name], graph.types[name])
            )
        lines.append("  end")
    # Edges, sorted for determinism.
    for consumer, dependency in sorted(graph.edges):
        lines.append(f"  {node_id[consumer]} --> {node_id[dependency]}")
    # Styling.
    fp = sorted(node_id[n] for n in names if n in first_party)
    tp = sorted(node_id[n] for n in names if n not in first_party)
    lines.append("  classDef firstparty fill:#d9e8fb,stroke:#3b73b9,color:#0b2545;")
    lines.append("  classDef thirdparty fill:#ededed,stroke:#9a9a9a,color:#333333;")
    if fp:
        lines.append("  class " + ",".join(fp) + " firstparty")
    if tp:
        lines.append("  class " + ",".join(tp) + " thirdparty")
    lines.append("```")
    lines.append("")

    # --- Layer roster --------------------------------------------------------
    lines.append("## Layers")
    lines.append("")
    lines.append("| Layer | Targets |")
    lines.append("| ----: | ------- |")
    for lyr, members in layer_rows:
        lines.append(f"| {lyr} | {', '.join(f'`{disp[m]}`' for m in members)} |")
    lines.append("")

    # --- Per-target direct dependencies (the precise diff surface) -----------
    lines.append("## Direct dependencies by target")
    lines.append("")
    lines.append("| Target | Type | Origin | Layer | Direct dependencies |")
    lines.append("| ------ | ---- | ------ | ----: | ------------------- |")
    for name in names:
        origin = "first-party" if name in first_party else "third-party"
        deps = sorted(graph.deps[name])
        if deps:
            dep_text = ", ".join(
                f"`{disp[d]}` ({graph.edges[(name, d)]})" for d in deps
            )
        else:
            dep_text = "_(none)_"
        lines.append(
            f"| `{disp[name]}` | {graph.types[name]} | {origin} | {layer[name]} | {dep_text} |"
        )

    lines.append("")
    lines.append(END_MARKER)
    return "\n".join(lines)


def build_full_document(block: str) -> str:
    year = datetime.now().year
    preamble = [
        f"<!-- SPDX-FileCopyrightText: Copyright (c) {year} NVIDIA CORPORATION & AFFILIATES."
        " All rights reserved. -->",
        "<!-- SPDX-License-Identifier: Apache-2.0 -->",
        "",
        "# CMake target dependency layers",
        "",
        "Layered, **direct-dependency** view of this project's CMake targets, derived from live",
        "CMake (`cmake --graphviz`). Targets are sorted into topological layers: a target sits one",
        "layer above its deepest direct dependency, so no two targets in a layer depend on each",
        "other and dependencies always point to lower layers.",
        "",
        "> **Auto-generated -- do not edit the region between the markers below.**",
        "> Regenerate by replacing this file with the `cmake-target-layers` artifact from the",
        "> *Verify CMake target layers* CI run, or locally with the full CI toolchain via",
        "> `python3 scripts/cmake_target_layers.py --preset ci-linux --write`.",
        "> CI fails when the committed diagram drifts from what CMake reports.",
        "",
    ]
    return "\n".join(preamble) + "\n" + block + "\n"


def extract_block(text: str) -> str | None:
    start = text.find(BEGIN_MARKER)
    end = text.find(END_MARKER)
    if start == -1 or end == -1 or end < start:
        return None
    return text[start : end + len(END_MARKER)]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def load_graph(args: argparse.Namespace) -> Graph:
    """Parse the graphviz dot (emitting it via cmake if needed). Returns the raw graph."""
    if args.dot:
        dot_path = Path(args.dot)
        if not dot_path.exists():
            raise SystemExit(f"--dot path does not exist: {dot_path}")
        dot_text = dot_path.read_text(encoding="utf-8")
    else:
        build_dir = Path(args.build_dir).resolve() if args.build_dir else None
        dot_text = emit_graphviz(
            build_dir=build_dir, preset=args.preset, extra=args.cmake_arg
        )
    graph = parse_dot(dot_text)
    if not graph.types:
        raise SystemExit("no targets parsed from dot input")
    return graph


def _write_document(path: Path, document: str, graph: Graph) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document, encoding="utf-8")
    print(f"wrote {path} ({len(graph.types)} targets, {len(graph.edges)} edges)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--dot", help="read an existing graphviz dot emitted by cmake --graphviz"
    )
    src.add_argument(
        "--build-dir", help="reuse an already-configured build dir to emit the graph"
    )
    src.add_argument(
        "--preset", help="configure with this CMake preset to emit the graph"
    )
    parser.add_argument(
        "--cmake-arg",
        action="append",
        default=[],
        help="extra arg passed to cmake (repeatable), e.g. --cmake-arg=-DENABLE_X=OFF",
    )
    out = parser.add_mutually_exclusive_group(required=True)
    out.add_argument(
        "--check", action="store_true", help="fail if the committed diagram is stale"
    )
    out.add_argument("--write", action="store_true", help=f"write {DOC_RELPATH}")
    out.add_argument(
        "--out", help="write the full document to this path (e.g. for a CI artifact)"
    )
    args = parser.parse_args(argv)

    first_party = first_party_targets(repo_root())
    graph = transitive_reduction(
        trim_indirect_third_party(load_graph(args), first_party)
    )
    layer = compute_layers(graph)
    block = render_generated_block(graph, layer, first_party)
    doc_path = repo_root() / DOC_RELPATH

    if args.write or args.out:
        _write_document(
            Path(args.out) if args.out else doc_path, build_full_document(block), graph
        )
        return 0

    # --check
    if not doc_path.exists():
        print(
            f"ERROR: {DOC_RELPATH} is missing; run the generator to create it.",
            file=sys.stderr,
        )
        return 1
    committed = extract_block(doc_path.read_text(encoding="utf-8"))
    if committed is None:
        print(
            f"ERROR: {DOC_RELPATH} has no generated region markers; regenerate it.",
            file=sys.stderr,
        )
        return 1
    if committed == block:
        print(f"OK: {DOC_RELPATH} is up to date ({len(graph.types)} targets).")
        return 0

    import difflib

    diff = difflib.unified_diff(
        committed.splitlines(),
        block.splitlines(),
        fromfile=f"{DOC_RELPATH} (committed)",
        tofile="live cmake graph",
        lineterm="",
    )
    message = [
        f"ERROR: {DOC_RELPATH} is out of date with live CMake.",
        "",
        "Refresh it by downloading the `cmake-target-layers` artifact from the "
        "'Verify CMake target layers' CI run and committing it",
        "(or run `python3 scripts/cmake_target_layers.py --preset ci-linux --write` "
        "with the full CI toolchain).",
    ]
    banner = "=" * 78
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(
            f"::error::{DOC_RELPATH} is out of date with live CMake. Refresh it from "
            "the `cmake-target-layers` artifact or run the generator locally."
        )
    print(
        "\n".join(
            [
                "",
                banner,
                *message,
                banner,
                "",
                "BEGIN GENERATED REGION DIFF",
                *diff,
                "END GENERATED REGION DIFF",
            ]
        )
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
