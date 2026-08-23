#!/usr/bin/env python3
"""Safely verify and archive a retired paper working directory."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


SOURCE_SUFFIXES = {".tex", ".bib", ".sty", ".cls", ".bst", ".cfg", ".def"}
ASSET_SUFFIXES = {".png", ".jpg", ".jpeg", ".svg", ".pdf", ".eps"}
SPECIAL_SOURCE_NAMES = {"Makefile", "latexmkrc", ".latexmkrc"}
BUILD_SUFFIXES = (
    ".aux",
    ".log",
    ".out",
    ".fls",
    ".fdb_latexmk",
    ".synctex.gz",
    ".bbl",
    ".blg",
)
SKIP_DIRS = {"output", "build", "_build", "_report_assets_build", "__pycache__"}
SKIP_PREFIXES = ("PAPER_CLAIM_AUDIT", "PAPER_IMPROVEMENT_")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
WARN_TOTAL_BYTES = 50 * 1024 * 1024
MAX_FILE_BYTES = 100 * 1024 * 1024


class RetireError(RuntimeError):
    pass


def validate_date(value: str) -> str:
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise RetireError("date 必须是有效的 YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise RetireError("date 必须是有效的 YYYY-MM-DD")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inside(root: Path, candidate: Path) -> Path:
    root = root.resolve()
    candidate = candidate.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise RetireError(f"路径越出项目根: {candidate}") from exc
    return candidate


def root_path(root: Path, value: str) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    return inside(root, candidate)


def git_metadata(root: Path) -> tuple[str, bool]:
    if not (root / ".git").exists():
        return "none", True
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=False
    )
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=root, text=True, capture_output=True, check=False
    )
    return (commit.stdout.strip() or "none", bool(status.stdout.strip()))


def git_paths(root: Path, *args: str) -> set[str]:
    if not (root / ".git").exists():
        return set()
    result = subprocess.run(
        ["git", "ls-files", "-z", *args],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return {item.decode() for item in result.stdout.split(b"\0") if item}


def git_file_states(root: Path, paths: list[Path]) -> dict[str, str]:
    if not (root / ".git").exists():
        return {str(path.relative_to(root)): "outside-git" for path in paths}
    tracked = git_paths(root)
    ignored = git_paths(root, "--others", "--ignored", "--exclude-standard")
    untracked = git_paths(root, "--others", "--exclude-standard")
    states: dict[str, str] = {}
    for path in paths:
        rel = str(path.relative_to(root))
        if rel in tracked:
            state = "tracked"
        elif rel in ignored:
            state = "ignored"
        elif rel in untracked:
            state = "untracked"
        else:
            state = "unknown"
        states[rel] = state
    return states


def ignored_future_paths(root: Path, paths: list[Path]) -> list[str]:
    if not (root / ".git").exists() or not paths:
        return []
    relpaths = [str(path.relative_to(root)) for path in paths]
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin"],
        cwd=root,
        input="\n".join(relpaths) + "\n",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return sorted(line for line in result.stdout.splitlines() if line)


def skip_reason(source: Path, path: Path, submitted_pdf: Path | None) -> str | None:
    rel = path.relative_to(source)
    if path.is_symlink():
        return "symlink"
    if any(part in SKIP_DIRS for part in rel.parts[:-1]):
        return "generated-directory"
    if path.name.startswith(SKIP_PREFIXES):
        return "review-state"
    if path.name == "compile.log" or path.name.endswith(BUILD_SUFFIXES):
        return "build-artifact"
    if submitted_pdf is not None and path.resolve() == submitted_pdf.resolve():
        return "submitted-pdf"
    if path.parent == source and path.suffix.lower() == ".pdf":
        return "top-level-pdf"
    return None


def inventory(source: Path, submitted_pdf: Path | None, extras: list[str]) -> tuple[list[Path], dict[str, str]]:
    included: list[Path] = []
    excluded: dict[str, str] = {}
    explicit: set[Path] = set()
    for item in extras:
        path = Path(item)
        if path.is_absolute() or ".." in path.parts or str(path) in {"", "."}:
            raise RetireError(f"include 必须是 source 内的相对文件: {item}")
        explicit.add(path)
    for path in sorted(source.rglob("*")):
        if not path.is_file() and not path.is_symlink():
            continue
        rel = path.relative_to(source)
        reason = skip_reason(source, path, submitted_pdf)
        if rel in explicit and reason not in {"symlink", "generated-directory", "submitted-pdf"}:
            included.append(path)
            continue
        if reason:
            excluded[str(rel)] = reason
            continue
        suffix = path.suffix.lower()
        is_asset = suffix in ASSET_SUFFIXES and not (suffix == ".pdf" and path.parent == source)
        if suffix in SOURCE_SUFFIXES or is_asset or path.name in SPECIAL_SOURCE_NAMES:
            included.append(path)
        else:
            excluded[str(rel)] = "not-required-source"
    missing_extras = sorted(str(path) for path in explicit if not (source / path).is_file())
    if missing_extras:
        raise RetireError(f"显式 include 不存在: {', '.join(missing_extras)}")
    return included, excluded


def size_summary(paths: list[Path]) -> tuple[int, list[Path]]:
    too_large = [path for path in paths if path.stat().st_size >= MAX_FILE_BYTES]
    return sum(path.stat().st_size for path in paths), too_large


def remove_compile_outputs(stage_source: Path, original_relpaths: set[Path]) -> None:
    for path in sorted(stage_source.rglob("*"), reverse=True):
        if path.is_file() and path.relative_to(stage_source) not in original_relpaths:
            path.unlink()
        elif path.is_dir() and not any(path.iterdir()):
            path.rmdir()


def verify_latex(stage_source: Path, main_tex: str, allow_unverified: bool) -> str:
    main_rel = Path(main_tex)
    if main_rel.is_absolute() or ".." in main_rel.parts or str(main_rel) in {"", "."}:
        raise RetireError("main-tex 必须是 source 内的相对文件")
    main_path = inside(stage_source, stage_source / main_rel)
    if not main_path.exists():
        if any(stage_source.rglob("*.tex")):
            raise RetireError(f"主 TeX 不存在: {main_tex}；请使用 --main-tex 指定")
        return "not-applicable"
    latexmk = shutil.which("latexmk")
    if latexmk is None:
        if allow_unverified:
            return "not-run"
        raise RetireError("检测到 LaTeX 源码但找不到 latexmk；确认后使用 --allow-unverified")
    original_relpaths = {path.relative_to(stage_source) for path in stage_source.rglob("*") if path.is_file()}
    result = subprocess.run(
        [latexmk, "-pdf", "-interaction=nonstopmode", "-halt-on-error", str(main_rel)],
        cwd=stage_source,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode != 0:
        tail = "\n".join(result.stdout.splitlines()[-20:])
        raise RetireError(f"隔离源码编译失败:\n{tail}")
    remove_compile_outputs(stage_source, original_relpaths)
    return "passed"


def write_readme(
    path: Path,
    slug: str,
    retired: str,
    source_rel: str,
    commit: str,
    dirty: bool,
    verification: str,
) -> None:
    path.write_text(
        "\n".join(
            [
                "---",
                "status: archived",
                f"slug: {slug}",
                f"retired: {retired}",
                f"source_path: {json.dumps(source_rel, ensure_ascii=False)}",
                f"source_commit: {commit}",
                f"working_tree_dirty: {str(dirty).lower()}",
                f"verification: {verification}",
                "---",
                "",
                f"# {slug}",
                "",
                "这是不可变的正式提交快照，不是实验数字、方法或论文叙事的权威来源。",
                "",
            ]
        ),
        encoding="utf-8",
    )


def write_checksums(package: Path) -> None:
    files = [package / "submitted.pdf"] + sorted((package / "source").rglob("*"))
    files = [path for path in files if path.is_file()]
    lines = [f"{sha256(path)}  {path.relative_to(package)}" for path in files]
    (package / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")


def verify_checksums(package: Path) -> list[str]:
    checksum_file = package / "SHA256SUMS"
    if not checksum_file.is_file():
        return ["SHA256SUMS missing"]
    failures: list[str] = []
    if not (package / "README.md").is_file():
        failures.append("README.md missing")
    if not (package / "submitted.pdf").is_file():
        failures.append("submitted.pdf missing")
    if not (package / "source").is_dir():
        failures.append("source directory missing")
    listed: set[str] = set()
    for line in checksum_file.read_text(encoding="utf-8").splitlines():
        expected, sep, raw_rel = line.partition("  ")
        if not sep:
            failures.append(f"invalid checksum line: {line}")
            continue
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            failures.append(f"invalid checksum: {raw_rel}")
            continue
        if raw_rel in listed:
            failures.append(f"duplicate checksum: {raw_rel}")
            continue
        listed.add(raw_rel)
        target = inside(package, package / raw_rel)
        if not target.is_file():
            failures.append(f"missing: {raw_rel}")
        elif sha256(target) != expected:
            failures.append(f"checksum mismatch: {raw_rel}")
    payload = {
        str(path.relative_to(package))
        for path in package.rglob("*")
        if path.is_file() and path.name not in {"README.md", "SHA256SUMS"}
    }
    for raw_rel in sorted(payload - listed):
        failures.append(f"uncovered package file: {raw_rel}")
    if "submitted.pdf" not in listed:
        failures.append("submitted.pdf checksum missing")
    return failures


def plan_retire(args: argparse.Namespace) -> dict[str, object]:
    root = Path(args.root).resolve()
    validate_date(args.date)
    source = root_path(root, args.source)
    if not source.is_dir():
        raise RetireError(f"来源目录不存在: {source}")
    if not SLUG_RE.fullmatch(args.slug):
        raise RetireError("slug 必须是 lowercase-kebab-case")
    pdf = root_path(root, args.pdf or str(Path(args.source) / "main.pdf"))
    if not pdf.is_file() or pdf.suffix.lower() != ".pdf":
        raise RetireError(f"最终 PDF 不存在: {pdf}")
    with pdf.open("rb") as handle:
        pdf_header = handle.read(5)
    if pdf_header != b"%PDF-":
        raise RetireError(f"最终文件没有 PDF 标头: {pdf}")
    destination = inside(root, root / "archive" / "docs" / "paper" / f"{args.date}-{args.slug}")
    if destination.exists():
        raise RetireError(f"目标已存在，拒绝覆盖: {destination}")
    included, excluded = inventory(source, pdf, args.include)
    if not included:
        raise RetireError("未找到可归档源码；请检查 source 或使用 --include 指定必要文件")
    total, too_large = size_summary([pdf, *included])
    if too_large:
        raise RetireError("单文件达到 100 MiB: " + ", ".join(str(path) for path in too_large))
    commit, dirty = git_metadata(root)
    file_states = git_file_states(root, [pdf, *included])
    future_files = [
        destination / "README.md",
        destination / "submitted.pdf",
        destination / "SHA256SUMS",
        *(destination / "source" / path.relative_to(source) for path in included),
    ]
    ignored_destination = ignored_future_paths(root, future_files)
    if ignored_destination:
        raise RetireError("归档目标会被 Git 忽略: " + ", ".join(ignored_destination))
    return {
        "root": root,
        "source": source,
        "source_rel": str(source.relative_to(root)),
        "pdf": pdf,
        "destination": destination,
        "included": included,
        "excluded": excluded,
        "total_bytes": total,
        "size_warning": total > WARN_TOTAL_BYTES,
        "source_commit": commit,
        "working_tree_dirty": dirty,
        "file_states": file_states,
    }


def display_plan(plan: dict[str, object]) -> None:
    root = plan["root"]
    source = plan["source"]
    print(f"source: {source.relative_to(root)}")
    pdf_rel = str(plan["pdf"].relative_to(root))
    print(f"pdf: {pdf_rel} [{plan['file_states'][pdf_rel]}]")
    print(f"destination: {plan['destination'].relative_to(root)}")
    print(f"source commit: {plan['source_commit']}")
    print(f"working tree dirty: {str(plan['working_tree_dirty']).lower()}")
    print(f"total bytes: {plan['total_bytes']}")
    if plan["size_warning"]:
        print("warning: package exceeds 50 MiB")
    print("included source:")
    for path in plan["included"]:
        root_rel = str(path.relative_to(root))
        print(f"- {path.relative_to(source)} [{plan['file_states'][root_rel]}]")
    print("excluded:")
    for path, reason in plan["excluded"].items():
        print(f"- {path}: {reason}")


def apply_retire(args: argparse.Namespace, plan: dict[str, object]) -> None:
    destination: Path = plan["destination"]
    parent = destination.parent
    parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{args.slug}-", dir=parent))
    try:
        shutil.copy2(plan["pdf"], stage / "submitted.pdf")
        stage_source = stage / "source"
        stage_source.mkdir()
        for path in plan["included"]:
            rel = path.relative_to(plan["source"])
            target = stage_source / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        verification = verify_latex(stage_source, args.main_tex, args.allow_unverified)
        write_readme(
            stage / "README.md",
            args.slug,
            args.date,
            plan["source_rel"],
            plan["source_commit"],
            plan["working_tree_dirty"],
            verification,
        )
        write_checksums(stage)
        failures = verify_checksums(stage)
        if failures:
            raise RetireError("归档后校验失败: " + "; ".join(failures))
        os.replace(stage, destination)
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        raise
    print(f"verification: {verification}")
    print(f"retired: {destination.relative_to(plan['root'])}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--source", default="paper")
    parser.add_argument("--include", action="append", default=[])
    parser.add_argument("--slug", required=True)
    parser.add_argument("--pdf")
    parser.add_argument("--main-tex", default="main.tex")
    parser.add_argument("--date", default=dt.date.today().isoformat())
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--allow-unverified", action="store_true")

    args = parser.parse_args()
    try:
        plan = plan_retire(args)
        display_plan(plan)
        print("active source is not deleted")
        if not args.apply:
            print("dry-run: no files changed; rerun with --apply after confirmation")
            return 0
        apply_retire(args, plan)
        return 0
    except RetireError as exc:
        print(f"error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
