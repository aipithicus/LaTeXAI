"""One bounded math vocabulary round trip, independently observed by native TeX.

Generic execution produces the pre-layout math tree. Projection uses a closed
vocabulary and a trusted canonical prelude, never the paper's redefinitions.
This qualifies selected noad structure, not layout or arbitrary package support.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

from ..engine.content_builder import ContentBuilder
from ..engine.causal import digest
from .probe_runner import run_probe, write_json
from .tex_trace import differences

INIT = (r"\catcode123=1 \catcode125=2 \catcode35=6 \catcode36=3 "
        r'\catcode94=7 \catcode95=8 \newlinechar=10 \mathcode43="202B ')
TRUSTED = r"\def\frac#1#2{{#1\over#2}}"
FONTS = (r"\font\rm=cmr10 \font\mi=cmmi10 \font\sy=cmsy10 \font\ex=cmex10 "
         r"\textfont0=\rm \scriptfont0=\rm \scriptscriptfont0=\rm "
         r"\textfont1=\mi \scriptfont1=\mi \scriptscriptfont1=\mi "
         r"\textfont2=\sy \scriptfont2=\sy \scriptscriptfont2=\sy "
         r"\textfont3=\ex \scriptfont3=\ex \scriptscriptfont3=\ex ")
CLASSES = {name: i for i, name in enumerate(("ord", "op", "bin", "rel", "open", "close", "punct", "inner"))}
VOCABULARY = {"frac", "mathchar", "mathord", "mathop", "mathbin", "mathrel", "mathopen", "mathclose",
              "mathpunct", "mathinner", "over", "atop", "above", "limits", "nolimits", "displaylimits"}


class ProjectionError(ValueError):
    pass


def project(node):
    def sequence(nodes):
        return "".join(emit(part) for part in nodes)
    def fraction(part, *, named=False):
        if len(part.children) != 2 or [n.kind for n in part.children] != ["numerator", "denominator"]:
            raise ProjectionError("Malformed fraction fields")
        numerator, denominator = [sequence(n.children) for n in part.children]
        thickness = part.get("thickness")
        if named and thickness == "default":
            return r"\frac{" + numerator + "}{" + denominator + "}"
        separator = r"\over " if thickness == "default" else r"\atop " if thickness == 0 else (
            r"\above " + str(thickness) + "sp " if type(thickness) is int else None)
        if separator is None:
            raise ProjectionError("Unknown fraction thickness")
        return numerator + separator + denominator
    def emit(part):
        if part.kind in {"math", "math_list"}:
            return sequence(part.children)
        if part.kind == "fraction":
            return fraction(part)
        if part.kind != "noad" or part.get("class_") not in CLASSES:
            raise ProjectionError("Vocabulary does not cover node " + part.kind)
        if set(dict(part.attributes)) - {"class_", "limits"}:
            raise ProjectionError("Unprojected atom attributes")
        nucleus = [n for n in part.children if n.kind not in {"sup", "sub"}]
        if len(nucleus) != 1:
            raise ProjectionError("Atom needs one nucleus")
        nucleus = nucleus[0]
        cls = part.get("class_")
        if nucleus.kind == "math_character":
            family, code = nucleus.get("family"), nucleus.get("code")
            if type(family) is not int or type(code) is not int or not 0 <= family <= 15 or not 0 <= code <= 255:
                raise ProjectionError("Invalid math character")
            if cls == "inner":
                body = r"\mathinner{\mathchar" + str(family * 256 + code) + " }"
            else:
                body = r'\mathchar"' + f"{CLASSES[cls] * 4096 + family * 256 + code:04X}" + " "
        elif nucleus.kind == "math_list":
            if cls == "ord" and len(nucleus.children) == 1 and nucleus.children[0].kind == "fraction" and nucleus.children[0].get("thickness") == "default":
                body = fraction(nucleus.children[0], named=True)
            else:
                body = ("{" if cls == "ord" else "\\math" + cls + "{") + sequence(nucleus.children) + "}"
        else:
            raise ProjectionError("Vocabulary does not cover nucleus " + nucleus.kind)
        limits = part.get("limits")
        if limits is not None:
            if cls != "op" or limits not in {"limits", "nolimits", "displaylimits"}:
                raise ProjectionError("Unsupported limits modifier")
            body += "\\" + limits + " "
        for role, marker in (("sup", "^"), ("sub", "_")):
            fields = [n for n in part.children if n.kind == role]
            if len(fields) > 1:
                raise ProjectionError("Duplicate script field")
            if fields:
                body += marker + "{" + sequence(fields[0].children) + "}"
        return body
    result = emit(node)
    if set(re.findall(r"\\([A-Za-z]+)", result)) - VOCABULARY:
        raise ProjectionError("Projection escaped its declared vocabulary")
    return result


def extract(preamble, formula, *, record=True):
    source = INIT + preamble + "\n" + r"\setbox0=\hbox{$" + formula + r"$}\copy0\end"
    build = ContentBuilder({"main.tex": source}, record=record).build("main.tex")
    if build.status != "completed":
        raise ProjectionError("Execution boundary: " + json.dumps(build.boundary))
    box = build.context.state_cells.values["box:0"].value
    formulae = [n for n in box.children if n.kind == "math"]
    if len(formulae) != 1:
        raise ProjectionError("Round trip requires exactly one inline formula")
    return build, formulae[0]


def list_observation(trace):
    maths = [item for item in trace["lists"] if item["mode"].startswith("math mode")]
    if trace["issues"] or len(maths) != 1:
        raise ValueError("Incomplete or ambiguous native math observation")
    def node(part):
        return {"path": part["path"], "text": part["text"], "children": [node(c) for c in part["children"]]}
    return [node(n) for n in maths[0]["nodes"]]


def qualify(preamble, formula, executable, output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    result = {"schema": "pytexml-vocabulary-roundtrip/1", "status": "incomplete",
              "vocabulary": sorted(VOCABULARY), "trusted_prelude_sha256": hashlib.sha256((INIT + FONTS + TRUSTED).encode()).hexdigest(),
              "scope": "One executed formula projected to a closed math vocabulary; selected native pre-layout noad structure and fallback diagnostics."}
    try:
        build, math = extract(preamble, formula)
        canonical = project(math)
        write_json(output / "execution.json", build.record)
        write_json(output / "content.json", math.as_dict())
        (output / "canonical.tex").write_text(canonical + "\n", encoding="ascii", newline="\n")
        result.update(canonical=canonical, authored_formula=formula, authored_preamble_sha256=hashlib.sha256(preamble.encode()).hexdigest())
        trusted, _ = extract(TRUSTED, r"\frac{1}{2}")
        guard = next(e["operands"]["definition"] for e in trusted.record["events"] if e["operation"] == "macro_expand" and e["operands"]["name"] == "frac")
        result["vocabulary_guards"] = [{"event": e["id"], "name": "frac", "trusted_meaning": digest(guard),
                                        "observed_meaning": digest(e["operands"]["definition"]),
                                        "matches": e["operands"]["definition"] == guard}
                                       for e in build.record["events"] if e["operation"] == "macro_expand" and e["operands"]["name"] == "frac"]
        observations, warnings, dependencies = {}, {}, {}
        plan = {"checkpoints": ["before", "after"], "fields": [{"id": "count", "kind": "count", "index": 20}]}
        for name, definitions, body in (("original", preamble, formula), ("canonical", TRUSTED, canonical)):
            source = output / (name + "-source")
            source.mkdir()
            text = (INIT + FONTS + r"\input pytexml-observe.tex " + definitions + "\n"
                    + r"\showboxdepth=1000 \showboxbreadth=1000 \tracinglostchars=2 "
                    + r"\PyTeXMLCheckpoint{before}\tracingmacros=2 "
                    + r"\setbox0=\hbox{$" + body + r"\showlists$}\tracingmacros=0 "
                    + r"\PyTeXMLCheckpoint{after}\end" + "\n")
            (source / "main.tex").write_text(text, encoding="utf-8", newline="\n")
            run = run_probe(source, "main.tex", executable, output / name, plan, mode="initex", expected_ok=1,
                            initial_state="trusted-initex-math-fonts-v1", parse_trace=True)
            if run["status"] != "complete":
                raise ValueError("Native observation incomplete: " + name)
            folder = output / name / "probed/pass-1"
            trace = json.loads((folder / "trace.json").read_text(encoding="utf-8"))
            observations[name] = list_observation(trace)
            log = (folder / "main.log").read_text(encoding="utf-8")
            warnings[name] = [line for line in log.splitlines() if re.search(r"Missing character:|Font shape .*undefined|font.*substitut", line, re.I)]
            closure = json.loads((folder / "files.json").read_text(encoding="utf-8"))
            dependencies[name] = {r["path"]: r["sha256"] for r in closure["records"]
                                  if r["kind"] == "INPUT" and Path(r["path"]).suffix in {".tfm", ".fmt", ".cnf"}}
        diff = differences(observations["original"], observations["canonical"])
        result.update(observations=observations, differences=diff, native_fallbacks=warnings,
                      ambient_inputs=dependencies, ambient_inputs_equal=dependencies["original"] == dependencies["canonical"],
                      causal_gaps=build.record["gaps"])
        result["status"] = ("incomplete" if not result["ambient_inputs_equal"] or build.record["gaps"] else
                            "native_fallback" if any(warnings.values()) else "mismatch" if diff else "matched")
    except (ValueError, OSError) as error:
        result["error"] = str(error)
    write_json(output / "receipt.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=Path, help="JSON containing preamble and formula")
    parser.add_argument("--pdftex", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    case = json.loads(args.case.read_text(encoding="utf-8"))
    result = qualify(case["preamble"], case["formula"], args.pdftex, args.output)
    print(json.dumps({"status": result["status"], "canonical": result.get("canonical"), "error": result.get("error")}))
    return 0 if result["status"] == "matched" else 1


if __name__ == "__main__":
    raise SystemExit(main())
