#!/usr/bin/env python3
"""Read-only schema v4 health audit for research projects."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Iterable

from retire import RetireError, git_file_states, verify_checksums


IMPORTANT_SUFFIXES = {".md", ".tex", ".bib", ".sty", ".cls", ".bst"}
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


def read_frontmatter(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return {}
    if not lines or lines[0].strip() != "---":
        return {}
    data: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            key, value = line.split(":", 1)
            data[key.strip()] = value.strip().strip('"\'')
    return data


def relpaths(root: Path, paths: Iterable[Path]) -> list[str]:
    return sorted(str(path.relative_to(root)) for path in paths)


def is_legacy_agents_pointer(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return bool(
        lines
        and lines[0] == "@ CLAUDE.md"
        and "## Documentation" not in lines
        and "## Last Handoff" not in lines
    )


def ignored_important_files(root: Path) -> list[str]:
    candidates: list[Path] = []
    for dirname in ("docs", "paper"):
        base = root / dirname
        if not base.is_dir():
            continue
        candidates.extend(
            path
            for path in base.rglob("*")
            if path.is_file() and path.suffix.lower() in IMPORTANT_SUFFIXES
        )
    if not candidates or not (root / ".git").exists():
        return []
    payload = b"\0".join(str(path.relative_to(root)).encode() for path in candidates) + b"\0"
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-z", "--stdin"],
        cwd=root,
        input=payload,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    ignored = [item.decode() for item in result.stdout.split(b"\0") if item]
    return sorted(ignored)


def audit_packages(root: Path, packages: list[Path], expected_status: str) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for package in packages:
        failures: list[str] = []
        try:
            failures.extend(verify_checksums(package))
        except (RetireError, OSError, UnicodeDecodeError, ValueError) as exc:
            failures.append(str(exc))
        status = read_frontmatter(package / "README.md").get("status")
        if status != expected_status:
            failures.append(f"status={status or 'missing'}; expected {expected_status}")
        files = [path for path in package.rglob("*") if path.is_file()]
        states = git_file_states(root, files) if files else {}
        results.append(
            {
                "path": str(package.relative_to(root)),
                "status": status,
                "failures": failures,
                "git_states": states,
            }
        )
    return results


def audit(root: Path, full: bool) -> dict[str, object]:
    root = root.resolve()
    docs = root / "docs"
    handoffs = docs / "handoffs"
    history = handoffs / "history"
    resolved_history = history / "resolved"
    superseded_history = history / "superseded"
    issues: list[dict[str, str]] = []

    readme_meta = read_frontmatter(docs / "README.md") if docs.is_dir() else {}
    raw_version = readme_meta.get("schema_version")
    try:
        schema_version = int(raw_version) if raw_version is not None else None
    except ValueError:
        schema_version = None

    if not docs.is_dir():
        issues.append({"severity": "error", "code": "docs-missing", "detail": "docs/ 不存在"})
    elif schema_version != 4:
        issues.append(
            {
                "severity": "warning",
                "code": "schema-version",
                "detail": f"schema_version={raw_version or 'missing'}，当前为 4",
            }
        )

    required_entries = (
        (docs / "README.md", "file"),
        (docs / "project" / "overview.md", "file"),
        (resolved_history, "directory"),
        (superseded_history, "directory"),
        (root / "archive" / "docs", "directory"),
    )
    missing_entries = [
        str(path.relative_to(root))
        for path, kind in required_entries
        if (kind == "file" and not path.is_file()) or (kind == "directory" and not path.is_dir())
    ]
    if missing_entries:
        issues.append(
            {
                "severity": "warning",
                "code": "required-entry-missing",
                "detail": ", ".join(missing_entries),
            }
        )

    project_entries = [
        path for path in (root / "CLAUDE.md", root / "AGENTS.md") if path.is_file()
    ]
    if not project_entries:
        issues.append(
            {
                "severity": "warning",
                "code": "project-entry-missing",
                "detail": "项目根没有 CLAUDE.md 或 AGENTS.md；普通流程不会自动创建",
            }
        )

    if is_legacy_agents_pointer(root / "AGENTS.md"):
        issues.append(
            {
                "severity": "warning",
                "code": "legacy-agents-pointer",
                "detail": "AGENTS.md 仍是 @ CLAUDE.md 占位入口，应由 init 迁移为独立受管入口",
            }
        )

    active_files: list[Path] = []
    other_root_handoffs: list[Path] = []
    if handoffs.is_dir():
        for path in handoffs.glob("*.md"):
            status = read_frontmatter(path).get("status")
            if status == "active":
                active_files.append(path)
            else:
                other_root_handoffs.append(path)
    if len(active_files) > 1:
        issues.append(
            {
                "severity": "error",
                "code": "multiple-active-handoffs",
                "detail": f"handoffs 根目录存在 {len(active_files)} 个 active 文件",
            }
        )
    if other_root_handoffs:
        issues.append(
            {
                "severity": "warning",
                "code": "handoff-history-outside-history",
                "detail": ", ".join(relpaths(root, other_root_handoffs)),
            }
        )
    if (handoffs / "resolved").exists():
        issues.append(
            {
                "severity": "warning",
                "code": "legacy-resolved-directory",
                "detail": "docs/handoffs/resolved/ 应迁移为 history/resolved/",
            }
        )

    unclassified_history = list(history.glob("*.md")) if history.is_dir() else []
    if unclassified_history:
        issues.append(
            {
                "severity": "warning",
                "code": "handoff-history-unclassified",
                "detail": ", ".join(relpaths(root, unclassified_history)),
            }
        )
    resolved_files = list(resolved_history.glob("*.md")) if resolved_history.is_dir() else []
    superseded_files = (
        list(superseded_history.glob("*.md")) if superseded_history.is_dir() else []
    )
    status_mismatches = [
        path
        for path in resolved_files
        if read_frontmatter(path).get("status") != "resolved"
    ] + [
        path
        for path in superseded_files
        if read_frontmatter(path).get("status") != "superseded"
    ]
    if status_mismatches:
        issues.append(
            {
                "severity": "warning",
                "code": "handoff-history-status-mismatch",
                "detail": ", ".join(relpaths(root, status_mismatches)),
            }
        )

    ignored = ignored_important_files(root)
    if ignored:
        issues.append(
            {
                "severity": "error",
                "code": "ignored-important-source",
                "detail": ", ".join(ignored),
            }
        )

    report: dict[str, object] = {
        "root": str(root),
        "schema_version": schema_version,
        "project_entries": relpaths(root, project_entries),
        "active_handoffs": relpaths(root, active_files),
        "history_handoffs": len(resolved_files) + len(superseded_files) + len(unclassified_history),
        "resolved_handoffs": len(resolved_files),
        "superseded_handoffs": len(superseded_files),
        "ignored_important_files": ignored,
        "authoritative_documents": [
            str(path.relative_to(root))
            for path in (
                docs / "evaluation" / "results.md",
                docs / "methods" / "README.md",
                docs / "project" / "paper-plan.md",
            )
            if path.exists()
        ],
        "issues": issues,
    }

    if full:
        markdown_files = list(docs.rglob("*.md")) if docs.is_dir() else []
        stale = [
            path
            for path in markdown_files
            if not (history.is_dir() and history in path.parents)
            and read_frontmatter(path).get("status") == "stale"
        ]
        paper = root / "paper"
        build_artifacts = [
            path
            for path in paper.rglob("*")
            if paper.is_dir() and path.is_file() and path.name.endswith(BUILD_SUFFIXES)
        ]
        top_level_pdfs = list(paper.glob("*.pdf")) if paper.is_dir() else []
        dashboards = docs / "dashboards"
        html_slugs = {path.stem for path in dashboards.glob("*.html")} if dashboards.is_dir() else set()
        render_dir = dashboards / "render"
        render_slugs = {path.stem for path in render_dir.glob("*.py")} if render_dir.is_dir() else set()
        dashboard_issues = {
            "missing_generators": sorted(html_slugs - render_slugs),
            "missing_outputs": sorted(render_slugs - html_slugs),
        }
        if dashboard_issues["missing_generators"]:
            issues.append(
                {
                    "severity": "warning",
                    "code": "dashboard-generator-missing",
                    "detail": ", ".join(dashboard_issues["missing_generators"]),
                }
            )
        if dashboard_issues["missing_outputs"]:
            issues.append(
                {
                    "severity": "warning",
                    "code": "dashboard-output-missing",
                    "detail": ", ".join(dashboard_issues["missing_outputs"]),
                }
            )
        archive_dir = root / "archive" / "docs" / "paper"
        archive_packages = (
            sorted(path for path in archive_dir.iterdir() if path.is_dir())
            if archive_dir.is_dir()
            else []
        )
        archive_package_audits = audit_packages(root, archive_packages, "archived")
        for package_audit in archive_package_audits:
            if package_audit["failures"]:
                issues.append(
                    {
                        "severity": "error",
                        "code": "invalid-paper-archive",
                        "detail": f"{package_audit['path']}: {'; '.join(package_audit['failures'])}",
                    }
                )
            non_tracked = [
                f"{path} ({state})"
                for path, state in package_audit["git_states"].items()
                if state != "tracked"
            ]
            if non_tracked:
                issues.append(
                    {
                        "severity": "warning",
                        "code": "paper-archive-not-tracked",
                        "detail": f"{package_audit['path']}: {', '.join(non_tracked)}",
                    }
                )
        report.update(
            {
                "stale_documents": relpaths(root, stale),
                "latex_build_artifacts": relpaths(root, build_artifacts),
                "paper_top_level_pdfs": relpaths(root, top_level_pdfs),
                "dashboard_issues": dashboard_issues,
                "archived_paper_audits": archive_package_audits,
                "archived_documents": len(archive_packages),
            }
        )
        if len(top_level_pdfs) > 1:
            issues.append(
                {
                    "severity": "warning",
                    "code": "multiple-paper-pdfs",
                    "detail": ", ".join(relpaths(root, top_level_pdfs)),
                }
            )
        if build_artifacts:
            issues.append(
                {
                    "severity": "warning",
                    "code": "latex-build-artifacts",
                    "detail": f"发现 {len(build_artifacts)} 个构建产物",
                }
            )

    return report


def print_human(report: dict[str, object], full: bool) -> None:
    print(f"research status: {report['root']}")
    print(f"schema: {report['schema_version'] or 'missing'}")
    print(f"project entries: {', '.join(report['project_entries']) or 'none'}")
    active = report["active_handoffs"]
    print(f"active handoff: {active[0] if len(active) == 1 else len(active)}")
    print(f"history handoffs: {report['history_handoffs']}")
    print(f"resolved handoffs: {report['resolved_handoffs']}")
    print(f"superseded handoffs: {report['superseded_handoffs']}")
    print(f"authoritative docs: {len(report['authoritative_documents'])}")
    if full:
        print(f"stale docs: {len(report['stale_documents'])}")
        print(f"latex build artifacts: {len(report['latex_build_artifacts'])}")
        print(f"paper top-level PDFs: {len(report['paper_top_level_pdfs'])}")
        print(f"archived paper packages: {report['archived_documents']}")
    issues = report["issues"]
    if not issues:
        print("issues: none")
        return
    print("issues:")
    for issue in issues:
        print(f"- [{issue['severity']}] {issue['code']}: {issue['detail']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="research project root")
    parser.add_argument("--full", action="store_true", help="run the expanded audit")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    args = parser.parse_args()
    report = audit(Path(args.root), args.full)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_human(report, args.full)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
