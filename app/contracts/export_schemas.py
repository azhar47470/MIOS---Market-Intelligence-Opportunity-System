import json
from pathlib import Path

from app.contracts.registry import export_contract_schemas


def export_schemas(output_dir: str | Path = "contracts/schemas") -> None:
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    for name, schema in export_contract_schemas().items():
        (path / f"{name}.schema.json").write_text(
            json.dumps(schema, indent=2, sort_keys=True),
            encoding="utf-8",
        )


if __name__ == "__main__":
    export_schemas()
