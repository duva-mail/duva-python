"""Régénère `src/duva/_generated/models.py` depuis la spécification OpenAPI de Duva (générée dans
le dépôt `duva`, `app/api_spec.py`) : `datamodel-code-generator`, jamais édité à la main. Le
fichier vit SOUS `src/duva/` (et non à la racine) car il est importé au moment de l'exécution par
`duva.client` : hors du paquet, il ne serait pas installé avec la bibliothèque.

    uv run --extra dev python scripts/generate.py             # https://duva.ca/openapi.json
    uv run --extra dev python scripts/generate.py --local      # ../duva/docs/openapi.json
"""

import re
import subprocess
import sys
from pathlib import Path

# datamodel-code-generator quirk (`--collapse-root-models` + `--use-annotated` together): for an
# optional, `maxLength`-constrained string field it still falls back to a `RootModel[str]`
# wrapper, AND drops the `| None` from BOTH the generic parameter and the root field's own
# annotation while keeping the `= None` default — invalid under mypy strict, first as `str =
# None`, then (once only the field is patched) as an LSP violation against `RootModel[str]`'s own
# `root: str`. Only 3 schemas hit this today (attachment content_type/content_id, message
# reply_to), but the fix is pattern-based so it keeps working if the next OpenAPI change adds
# another one.
_ROOT_MODEL_MISSING_OPTIONAL = re.compile(
    r"(RootModel\[)(\w+)(\]\):\n\s*root: Annotated\[.+?\])(\s*=\s*None)"
)


def _fix_root_model_optionality(text: str) -> str:
    return _ROOT_MODEL_MISSING_OPTIONAL.sub(r"\1\2 | None\3 | None\4", text)


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "src" / "duva" / "_generated" / "models.py"
LIVE_URL = "https://duva.ca/openapi.json"
LOCAL_PATH = str((ROOT.parent / "duva" / "docs" / "openapi.json").resolve())

# --collapse-root-models : évite des classes RootModel[str] pour un simple champ optionnel.
# --enum-field-as-literal all : `status: Literal["queued", ...]` plutôt que des énumérations
#   numérotées (Status, Status1, Status2...) quand plusieurs schémas ont un champ du même nom.
ARGS = [
    "--input-file-type", "openapi",
    "--output-model-type", "pydantic_v2.BaseModel",
    "--target-python-version", "3.10",
    "--use-schema-description", "--use-field-description",
    "--disable-timestamp",
    "--use-standard-collections", "--use-union-operator",
    "--collapse-root-models",
    "--enum-field-as-literal", "all",
    # `constr(...)`/`conint(...)` used directly as a type annotation is invalid under mypy strict
    # (PEP 484 forbids a function call in annotation position); `--use-annotated` emits
    # `Annotated[str, StringConstraints(...)]` instead, which mypy accepts.
    "--use-annotated",
]  # fmt: skip


def main(argv: list[str]) -> int:
    source = LOCAL_PATH if "--local" in argv else LIVE_URL
    OUTPUT.parent.mkdir(exist_ok=True)
    subprocess.run(
        ["uvx", "--from", "datamodel-code-generator", "datamodel-codegen",
         "--input", source, "--output", str(OUTPUT), *ARGS],
        check=True,
    )  # fmt: skip
    OUTPUT.write_text(_fix_root_model_optionality(OUTPUT.read_text()))
    # datamodel-code-generator writes single-quoted, unformatted code: normalize it so the
    # generated file matches the project's own style and doesn't fail `ruff format --check`.
    subprocess.run(["uv", "run", "ruff", "format", str(OUTPUT)], cwd=ROOT, check=True)
    print(f"{OUTPUT.relative_to(ROOT)} written from {source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
