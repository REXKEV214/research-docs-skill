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
import stat
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
VERIFICATION_SCHEMA_VERSION = 1
REQUIRED_README_HEADINGS = (
    "项目简介",
    "版本定位",
    "归档内容",
    "编译与复现",
    "验证",
    "与其他版本的关系",
    "权威来源",
)


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


def input_file(value: str, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise RetireError(f"{label}不存在: {path}")
    return path


def validate_readme_body(path: Path) -> str:
    try:
        body = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise RetireError(f"无法读取 README 正文: {path}") from exc
    if not re.match(r"^# [^#\n].*", body):
        raise RetireError("README 正文必须以一级标题开头")
    lines = body.splitlines()
    headings: list[tuple[str, int]] = []
    fence: tuple[str, int] | None = None
    for index, line in enumerate(lines):
        if fence is None:
            opening = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
            if opening is not None:
                marker = opening.group(1)
                info = opening.group(2)
                if marker[0] == "~" or "`" not in info:
                    fence = (marker[0], len(marker))
                    continue
        else:
            closing = re.match(r"^ {0,3}(`+|~+)[ \t]*$", line)
            if (
                closing is not None
                and closing.group(1)[0] == fence[0]
                and len(closing.group(1)) >= fence[1]
            ):
                fence = None
            continue
        if fence is None and line.startswith("## ") and not line.startswith("### "):
            headings.append((line[3:].strip(), index))
    required_counts = {
        heading: sum(name == heading for name, _ in headings)
        for heading in REQUIRED_README_HEADINGS
    }
    missing = [heading for heading, count in required_counts.items() if count == 0]
    if missing:
        raise RetireError("README 正文缺少章节: " + ", ".join(missing))
    duplicates = [heading for heading, count in required_counts.items() if count > 1]
    if duplicates:
        raise RetireError("README 正文章节重复: " + ", ".join(duplicates))
    actual_order = [
        heading for heading, _ in headings if heading in REQUIRED_README_HEADINGS
    ]
    if actual_order != list(REQUIRED_README_HEADINGS):
        raise RetireError("README 正文章节顺序不符合归档 schema")
    for heading, line_index in headings:
        if heading not in REQUIRED_README_HEADINGS:
            continue
        next_h2 = next(
            (candidate for _, candidate in headings if candidate > line_index),
            len(lines),
        )
        if not "\n".join(lines[line_index + 1 : next_h2]).strip():
            raise RetireError(f"README 正文章节内容为空: {heading}")
    return body


def validate_verification_report(
    path: Path, source: Path, submitted_pdf: Path, allow_unverified: bool
) -> dict[str, object]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RetireError(f"验证报告不是有效 JSON: {path}") from exc
    if not isinstance(report, dict):
        raise RetireError("验证报告顶层必须是 JSON object")
    if report.get("schema_version") != VERIFICATION_SCHEMA_VERSION:
        raise RetireError(
            f"验证报告 schema_version 必须是 {VERIFICATION_SCHEMA_VERSION}"
        )
    status = report.get("status")
    if status == "failed":
        raise RetireError("验证报告状态为 failed，拒绝归档")
    if status == "not-run" and not allow_unverified:
        raise RetireError("验证报告状态为 not-run；确认后使用 --allow-unverified")
    if status not in {"passed", "not-run"}:
        raise RetireError("验证报告 status 必须是 passed、not-run 或 failed")
    method = report.get("method")
    if not isinstance(method, str) or not SLUG_RE.fullmatch(method):
        raise RetireError("验证报告 method 必须是 lowercase-kebab-case")
    expected_sha = report.get("submitted_pdf_sha256")
    if not isinstance(expected_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
        raise RetireError("验证报告 submitted_pdf_sha256 必须是 SHA-256")
    if sha256(submitted_pdf) != expected_sha:
        raise RetireError("验证报告的提交 PDF SHA-256 与当前文件不一致")
    build_command = report.get("build_command")
    if not isinstance(build_command, list) or not build_command or not all(
        isinstance(item, str) and item.strip() for item in build_command
    ):
        raise RetireError("验证报告 build_command 必须是非空字符串数组")
    build_cwd = report.get("build_cwd")
    if not isinstance(build_cwd, str) or not build_cwd.strip():
        raise RetireError("验证报告 build_cwd 必须是 source 内的相对目录")
    build_rel = Path(build_cwd)
    if build_rel.is_absolute() or ".." in build_rel.parts or str(build_rel) == "":
        raise RetireError("验证报告 build_cwd 必须是 source 内的相对目录")
    build_dir = inside(source, source / build_rel)
    if not build_dir.is_dir():
        raise RetireError(f"验证报告 build_cwd 不存在: {build_cwd}")
    checks = report.get("checks")
    if not isinstance(checks, list) or not checks:
        raise RetireError("验证报告 checks 必须是非空数组")
    for check in checks:
        if not isinstance(check, dict):
            raise RetireError("验证报告 checks 的每一项必须是 object")
        if not isinstance(check.get("name"), str) or not check["name"].strip():
            raise RetireError("验证报告 check.name 必须是非空字符串")
        check_status = check.get("status")
        if check_status not in {"passed", "not-run"}:
            raise RetireError("验证报告 check.status 必须是 passed 或 not-run")
        if status == "passed" and check_status != "passed":
            raise RetireError("passed 验证报告不能包含未执行的检查")
        if not isinstance(check.get("detail"), str) or not check["detail"].strip():
            raise RetireError("验证报告 check.detail 必须是非空字符串")
    return report


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


def directory_open_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )


def open_directory_no_symlinks(path: Path) -> int:
    """Open an absolute directory path without following any component symlink."""
    if not path.is_absolute():
        raise RetireError(f"安全目录路径必须是绝对路径: {path}")
    current_fd = os.open(os.sep, directory_open_flags())
    try:
        for component in path.parts[1:]:
            next_fd = os.open(component, directory_open_flags(), dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except OSError as exc:
        os.close(current_fd)
        raise RetireError(f"目录路径包含符号链接或无法安全打开: {path}") from exc


def open_project_directory(root: Path, relative: Path, create: bool) -> int:
    """Open a project directory relative to a stable root descriptor."""
    if relative.is_absolute() or ".." in relative.parts:
        raise RetireError(f"项目目录必须位于根目录内: {relative}")
    current_fd = open_directory_no_symlinks(root)
    try:
        for component in relative.parts:
            try:
                next_fd = os.open(component, directory_open_flags(), dir_fd=current_fd)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(component, 0o755, dir_fd=current_fd)
                next_fd = os.open(component, directory_open_flags(), dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except OSError as exc:
        os.close(current_fd)
        raise RetireError(f"项目目录包含符号链接或无法安全创建: {relative}") from exc


def open_regular_file_no_symlinks(path: Path) -> int:
    """Open a regular file without following symlinks and without blocking on FIFOs."""
    if not path.is_absolute() or not path.name:
        raise RetireError(f"安全输入路径必须是绝对文件路径: {path}")
    current_fd = os.open(os.sep, directory_open_flags())
    try:
        for component in path.parts[1:-1]:
            next_fd = os.open(component, directory_open_flags(), dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        flags = (
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_CLOEXEC", 0)
        )
        source_fd = os.open(path.name, flags, dir_fd=current_fd)
    except OSError as exc:
        raise RetireError(f"归档输入包含符号链接或无法安全读取: {path}") from exc
    finally:
        os.close(current_fd)
    return source_fd


def copy_regular_file(
    source: Path, target: Path, expected_sha256: str | None = None
) -> None:
    """Copy one planned, bounded regular file from a stable descriptor."""
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        source_fd = open_regular_file_no_symlinks(source)
        with os.fdopen(source_fd, "rb") as source_handle:
            source_stat = os.fstat(source_handle.fileno())
            if not stat.S_ISREG(source_stat.st_mode):
                raise RetireError(f"归档输入不是普通文件: {source}")
            if source_stat.st_size >= MAX_FILE_BYTES:
                raise RetireError(f"单文件达到 100 MiB: {source}")
            copied = 0
            digest = hashlib.sha256()
            with target.open("xb") as target_handle:
                for chunk in iter(lambda: source_handle.read(1024 * 1024), b""):
                    copied += len(chunk)
                    if copied >= MAX_FILE_BYTES:
                        raise RetireError(f"单文件达到 100 MiB: {source}")
                    digest.update(chunk)
                    target_handle.write(chunk)
                os.fchmod(target_handle.fileno(), stat.S_IMODE(source_stat.st_mode))
            if expected_sha256 is not None and digest.hexdigest() != expected_sha256:
                raise RetireError(f"归档输入在计划后发生变化: {source}")
    except Exception:
        if target.exists():
            target.unlink()
        raise


def validate_staged_pdf(path: Path, expected_sha256: str) -> None:
    with path.open("rb") as handle:
        if handle.read(5) != b"%PDF-":
            raise RetireError("归档后的 submitted.pdf 没有 PDF 标头")
    if path.stat().st_size >= MAX_FILE_BYTES:
        raise RetireError("归档后的 submitted.pdf 达到 100 MiB")
    if sha256(path) != expected_sha256:
        raise RetireError("归档后的 submitted.pdf 与计划 SHA-256 不一致")


def publish_stage_no_replace(stage: Path, destination_name: str, parent_fd: int) -> None:
    """Reserve the final name exclusively, then atomically replace our reservation."""
    try:
        os.mkdir(destination_name, 0o700, dir_fd=parent_fd)
    except FileExistsError as exc:
        raise RetireError(f"目标已存在，拒绝覆盖: {destination_name}") from exc
    reserved = True
    try:
        os.rename(
            stage.name,
            destination_name,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
        )
        reserved = False
    except OSError as exc:
        raise RetireError(f"无法原子发布归档: {destination_name}") from exc
    finally:
        if reserved:
            try:
                os.rmdir(destination_name, dir_fd=parent_fd)
            except OSError:
                pass


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
        [
            latexmk,
            "-pdf",
            "-interaction=nonstopmode",
            "-halt-on-error",
            f"./{main_rel.as_posix()}",
        ],
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
    verification_method: str | None = None,
    body: str | None = None,
) -> None:
    lines = [
        "---",
        "status: archived",
        f"slug: {slug}",
        f"retired: {retired}",
        f"source_path: {json.dumps(source_rel, ensure_ascii=False)}",
        f"source_commit: {commit}",
        f"working_tree_dirty: {str(dirty).lower()}",
        f"verification: {verification}",
    ]
    if verification_method is not None:
        lines.append(f"verification_method: {verification_method}")
    lines.extend(["---", ""])
    if body is None:
        lines.extend(
            [
                f"# {slug}",
                "",
                "这是不可变的正式提交快照，不是实验数字、方法或论文叙事的权威来源。",
                "",
            ]
        )
    else:
        lines.extend([body.rstrip(), ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def write_checksums(package: Path) -> None:
    files = [package / "README.md", package / "submitted.pdf"]
    if (package / "VERIFICATION.json").is_file():
        files.append(package / "VERIFICATION.json")
    files.extend(sorted((package / "source").rglob("*")))
    files = [path for path in files if path.is_file()]
    lines = [f"{sha256(path)}  {path.relative_to(package)}" for path in files]
    (package / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_frontmatter(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return {}
    if not lines or lines[0].strip() != "---":
        return {}
    metadata: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return metadata
        if ":" in line:
            key, value = line.split(":", 1)
            metadata[key.strip()] = value.strip().strip("\"'")
    return {}


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
        if path.is_file() and path.name != "SHA256SUMS"
    }
    for raw_rel in sorted(payload - listed):
        failures.append(f"uncovered package file: {raw_rel}")
    if "submitted.pdf" not in listed:
        failures.append("submitted.pdf checksum missing")
    if "README.md" not in listed:
        failures.append("README.md checksum missing")

    metadata = read_frontmatter(package / "README.md")
    method = metadata.get("verification_method")
    report_path = package / "VERIFICATION.json"
    if report_path.is_file():
        if not method or method == "built-in-latex":
            failures.append("VERIFICATION.json requires a hybrid verification_method")
        try:
            report = validate_verification_report(
                report_path,
                package / "source",
                package / "submitted.pdf",
                allow_unverified=True,
            )
        except RetireError as exc:
            failures.append(f"invalid VERIFICATION.json: {exc}")
        else:
            if metadata.get("verification") != report["status"]:
                failures.append("README verification does not match VERIFICATION.json")
            if method != report["method"]:
                failures.append("README verification_method does not match VERIFICATION.json")
    elif method and method != "built-in-latex":
        failures.append("VERIFICATION.json missing for hybrid archive")
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
    if bool(args.verification_report) != bool(args.readme_body):
        raise RetireError("混合验证必须同时提供 --verification-report 和 --readme-body")
    verification_report_path: Path | None = None
    verification_report: dict[str, object] | None = None
    readme_body_path: Path | None = None
    readme_body: str | None = None
    if args.verification_report:
        verification_report_path = input_file(args.verification_report, "验证报告")
        readme_body_path = input_file(args.readme_body, "README 正文")
        verification_report = validate_verification_report(
            verification_report_path, source, pdf, args.allow_unverified
        )
        readme_body = validate_readme_body(readme_body_path)
    destination = inside(root, root / "archive" / "docs" / "paper" / f"{args.date}-{args.slug}")
    if destination.exists():
        raise RetireError(f"目标已存在，拒绝覆盖: {destination}")
    included, excluded = inventory(source, pdf, args.include)
    if not included:
        raise RetireError("未找到可归档源码；请检查 source 或使用 --include 指定必要文件")
    package_inputs = [pdf, *included]
    if verification_report_path is not None:
        package_inputs.extend([verification_report_path, readme_body_path])
    total, too_large = size_summary(package_inputs)
    if too_large:
        raise RetireError("单文件达到 100 MiB: " + ", ".join(str(path) for path in too_large))
    pdf_sha256 = sha256(pdf)
    if (
        verification_report is not None
        and verification_report["submitted_pdf_sha256"] != pdf_sha256
    ):
        raise RetireError("验证报告的提交 PDF SHA-256 与计划快照不一致")
    included_sha256 = {path: sha256(path) for path in included}
    commit, dirty = git_metadata(root)
    file_states = git_file_states(root, [pdf, *included])
    future_files = [
        destination / "README.md",
        destination / "submitted.pdf",
        destination / "SHA256SUMS",
        *(destination / "source" / path.relative_to(source) for path in included),
    ]
    if verification_report_path is not None:
        future_files.append(destination / "VERIFICATION.json")
    ignored_destination = ignored_future_paths(root, future_files)
    if ignored_destination:
        raise RetireError("归档目标会被 Git 忽略: " + ", ".join(ignored_destination))
    return {
        "root": root,
        "source": source,
        "source_rel": str(source.relative_to(root)),
        "pdf": pdf,
        "pdf_sha256": pdf_sha256,
        "destination": destination,
        "included": included,
        "included_sha256": included_sha256,
        "excluded": excluded,
        "total_bytes": total,
        "size_warning": total > WARN_TOTAL_BYTES,
        "source_commit": commit,
        "working_tree_dirty": dirty,
        "file_states": file_states,
        "verification_report_path": verification_report_path,
        "verification_report": verification_report,
        "readme_body_path": readme_body_path,
        "readme_body": readme_body,
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
    if plan["verification_report"] is not None:
        print(f"verification report: {plan['verification_report_path']}")
        print(f"verification method: {plan['verification_report']['method']}")
        print(f"README body: {plan['readme_body_path']}")
    else:
        print("verification method: built-in-latex")
    print("included source:")
    for path in plan["included"]:
        root_rel = str(path.relative_to(root))
        print(f"- {path.relative_to(source)} [{plan['file_states'][root_rel]}]")
    print("excluded:")
    for path, reason in plan["excluded"].items():
        print(f"- {path}: {reason}")


def apply_retire(args: argparse.Namespace, plan: dict[str, object]) -> None:
    destination: Path = plan["destination"]
    parent_fd = open_project_directory(
        plan["root"], Path("archive") / "docs" / "paper", create=True
    )
    previous_cwd_fd = os.open(".", directory_open_flags())
    stage: Path | None = None
    try:
        os.fchdir(parent_fd)
        stage = Path(tempfile.mkdtemp(prefix=f".{args.slug}-", dir="."))
        copy_regular_file(
            plan["pdf"], stage / "submitted.pdf", plan["pdf_sha256"]
        )
        stage_source = stage / "source"
        stage_source.mkdir()
        for path in plan["included"]:
            rel = path.relative_to(plan["source"])
            target = stage_source / rel
            copy_regular_file(path, target, plan["included_sha256"][path])
        report = plan["verification_report"]
        validate_staged_pdf(stage / "submitted.pdf", plan["pdf_sha256"])
        if report is None:
            verification = verify_latex(stage_source, args.main_tex, args.allow_unverified)
            verification_method = "built-in-latex"
        else:
            (stage / "VERIFICATION.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            verification = str(report["status"])
            verification_method = str(report["method"])
        write_readme(
            stage / "README.md",
            args.slug,
            args.date,
            plan["source_rel"],
            plan["source_commit"],
            plan["working_tree_dirty"],
            verification,
            verification_method,
            plan["readme_body"],
        )
        write_checksums(stage)
        failures = verify_checksums(stage)
        if failures:
            raise RetireError("归档后校验失败: " + "; ".join(failures))
        publish_stage_no_replace(stage, destination.name, parent_fd)
    except Exception:
        if stage is not None and stage.exists():
            shutil.rmtree(stage)
        raise
    finally:
        os.fchdir(previous_cwd_fd)
        os.close(previous_cwd_fd)
        os.close(parent_fd)
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
    parser.add_argument("--verification-report")
    parser.add_argument("--readme-body")

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
