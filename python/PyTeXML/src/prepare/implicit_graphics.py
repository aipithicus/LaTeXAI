"""Existing heuristic inventory of latent graphics; no rendering or interpretation."""
from __future__ import annotations
from pathlib import Path
import re
from typing import List, Optional, Tuple
from ..source_io import SourceDecodingError, open_source
from .manifest import ImplicitGraphicInfo


FLOAT_ENVIRONMENTS = {"figure", "figure*", "wrapfigure", "sidewaysfigure", "SCfigure", "marginfigure"}


MATH_ENVIRONMENTS = {
    "equation", "equation*", "align", "align*", "gather", "gather*",
    "multline", "multline*", "split", "displaymath", "math", "subequations"
}


COMMUTATIVE_DIAGRAM_ENVS = {
    "tikzcd": "tikz-cd",
    "CD": "amscd",
    "xymatrix": "xy",
    "diagram": "diagrams",
    "xy": "xy",
    "pbdiagram": "pb-diagram",
}


DRAWING_ENVS = {
    "tikzpicture": "tikz",
    "picture": "latex",
    "pgfpicture": "pgf",
    "pspicture": "pstricks",
    "asy": "asymptote",
    "gnuplot": "gnuplottex",
}


SPECIALIZED_CANVAS_ENVS = {
    "circuitikz": "circuitikz",
    "forest": "forest",
    "bytefield": "bytefield",
    "chemfig": "chemfig",
    "blochsphere": "blochsphere",
    "feynman": "feynmf",
    "feynhand": "feynhand",
}


IMAGE_INCLUDE_RE = re.compile(
    r"\\(?:includegraphics|pgfimage|pgfdeclareimage|epsfig|psfig|includesvg)\b"
)


ARROW_TOKEN_RE = re.compile(
    r"\\(?:arrow|ar\b|xrightarrow|xleftarrow|twoheadrightarrow|hookrightarrow|dashrightarrow|mapsto|to\b)|@[><VA]{3}"
)


