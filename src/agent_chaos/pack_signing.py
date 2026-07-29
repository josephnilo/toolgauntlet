from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

from .exceptions import PackVerificationError
from .utils import ensure_suite_yaml_path


def _suite_root(path: str | Path) -> Path:
    suite_yaml = ensure_suite_yaml_path(path)
    root = suite_yaml.parent.resolve()
    if not suite_yaml.exists():
        raise PackVerificationError(f"suite.yaml not found at: {suite_yaml}")
    return root


def _iter_pack_files(root: Path, signature_filename: str) -> list[Path]:
    files: list[Path] = []
    for candidate in sorted(root.rglob("*")):
        if not candidate.is_file():
            continue
        name = candidate.name
        if name == signature_filename:
            continue
        if name.startswith(".") or name == ".DS_Store":
            continue
        if "__pycache__" in candidate.parts:
            continue
        files.append(candidate)
    return files


def compute_pack_signature(
    *,
    suite_path: str | Path,
    secret_key: str,
    signature_filename: str = "pack.sig",
) -> str:
    if not secret_key:
        raise PackVerificationError("secret_key is required")
    root = _suite_root(suite_path)

    digest = hmac.new(secret_key.encode("utf-8"), digestmod=hashlib.sha256)
    for file_path in _iter_pack_files(root, signature_filename=signature_filename):
        rel = file_path.relative_to(root).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        with file_path.open("rb") as handle:
            while True:
                chunk = handle.read(65536)
                if not chunk:
                    break
                digest.update(chunk)
        digest.update(b"\0")

    return digest.hexdigest()


def sign_pack(
    *,
    suite_path: str | Path,
    secret_key: str,
    signature_filename: str = "pack.sig",
    output_path: str | Path | None = None,
) -> tuple[Path, str]:
    root = _suite_root(suite_path)
    signature = compute_pack_signature(
        suite_path=root,
        secret_key=secret_key,
        signature_filename=signature_filename,
    )
    destination = Path(output_path).resolve() if output_path else (root / signature_filename)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(signature + "\n", encoding="utf-8")
    return destination, signature


def verify_pack(
    *,
    suite_path: str | Path,
    secret_key: str,
    signature_filename: str = "pack.sig",
    signature_path: str | Path | None = None,
) -> bool:
    root = _suite_root(suite_path)
    target = Path(signature_path).resolve() if signature_path else (root / signature_filename)
    if not target.exists():
        raise PackVerificationError(f"signature file not found: {target}")

    expected = target.read_text(encoding="utf-8").strip().lower()
    if not expected:
        raise PackVerificationError(f"signature file is empty: {target}")

    actual = compute_pack_signature(
        suite_path=root,
        secret_key=secret_key,
        signature_filename=signature_filename,
    ).lower()
    if not hmac.compare_digest(expected, actual):
        raise PackVerificationError("signature mismatch")
    return True

