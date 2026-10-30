"""Build pre-layout content from an explicit source inventory and optional format."""
from .format_builder import FormatBuilder


class ContentBuilder(FormatBuilder):
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
    args = parser.parse_args()
    config = json.loads(args.inventory.read_text(encoding="utf-8"))
    base = args.inventory.resolve().parent
    builder = ContentBuilder({name: (base / path).read_bytes().decode("utf-8") for name, path in config["sources"].items()},
        metrics={name: (base / path).read_bytes() for name, path in config.get("metrics", {}).items()},
        initialization=config.get("initialization"), profile=config.get("profile", "pdftex"), budget=args.budget)
    restored = builder.restore(args.restore.read_text(encoding="utf-8")) if args.restore else None
    result = builder.build(args.entry or config["entry"], restored=restored)
    payload = {"receipt": result.receipt(), "content": result.content}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"status": result.status, "boundary": result.boundary, "output": str(args.output)}))
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