def detect_implicit_graphics(p_dir: Path, active_tex_files: List[str]) -> List[ImplicitGraphicInfo]:
    """
    Ascertains an upfront inventory of implicit rendered graphics (assetless figures,
    programmatic vector drawings, commutative diagrams, and morphism grids)
    without relying solely on fragile package hardcoding.
    """
    results: List[ImplicitGraphicInfo] = []

    for rel_tex in active_tex_files:
        tex_path = (p_dir / rel_tex).resolve()
        if not tex_path.is_file():
            continue

        try:
            with open_source(tex_path) as f:
                lines = f.readlines()
        except SourceDecodingError:
            raise
        except Exception:
            continue

        env_stack: List[Tuple[str, int]] = []
        local_float_envs = set(FLOAT_ENVIRONMENTS)
        in_definition: bool = False
        def_brace_depth: int = 0
        def_env_name: Optional[str] = None

        in_float: bool = False
        float_start_line: int = 0
        float_env: Optional[str] = None
        float_has_image: bool = False
        float_inner_envs: List[str] = []
        float_lines: List[str] = []

        math_depth: int = 0

        for idx, line in enumerate(lines, start=1):
            clean_line = re.sub(r"(?<!\\)%.*", "", line).strip()
            if not clean_line:
                continue

            # Track \newenvironment / \renewenvironment templates
            new_env_m = re.search(r"\\(?:newenvironment|renewenvironment)\*?\s*\{([^}]+)\}", clean_line)
            if new_env_m:
                in_definition = True
                def_env_name = new_env_m.group(1).strip()
                def_brace_depth = 0

            if in_definition:
                def_brace_depth += clean_line.count("{") - clean_line.count("}")
                if r"\begin{figure" in clean_line and def_env_name:
                    local_float_envs.add(def_env_name)
                if def_brace_depth <= 0:
                    in_definition = False
                    def_env_name = None
                continue

            dollar_count = len(re.findall(r"(?<!\\)\$", clean_line))
            if dollar_count % 2 != 0:
                math_depth = 1 if math_depth == 0 else 0

            is_math_mode = (
                math_depth > 0 or
                any(env in MATH_ENVIRONMENTS for env, _ in env_stack) or
                r"\[" in clean_line or
                r"\(" in clean_line
            )

            # Check \begin{...}
            begins = re.findall(r"\\begin\{([^}]+)\}", clean_line)
            for env in begins:
                env_stack.append((env, idx))
                if env in local_float_envs and not in_float:
                    in_float = True
                    float_start_line = idx
                    float_env = env
                    float_has_image = False
                    float_inner_envs = []
                    float_lines = [clean_line]
                elif in_float:
                    float_inner_envs.append(env)


                if env in COMMUTATIVE_DIAGRAM_ENVS:
                    results.append(ImplicitGraphicInfo(
                        kind=env,
                        category="COMMUTATIVE_DIAGRAM",
                        file=rel_tex,
                        line_number=idx,
                        is_floating=in_float,
                        is_math_mode=is_math_mode,
                        preview=clean_line[:120],
                        environment_name=env,
                        package_hint=COMMUTATIVE_DIAGRAM_ENVS[env]
                    ))
                elif env in DRAWING_ENVS:
                    results.append(ImplicitGraphicInfo(
                        kind=env,
                        category="PROGRAMMATIC_DRAWING",
                        file=rel_tex,
                        line_number=idx,
                        is_floating=in_float,
                        is_math_mode=is_math_mode,
                        preview=clean_line[:120],
                        environment_name=env,
                        package_hint=DRAWING_ENVS[env]
                    ))
                elif env in SPECIALIZED_CANVAS_ENVS:
                    results.append(ImplicitGraphicInfo(
                        kind=env,
                        category="SPECIALIZED_CANVAS",
                        file=rel_tex,
                        line_number=idx,
                        is_floating=in_float,
                        is_math_mode=is_math_mode,
                        preview=clean_line[:120],
                        environment_name=env,
                        package_hint=SPECIALIZED_CANVAS_ENVS[env]
                    ))

            if in_float:
                float_lines.append(clean_line)
                if IMAGE_INCLUDE_RE.search(clean_line):
                    float_has_image = True

            # Standalone macros like \xymatrix{...} or \tikz{...}
            if r"\xymatrix" in clean_line and not any(env == "xymatrix" for env, _ in env_stack):
                results.append(ImplicitGraphicInfo(
                    kind="xymatrix",
                    category="COMMUTATIVE_DIAGRAM",
                    file=rel_tex,
                    line_number=idx,
                    is_floating=in_float,
                    is_math_mode=True,
                    preview=clean_line[:120],
                    environment_name="xymatrix",
                    package_hint="xy"
                ))

            if re.search(r"\\tikz\s*(?:\[[^\]]*\])?\s*\{", clean_line):
                results.append(ImplicitGraphicInfo(
                    kind="tikz_inline",
                    category="PROGRAMMATIC_DRAWING",
                    file=rel_tex,
                    line_number=idx,
                    is_floating=in_float,
                    is_math_mode=is_math_mode,
                    preview=clean_line[:120],
                    environment_name="tikz",
                    package_hint="tikz"
                ))

            # Morphism grid heuristic: table cells with arrow morphisms in math mode
            if is_math_mode and "&" in clean_line and r"\\" in clean_line and ARROW_TOKEN_RE.search(clean_line):
                if not any(r.file == rel_tex and r.line_number == idx for r in results):
                    results.append(ImplicitGraphicInfo(
                        kind="morphism_grid",
                        category="COMMUTATIVE_DIAGRAM",
                        file=rel_tex,
                        line_number=idx,
                        is_floating=in_float,
                        is_math_mode=True,
                        preview=clean_line[:120],
                        environment_name="math_grid",
                        package_hint="amscd/tikz-cd/xy"
                    ))

            # Check \end{...}
            ends = re.findall(r"\\end\{([^}]+)\}", clean_line)
            for env in ends:
                if in_float and env == float_env:
                    if not float_has_image:
                        non_trivial_inner = [e for e in float_inner_envs if e not in ("center", "flushleft", "flushright", "minipage")]
                        inner_env_name = non_trivial_inner[0] if non_trivial_inner else "code_block"
                        preview_str = " ".join(l for l in float_lines if l)[:140]
                        results.append(ImplicitGraphicInfo(
                            kind="assetless_float",
                            category="ASSETLESS_FLOAT",
                            file=rel_tex,
                            line_number=float_start_line,
                            is_floating=True,
                            is_math_mode=False,
                            preview=preview_str,
                            environment_name=inner_env_name,
                            package_hint=DRAWING_ENVS.get(inner_env_name) or COMMUTATIVE_DIAGRAM_ENVS.get(inner_env_name)
                        ))
                    in_float = False
                    float_env = None
                    float_has_image = False
                    float_inner_envs = []
                    float_lines = []

                for s_idx in range(len(env_stack) - 1, -1, -1):
                    if env_stack[s_idx][0] == env:
                        env_stack.pop(s_idx)
                        break

    return results
