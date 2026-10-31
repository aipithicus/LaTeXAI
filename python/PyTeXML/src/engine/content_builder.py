"""Build pre-layout content from an explicit source inventory and optional format."""
from .format_builder import FormatBuilder


class ContentBuilder(FormatBuilder):
    def __init__(self, *args, semantic_drivers=None, insertion_roles=None, box_roles=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.semantic_drivers = dict(semantic_drivers or {})
        self.insertion_roles = {int(k): v for k, v in (insertion_roles or {}).items()}
        self.box_roles = {int(k): v for k, v in (box_roles or {}).items()}
        if any(not 0 <= k <= 254 or v != "footnote" for k, v in self.insertion_roles.items()):
            raise ValueError("Insertion roles require an explicit class in 0..254 and the role footnote")
        if any(not 0 <= k <= 32767 or v != "float" for k, v in self.box_roles.items()):
            raise ValueError("Box roles require an explicit register in 0..32767 and the role float")

    def content_state(self, span):
        from .content import ContentState
        return ContentState(span, insertion_roles=self.insertion_roles, box_roles=self.box_roles)

    def adapt_input(self, host, name, span):
        if name not in self.semantic_drivers:
            return False
        from .semantic_drivers import install
        install(host, self.semantic_drivers[name], self.sources[name].text, span)
        return True

    def build(self, root, *, restored=None):
        return super().build(root, restored=restored, require_dump=False, construct_content=True)


def main():
    import argparse
    import json
    from pathlib import Path
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=Path)
    parser.add_argument("--entry")
    parser.add_argument("--restore", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--budget", type=int, default=10000)
    parser.add_argument("--record", type=Path, help="Write an opt-in causal execution record")
    args = parser.parse_args()
    config = json.loads(args.inventory.read_text(encoding="utf-8"))
    base = args.inventory.resolve().parent
    builder = ContentBuilder({name: (base / path).read_bytes().decode("utf-8") for name, path in config["sources"].items()},
        metrics={name: (base / path).read_bytes() for name, path in config.get("metrics", {}).items()},
        initialization=config.get("initialization"), profile=config.get("profile", "pdftex"), budget=args.budget,
        semantic_drivers=config.get("semantic_drivers"), insertion_roles=config.get("insertion_roles"),
        box_roles=config.get("box_roles"), record=args.record is not None)
    restored = builder.restore(args.restore.read_text(encoding="utf-8")) if args.restore else None
    result = builder.build(args.entry or config["entry"], restored=restored)
    payload = {"receipt": result.receipt(), "content": result.content}
    if args.record is not None:
        args.record.parent.mkdir(parents=True, exist_ok=True)
        args.record.write_text(json.dumps(result.record, indent=2) + "\n", encoding="utf-8", newline="\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"status": result.status, "boundary": result.boundary, "output": str(args.output)}))
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
