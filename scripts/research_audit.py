#!/usr/bin/env python3
"""Read-only schema v4 health audit for research projects."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Iterable

from deliverable import DeliverableError, git_file_states, verify_checksums


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
        except (DeliverableError, OSError, UnicodeDecodeError, ValueError) as exc:
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
        (handoffs / "history", "directory"),
        (root / "archive" / "docs", "directory"),
        (root / "CLAUDE.md", "file"),
        (root / "AGENTS.md", "file"),
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
                "detail": "docs/handoffs/resolved/ 应迁移为 history/",
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
        "active_handoffs": relpaths(root, active_files),
        "history_handoffs": len(list((handoffs / "history").glob("*.md")))
        if (handoffs / "history").is_dir()
        else 0,
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
        history = handoffs / "history"
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
        deliverables_dir = docs / "deliverables"
        active_packages = (
            sorted(path for path in deliverables_dir.iterdir() if path.is_dir())
            if deliverables_dir.is_dir()
            else []
        )
        archive_dir = root / "archive" / "docs"
        archive_packages = (
            sorted(
                path
                for path in archive_dir.iterdir()
                if path.is_dir() and ((path / "SHA256SUMS").exists() or (path / "submitted.pdf").exists())
            )
            if archive_dir.is_dir()
            else []
        )
        active_package_audits = audit_packages(root, active_packages, "submitted")
        archive_package_audits = audit_packages(root, archive_packages, "archived")
        for package_audit in [*active_package_audits, *archive_package_audits]:
            if package_audit["failures"]:
                issues.append(
                    {
                        "severity": "error",
                        "code": "invalid-deliverable-package",
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
                        "code": "deliverable-not-tracked",
                        "detail": f"{package_audit['path']}: {', '.join(non_tracked)}",
                    }
                )
        report.update(
            {
                "stale_documents": relpaths(root, stale),
                "latex_build_artifacts": relpaths(root, build_artifacts),
                "paper_top_level_pdfs": relpaths(root, top_level_pdfs),
                "dashboard_issues": dashboard_issues,
                "active_deliverables": len(active_packages),
                "deliverable_audits": active_package_audits,
                "archived_deliverable_audits": archive_package_audits,
                "archived_documents": len(list((root / "archive" / "docs").glob("*/README.md")))
                if (root / "archive" / "docs").is_dir()
                else 0,
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
    active = report["active_handoffs"]
    print(f"active handoff: {active[0] if len(active) == 1 else len(active)}")
    print(f"history handoffs: {report['history_handoffs']}")
    print(f"authoritative docs: {len(report['authoritative_documents'])}")
    if full:
        print(f"stale docs: {len(report['stale_documents'])}")
        print(f"latex build artifacts: {len(report['latex_build_artifacts'])}")
        print(f"paper top-level PDFs: {len(report['paper_top_level_pdfs'])}")
        print(f"active deliverables: {report['active_deliverables']}")
        print(f"archived document packages: {report['archived_documents']}")
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
