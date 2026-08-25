from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
AUDIT = REPO / "scripts" / "research_audit.py"
RETIRE = REPO / "scripts" / "retire.py"
INSTALL = REPO / "install.sh"


def run_script(script: Path, *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def load_retire_module():
    spec = importlib.util.spec_from_file_location("research_retire", RETIRE)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load retire.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ResearchAuditTests(unittest.TestCase):
    def test_reports_missing_v4_required_entries(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "docs").mkdir()
            (root / "docs" / "README.md").write_text(
                "---\nschema_version: 4\nstatus: active\n---\n", encoding="utf-8"
            )
            result = run_script(AUDIT, "--root", str(root), "--json", cwd=root)
            self.assertEqual(result.returncode, 0, result.stdout)
            report = json.loads(result.stdout)
            issue = next(item for item in report["issues"] if item["code"] == "required-entry-missing")
            self.assertIn("docs/project/overview.md", issue["detail"])
            self.assertIn("docs/handoffs/history/resolved", issue["detail"])
            self.assertIn("docs/handoffs/history/superseded", issue["detail"])
            self.assertIn("archive/docs", issue["detail"])
            self.assertNotIn("CLAUDE.md", issue["detail"])
            self.assertNotIn("AGENTS.md", issue["detail"])
            entry_issue = next(item for item in report["issues"] if item["code"] == "project-entry-missing")
            self.assertIn("CLAUDE.md", entry_issue["detail"])
            self.assertIn("AGENTS.md", entry_issue["detail"])

    def test_any_existing_project_entry_combination_is_valid(self) -> None:
        for entry_names in (("AGENTS.md",), ("CLAUDE.md",), ("CLAUDE.md", "AGENTS.md")):
            with self.subTest(entry_names=entry_names), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                (root / "docs" / "project").mkdir(parents=True)
                (root / "docs" / "handoffs" / "history" / "resolved").mkdir(parents=True)
                (root / "docs" / "handoffs" / "history" / "superseded").mkdir()
                (root / "archive" / "docs").mkdir(parents=True)
                (root / "docs" / "README.md").write_text(
                    "---\nschema_version: 4\nstatus: active\n---\n", encoding="utf-8"
                )
                (root / "docs" / "project" / "overview.md").write_text(
                    "overview\n", encoding="utf-8"
                )
                for entry_name in entry_names:
                    (root / entry_name).write_text("# Project instructions\n", encoding="utf-8")

                result = run_script(AUDIT, "--root", str(root), "--json", cwd=root)
                self.assertEqual(result.returncode, 0, result.stdout)
                report = json.loads(result.stdout)
                self.assertEqual(report["project_entries"], sorted(entry_names))
                codes = {issue["code"] for issue in report["issues"]}
                self.assertNotIn("project-entry-missing", codes)
                self.assertNotIn("required-entry-missing", codes)

    def test_history_subdirectories_are_counted_and_status_checked(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            resolved = root / "docs" / "handoffs" / "history" / "resolved"
            superseded = root / "docs" / "handoffs" / "history" / "superseded"
            resolved.mkdir(parents=True)
            superseded.mkdir()
            (resolved / "done.md").write_text("---\nstatus: resolved\n---\n", encoding="utf-8")
            (superseded / "carried.md").write_text(
                "---\nstatus: superseded\n---\n", encoding="utf-8"
            )
            (resolved / "wrong.md").write_text("---\nstatus: active\n---\n", encoding="utf-8")
            (resolved.parent / "unclassified.md").write_text(
                "---\nstatus: resolved\n---\n", encoding="utf-8"
            )

            result = run_script(AUDIT, "--root", str(root), "--json", cwd=root)
            self.assertEqual(result.returncode, 0, result.stdout)
            report = json.loads(result.stdout)
            self.assertEqual(report["history_handoffs"], 4)
            self.assertEqual(report["resolved_handoffs"], 2)
            self.assertEqual(report["superseded_handoffs"], 1)
            codes = {issue["code"] for issue in report["issues"]}
            self.assertIn("handoff-history-unclassified", codes)
            self.assertIn("handoff-history-status-mismatch", codes)

    def test_reports_schema_handoff_and_ignored_source(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / ".gitignore").write_text("/paper/\n", encoding="utf-8")
            (root / "docs" / "handoffs" / "history").mkdir(parents=True)
            (root / "docs" / "handoffs" / "resolved").mkdir()
            (root / "docs" / "README.md").write_text(
                "---\nschema_version: 4\nstatus: active\n---\n", encoding="utf-8"
            )
            (root / "docs" / "handoffs" / "2026-01-01-1200-test.md").write_text(
                "---\nstatus: active\n---\n\n## 下一步\n继续测试\n", encoding="utf-8"
            )
            (root / "paper").mkdir()
            (root / "paper" / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
            (root / "paper" / "main.synctex.gz").write_bytes(b"generated")

            result = run_script(AUDIT, "--root", str(root), "--json", cwd=root)
            self.assertEqual(result.returncode, 0, result.stdout)
            report = json.loads(result.stdout)
            self.assertEqual(report["schema_version"], 4)
            self.assertEqual(len(report["active_handoffs"]), 1)
            codes = {issue["code"] for issue in report["issues"]}
            self.assertIn("legacy-resolved-directory", codes)
            self.assertIn("ignored-important-source", codes)
            self.assertIn("paper/main.tex", report["ignored_important_files"])
            self.assertNotIn("paper/main.synctex.gz", report["ignored_important_files"])

    def test_full_audit_reports_multiple_active_handoffs_and_build_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "docs" / "handoffs" / "history").mkdir(parents=True)
            (root / "docs" / "README.md").write_text(
                "---\nschema_version: 4\nstatus: active\n---\n", encoding="utf-8"
            )
            for index in (1, 2):
                (root / "docs" / "handoffs" / f"2026-01-0{index}-1200-test.md").write_text(
                    "---\nstatus: active\n---\n", encoding="utf-8"
                )
            (root / "paper").mkdir()
            (root / "paper" / "main.aux").write_text("generated", encoding="utf-8")
            (root / "paper" / "main.pdf").write_bytes(b"%PDF-1.4\n")
            (root / "paper" / "older.pdf").write_bytes(b"%PDF-1.4\n")
            (root / "docs" / "dashboards").mkdir(parents=True)
            (root / "docs" / "dashboards" / "results.html").write_text("<html></html>", encoding="utf-8")

            result = run_script(AUDIT, "--root", str(root), "--full", "--json", cwd=root)
            self.assertEqual(result.returncode, 0, result.stdout)
            report = json.loads(result.stdout)
            codes = {issue["code"] for issue in report["issues"]}
            self.assertIn("multiple-active-handoffs", codes)
            self.assertIn("latex-build-artifacts", codes)
            self.assertIn("multiple-paper-pdfs", codes)
            self.assertIn("dashboard-generator-missing", codes)
            human = run_script(AUDIT, "--root", str(root), "--full", cwd=root)
            self.assertIn("dashboard-generator-missing", human.stdout)

    def test_full_audit_rejects_broken_archived_paper_package(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / "docs" / "project").mkdir(parents=True)
            (root / "docs" / "handoffs" / "history").mkdir(parents=True)
            (root / "archive" / "docs").mkdir(parents=True)
            (root / "docs" / "README.md").write_text(
                "---\nschema_version: 4\nstatus: active\n---\n", encoding="utf-8"
            )
            (root / "docs" / "project" / "overview.md").write_text("overview\n", encoding="utf-8")
            (root / "CLAUDE.md").write_text("# Project\n", encoding="utf-8")
            (root / "AGENTS.md").write_text("@ CLAUDE.md\n", encoding="utf-8")
            broken = root / "archive" / "docs" / "paper" / "2026-08-23-broken"
            broken.mkdir(parents=True)
            (broken / "README.md").write_text("---\nstatus: archived\n---\n", encoding="utf-8")

            result = run_script(AUDIT, "--root", str(root), "--full", "--json", cwd=root)
            self.assertEqual(result.returncode, 0, result.stdout)
            report = json.loads(result.stdout)
            codes = {issue["code"] for issue in report["issues"]}
            self.assertIn("invalid-paper-archive", codes)
            self.assertIn("paper-archive-not-tracked", codes)
            self.assertIn("legacy-agents-pointer", codes)
            self.assertEqual(report["archived_documents"], 1)


class RetireTests(unittest.TestCase):
    def make_project(self, root: Path) -> None:
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        paper = root / "paper"
        (paper / "figures").mkdir(parents=True)
        (paper / "main.tex").write_text(
            "\\documentclass{article}\n\\begin{document}\nTest\n\\end{document}\n",
            encoding="utf-8",
        )
        (paper / "references.bib").write_text("", encoding="utf-8")
        (paper / "figures" / "plot.png").write_bytes(b"png")
        (paper / "banner.png").write_bytes(b"png")
        (paper / "main.pdf").write_bytes(b"%PDF-1.4\nsubmitted\n")
        (paper / "main.aux").write_text("generated", encoding="utf-8")
        (paper / "main-round1.pdf").write_bytes(b"%PDF-1.4\nold\n")

    def archive_path(self, root: Path, slug: str = "course-paper") -> Path:
        return root / "archive" / "docs" / "paper" / f"2026-08-23-{slug}"

    def write_hybrid_inputs(
        self, root: Path, pdf: Path, build_cwd: str = "."
    ) -> tuple[Path, Path]:
        report = root / "verification.json"
        report.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "passed",
                    "method": "agent-isolated-build",
                    "submitted_pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
                    "build_command": ["latexmk -xelatex main.tex"],
                    "build_cwd": build_cwd,
                    "checks": [
                        {
                            "name": "isolated-build",
                            "status": "passed",
                            "detail": "build completed",
                        },
                        {
                            "name": "submitted-pdf",
                            "status": "passed",
                            "detail": "19 pages, A4",
                        },
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        readme_body = root / "archive-readme.md"
        readme_body.write_text(
            """# 双语共读故事生成中的服务不对称

## 项目简介

本项目研究双语故事生成中的服务不对称。

## 版本定位

这是课程平台实际接收的提交版本。

## 归档内容

`submitted.pdf` 是提交文件，`source/` 保存可复现源码。

## 编译与复现

```bash
cd source/tex
latexmk -xelatex main.tex
```

## 验证

隔离构建和 PDF 检查均通过。

## 与其他版本的关系

本版本取代较早的研究草稿，作为课程交付记录。

## 权威来源

归档记录提交内容；实验数字仍以项目结果文档为准。
""",
            encoding="utf-8",
        )
        return report, readme_body

    def retire_args(
        self,
        root: Path,
        report: Path,
        readme_body: Path,
        *,
        allow_unverified: bool = False,
    ) -> argparse.Namespace:
        return argparse.Namespace(
            root=str(root),
            source="paper",
            include=[],
            slug="course-paper",
            pdf=None,
            main_tex="main.tex",
            date="2026-08-23",
            apply=True,
            allow_unverified=allow_unverified,
            verification_report=str(report),
            readme_body=str(readme_body),
        )

    def test_hybrid_mode_archives_agent_report_and_rich_readme_for_custom_source(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            source = root / "term_paper"
            (source / "tex").mkdir(parents=True)
            (source / "README.md").write_text("build instructions\n", encoding="utf-8")
            (source / "tex" / "main.tex").write_text(
                "\\documentclass{article}\n\\begin{document}\nTest\n\\end{document}\n",
                encoding="utf-8",
            )
            pdf = source / "submitted-course-paper.pdf"
            pdf.write_bytes(b"%PDF-1.4\nsubmitted\n")
            report, readme_body = self.write_hybrid_inputs(root, pdf, build_cwd="tex")

            result = run_script(
                RETIRE,
                "--root",
                str(root),
                "--source",
                "term_paper",
                "--slug",
                "course-paper",
                "--date",
                "2026-08-23",
                "--pdf",
                str(pdf),
                "--main-tex",
                "tex/main.tex",
                "--include",
                "README.md",
                "--verification-report",
                str(report),
                "--readme-body",
                str(readme_body),
                "--apply",
                cwd=root,
            )

            self.assertEqual(result.returncode, 0, result.stdout)
            archive = self.archive_path(root)
            self.assertEqual(
                json.loads((archive / "VERIFICATION.json").read_text(encoding="utf-8"))["method"],
                "agent-isolated-build",
            )
            readme = (archive / "README.md").read_text(encoding="utf-8")
            self.assertIn('source_path: "term_paper"', readme)
            self.assertIn("verification_method: agent-isolated-build", readme)
            self.assertIn("# 双语共读故事生成中的服务不对称", readme)
            self.assertNotIn("# course-paper", readme)
            self.assertIn("## 编译与复现", readme)
            self.assertIn("这是课程平台实际接收的提交版本", readme)
            checksums = (archive / "SHA256SUMS").read_text(encoding="utf-8")
            self.assertIn("  README.md", checksums)
            self.assertIn("  VERIFICATION.json", checksums)
            self.assertTrue((archive / "source" / "README.md").is_file())
            self.assertTrue((archive / "source" / "tex" / "main.tex").is_file())

    def test_hybrid_mode_rejects_report_for_different_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.make_project(root)
            pdf = root / "paper" / "main.pdf"
            report, readme_body = self.write_hybrid_inputs(root, pdf)
            payload = json.loads(report.read_text(encoding="utf-8"))
            payload["submitted_pdf_sha256"] = "0" * 64
            report.write_text(json.dumps(payload), encoding="utf-8")

            result = run_script(
                RETIRE,
                "--root",
                str(root),
                "--slug",
                "course-paper",
                "--date",
                "2026-08-23",
                "--verification-report",
                str(report),
                "--readme-body",
                str(readme_body),
                "--apply",
                cwd=root,
            )

            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertIn("SHA-256", result.stdout)
            self.assertFalse(self.archive_path(root).exists())

    def test_hybrid_mode_rejects_failed_report(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.make_project(root)
            pdf = root / "paper" / "main.pdf"
            report, readme_body = self.write_hybrid_inputs(root, pdf)
            payload = json.loads(report.read_text(encoding="utf-8"))
            payload["status"] = "failed"
            report.write_text(json.dumps(payload), encoding="utf-8")

            result = run_script(
                RETIRE,
                "--root",
                str(root),
                "--slug",
                "course-paper",
                "--date",
                "2026-08-23",
                "--verification-report",
                str(report),
                "--readme-body",
                str(readme_body),
                cwd=root,
            )

            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertIn("failed", result.stdout)
            self.assertFalse(self.archive_path(root).exists())

    def test_hybrid_mode_requires_a_document_title(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.make_project(root)
            pdf = root / "paper" / "main.pdf"
            report, readme_body = self.write_hybrid_inputs(root, pdf)
            body = readme_body.read_text(encoding="utf-8")
            readme_body.write_text(body.split("\n", 2)[2], encoding="utf-8")

            result = run_script(
                RETIRE,
                "--root",
                str(root),
                "--slug",
                "course-paper",
                "--date",
                "2026-08-23",
                "--verification-report",
                str(report),
                "--readme-body",
                str(readme_body),
                cwd=root,
            )

            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertIn("README 正文必须以一级标题开头", result.stdout)
            self.assertFalse(self.archive_path(root).exists())

    def test_hybrid_mode_rejects_empty_duplicate_or_reordered_readme_sections(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.make_project(root)
            pdf = root / "paper" / "main.pdf"
            report, readme_body = self.write_hybrid_inputs(root, pdf)
            original = readme_body.read_text(encoding="utf-8")
            cases = {
                "empty": original.replace(
                    "## 验证\n\n隔离构建和 PDF 检查均通过。",
                    "## 验证\n",
                ),
                "duplicate": original + "\n## 验证\n\n重复。\n",
                "reordered": original.replace(
                    "## 项目简介\n\n本项目研究双语故事生成中的服务不对称。\n\n"
                    "## 版本定位\n\n这是课程平台实际接收的提交版本。",
                    "## 版本定位\n\n这是课程平台实际接收的提交版本。\n\n"
                    "## 项目简介\n\n本项目研究双语故事生成中的服务不对称。",
                ),
            }
            for label, body in cases.items():
                with self.subTest(label=label):
                    readme_body.write_text(body, encoding="utf-8")
                    result = run_script(
                        RETIRE,
                        "--root",
                        str(root),
                        "--slug",
                        "course-paper",
                        "--date",
                        "2026-08-23",
                        "--verification-report",
                        str(report),
                        "--readme-body",
                        str(readme_body),
                        cwd=root,
                    )
                    self.assertEqual(result.returncode, 2, result.stdout)
            self.assertFalse(self.archive_path(root).exists())

    def test_hybrid_mode_ignores_headings_inside_longer_fenced_code_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.make_project(root)
            pdf = root / "paper" / "main.pdf"
            report, readme_body = self.write_hybrid_inputs(root, pdf)
            fenced_sections = "\n\n".join(
                f"## {heading}\n\nonly code"
                for heading in (
                    "项目简介",
                    "版本定位",
                    "归档内容",
                    "编译与复现",
                    "验证",
                    "与其他版本的关系",
                    "权威来源",
                )
            )
            readme_body.write_text(
                f"# 课程论文\n\n````markdown\n```\n{fenced_sections}\n````\n",
                encoding="utf-8",
            )

            result = run_script(
                RETIRE,
                "--root",
                str(root),
                "--slug",
                "course-paper",
                "--date",
                "2026-08-23",
                "--verification-report",
                str(report),
                "--readme-body",
                str(readme_body),
                cwd=root,
            )

            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertIn("README 正文缺少章节", result.stdout)

    def test_hybrid_mode_requires_report_and_readme_body_as_a_pair(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.make_project(root)
            pdf = root / "paper" / "main.pdf"
            report, _ = self.write_hybrid_inputs(root, pdf)

            result = run_script(
                RETIRE,
                "--root",
                str(root),
                "--slug",
                "course-paper",
                "--date",
                "2026-08-23",
                "--verification-report",
                str(report),
                cwd=root,
            )

            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertIn("必须同时提供", result.stdout)
            self.assertFalse(self.archive_path(root).exists())

    def test_hybrid_mode_requires_confirmation_for_not_run_report(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.make_project(root)
            pdf = root / "paper" / "main.pdf"
            report, readme_body = self.write_hybrid_inputs(root, pdf)
            payload = json.loads(report.read_text(encoding="utf-8"))
            payload["status"] = "not-run"
            payload["checks"] = [
                {
                    "name": "isolated-build",
                    "status": "not-run",
                    "detail": "TeX toolchain unavailable",
                }
            ]
            report.write_text(json.dumps(payload), encoding="utf-8")

            rejected = run_script(
                RETIRE,
                "--root",
                str(root),
                "--slug",
                "course-paper",
                "--date",
                "2026-08-23",
                "--verification-report",
                str(report),
                "--readme-body",
                str(readme_body),
                cwd=root,
            )
            accepted = run_script(
                RETIRE,
                "--root",
                str(root),
                "--slug",
                "course-paper",
                "--date",
                "2026-08-23",
                "--verification-report",
                str(report),
                "--readme-body",
                str(readme_body),
                "--allow-unverified",
                cwd=root,
            )

            self.assertEqual(rejected.returncode, 2, rejected.stdout)
            self.assertIn("--allow-unverified", rejected.stdout)
            self.assertEqual(accepted.returncode, 0, accepted.stdout)
            self.assertFalse(self.archive_path(root).exists())

            applied = run_script(
                RETIRE,
                "--root",
                str(root),
                "--slug",
                "course-paper",
                "--date",
                "2026-08-23",
                "--verification-report",
                str(report),
                "--readme-body",
                str(readme_body),
                "--allow-unverified",
                "--apply",
                cwd=root,
            )
            self.assertEqual(applied.returncode, 0, applied.stdout)
            readme = (self.archive_path(root) / "README.md").read_text(encoding="utf-8")
            self.assertIn("verification: not-run", readme)

    def test_hybrid_mode_requires_complete_readme_body(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.make_project(root)
            pdf = root / "paper" / "main.pdf"
            report, readme_body = self.write_hybrid_inputs(root, pdf)
            readme_body.write_text(
                "# 课程论文\n\n## 项目简介\n\n内容不完整。\n", encoding="utf-8"
            )

            result = run_script(
                RETIRE,
                "--root",
                str(root),
                "--slug",
                "course-paper",
                "--date",
                "2026-08-23",
                "--verification-report",
                str(report),
                "--readme-body",
                str(readme_body),
                cwd=root,
            )

            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertIn("README 正文缺少章节", result.stdout)
            self.assertIn("编译与复现", result.stdout)
            self.assertFalse(self.archive_path(root).exists())

    def test_apply_revalidates_staged_pdf_against_report(self) -> None:
        retire = load_retire_module()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.make_project(root)
            pdf = root / "paper" / "main.pdf"
            report, readme_body = self.write_hybrid_inputs(root, pdf)
            args = self.retire_args(root, report, readme_body)
            plan = retire.plan_retire(args)
            pdf.write_bytes(b"%PDF-1.4\nchanged after plan\n")

            with self.assertRaises(retire.RetireError):
                retire.apply_retire(args, plan)

            self.assertFalse(self.archive_path(root).exists())
            self.assertFalse(any((root / "archive" / "docs" / "paper").glob(".course-paper-*")))

    def test_builtin_apply_revalidates_pdf_against_the_plan(self) -> None:
        retire = load_retire_module()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.make_project(root)
            args = argparse.Namespace(
                root=str(root),
                source="paper",
                include=[],
                slug="course-paper",
                pdf=None,
                main_tex="main.tex",
                date="2026-08-23",
                apply=True,
                allow_unverified=True,
                verification_report=None,
                readme_body=None,
            )
            plan = retire.plan_retire(args)
            (root / "paper" / "main.pdf").write_bytes(
                b"%PDF-1.4\na different valid PDF after plan\n"
            )

            with self.assertRaises(retire.RetireError):
                retire.apply_retire(args, plan)

            self.assertFalse(self.archive_path(root).exists())

    def test_apply_rejects_source_replaced_by_symlink_after_plan(self) -> None:
        retire = load_retire_module()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.make_project(root)
            pdf = root / "paper" / "main.pdf"
            report, readme_body = self.write_hybrid_inputs(root, pdf)
            args = self.retire_args(root, report, readme_body)
            plan = retire.plan_retire(args)
            main_tex = root / "paper" / "main.tex"
            replacement = root / "replacement.tex"
            replacement.write_text("outside source inventory\n", encoding="utf-8")
            main_tex.unlink()
            main_tex.symlink_to(replacement)

            with self.assertRaises(retire.RetireError):
                retire.apply_retire(args, plan)

            self.assertFalse(self.archive_path(root).exists())

    def test_apply_rejects_source_parent_replaced_by_symlink_after_plan(self) -> None:
        retire = load_retire_module()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.make_project(root)
            pdf = root / "paper" / "main.pdf"
            report, readme_body = self.write_hybrid_inputs(root, pdf)
            args = self.retire_args(root, report, readme_body)
            plan = retire.plan_retire(args)
            original = root / "paper-original"
            (root / "paper").rename(original)
            (root / "paper").symlink_to(original, target_is_directory=True)

            with self.assertRaises(retire.RetireError):
                retire.apply_retire(args, plan)

            self.assertFalse(self.archive_path(root).exists())

    def test_apply_rejects_archive_parent_replaced_by_symlink_after_plan(self) -> None:
        retire = load_retire_module()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "project"
            outside = Path(raw) / "outside"
            root.mkdir()
            outside.mkdir()
            self.make_project(root)
            pdf = root / "paper" / "main.pdf"
            report, readme_body = self.write_hybrid_inputs(root, pdf)
            args = self.retire_args(root, report, readme_body)
            plan = retire.plan_retire(args)
            (root / "archive").symlink_to(outside, target_is_directory=True)

            with self.assertRaises(retire.RetireError):
                retire.apply_retire(args, plan)

            self.assertEqual(list(outside.iterdir()), [])

    def test_copy_regular_file_rejects_fifo_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            fifo = root / "planned.tex"
            target = root / "copied.tex"
            os.mkfifo(fifo)
            code = f"""
import importlib.util
import sys
from pathlib import Path
spec = importlib.util.spec_from_file_location('research_retire_fifo', {str(RETIRE)!r})
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
try:
    module.copy_regular_file(Path(sys.argv[1]), Path(sys.argv[2]))
except module.RetireError:
    raise SystemExit(0)
raise SystemExit(3)
"""
            process = subprocess.Popen(
                [sys.executable, "-c", code, str(fifo), str(target)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            try:
                stdout, _ = process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                self.fail("copy_regular_file blocked on a FIFO")

            self.assertEqual(process.returncode, 0, stdout)
            self.assertFalse(target.exists())

    def test_apply_does_not_replace_destination_created_after_plan(self) -> None:
        retire = load_retire_module()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.make_project(root)
            pdf = root / "paper" / "main.pdf"
            report, readme_body = self.write_hybrid_inputs(root, pdf)
            args = self.retire_args(root, report, readme_body)
            plan = retire.plan_retire(args)
            destination = self.archive_path(root)
            destination.mkdir(parents=True)

            with self.assertRaises(retire.RetireError):
                retire.apply_retire(args, plan)

            self.assertTrue(destination.is_dir())
            self.assertEqual(list(destination.iterdir()), [])

    def test_archive_integrity_covers_readme_and_hybrid_report_semantics(self) -> None:
        retire = load_retire_module()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.make_project(root)
            pdf = root / "paper" / "main.pdf"
            report, readme_body = self.write_hybrid_inputs(root, pdf)
            args = self.retire_args(root, report, readme_body)
            plan = retire.plan_retire(args)
            retire.apply_retire(args, plan)
            archive = self.archive_path(root)

            readme = archive / "README.md"
            readme.write_text(readme.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8")
            self.assertTrue(any("README.md" in item for item in retire.verify_checksums(archive)))

            readme.write_text(
                readme.read_text(encoding="utf-8").removesuffix("tampered\n"),
                encoding="utf-8",
            )
            retire.write_checksums(archive)
            (archive / "VERIFICATION.json").unlink()
            retire.write_checksums(archive)
            self.assertTrue(
                any("VERIFICATION.json" in item for item in retire.verify_checksums(archive))
            )

    def test_archive_integrity_revalidates_report_pdf_binding(self) -> None:
        retire = load_retire_module()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.make_project(root)
            pdf = root / "paper" / "main.pdf"
            report, readme_body = self.write_hybrid_inputs(root, pdf)
            args = self.retire_args(root, report, readme_body)
            plan = retire.plan_retire(args)
            retire.apply_retire(args, plan)
            archive = self.archive_path(root)
            archived_report = archive / "VERIFICATION.json"
            payload = json.loads(archived_report.read_text(encoding="utf-8"))
            payload["submitted_pdf_sha256"] = "0" * 64
            archived_report.write_text(json.dumps(payload), encoding="utf-8")
            retire.write_checksums(archive)

            failures = retire.verify_checksums(archive)
            self.assertTrue(any("SHA-256" in item for item in failures), failures)

    def test_retire_is_dry_run_then_creates_minimal_verified_archive(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.make_project(root)
            archive = self.archive_path(root)

            dry = run_script(
                RETIRE,
                "--root",
                str(root),
                "--slug",
                "course-paper",
                "--date",
                "2026-08-23",
                "--allow-unverified",
                cwd=root,
            )
            self.assertEqual(dry.returncode, 0, dry.stdout)
            self.assertFalse(archive.exists())
            self.assertIn("archive/docs/paper/2026-08-23-course-paper", dry.stdout)

            apply = run_script(
                RETIRE,
                "--root",
                str(root),
                "--slug",
                "course-paper",
                "--date",
                "2026-08-23",
                "--allow-unverified",
                "--apply",
                cwd=root,
            )
            self.assertEqual(apply.returncode, 0, apply.stdout)
            self.assertTrue((archive / "submitted.pdf").is_file())
            self.assertTrue((archive / "source" / "main.tex").is_file())
            self.assertTrue((archive / "source" / "figures" / "plot.png").is_file())
            self.assertTrue((archive / "source" / "banner.png").is_file())
            self.assertFalse((archive / "source" / "main.aux").exists())
            self.assertFalse((archive / "source" / "main-round1.pdf").exists())
            self.assertTrue((root / "paper" / "main.tex").is_file())
            self.assertIn("active source is not deleted", apply.stdout)
            readme = (archive / "README.md").read_text(encoding="utf-8")
            self.assertIn("status: archived", readme)
            self.assertIn("retired: 2026-08-23", readme)

            for line in (archive / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
                expected, rel = line.split("  ", 1)
                actual = hashlib.sha256((archive / rel).read_bytes()).hexdigest()
                self.assertEqual(actual, expected)

            audit = run_script(AUDIT, "--root", str(root), "--full", "--json", cwd=root)
            report = json.loads(audit.stdout)
            self.assertEqual(report["archived_documents"], 1)
            self.assertNotIn(
                "invalid-paper-archive",
                {issue["code"] for issue in report["issues"]},
            )

            duplicate = run_script(
                RETIRE,
                "--root",
                str(root),
                "--slug",
                "course-paper",
                "--date",
                "2026-08-23",
                "--allow-unverified",
                "--apply",
                cwd=root,
            )
            self.assertEqual(duplicate.returncode, 2, duplicate.stdout)
            self.assertIn("拒绝覆盖", duplicate.stdout)

    @unittest.skipUnless(shutil.which("latexmk"), "latexmk is required for isolated compile test")
    def test_retire_compiles_isolated_source_when_latexmk_is_available(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.make_project(root)
            result = run_script(
                RETIRE,
                "--root",
                str(root),
                "--slug",
                "compiled-paper",
                "--date",
                "2026-08-23",
                "--apply",
                cwd=root,
            )
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn("verification: passed", result.stdout)
            readme = self.archive_path(root, "compiled-paper") / "README.md"
            self.assertIn("verification: passed", readme.read_text(encoding="utf-8"))

    def test_retire_rejects_a_github_oversized_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.make_project(root)
            oversized = root / "paper" / "figures" / "large.png"
            with oversized.open("wb") as handle:
                handle.seek(100 * 1024 * 1024 - 1)
                handle.write(b"x")
            result = run_script(
                RETIRE,
                "--root",
                str(root),
                "--slug",
                "course-paper",
                cwd=root,
            )
            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertIn("100 MiB", result.stdout)

    def test_retire_refuses_pdf_only_archive(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / "paper").mkdir()
            (root / "paper" / "main.pdf").write_bytes(b"%PDF-1.4\nsubmitted\n")
            result = run_script(
                RETIRE,
                "--root",
                str(root),
                "--slug",
                "course-paper",
                cwd=root,
            )
            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertIn("未找到可归档源码", result.stdout)

    def test_retire_failure_is_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.make_project(root)
            result = run_script(
                RETIRE,
                "--root",
                str(root),
                "--slug",
                "course-paper",
                "--date",
                "2026-08-23",
                "--main-tex",
                "missing.tex",
                "--allow-unverified",
                "--apply",
                cwd=root,
            )
            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertIn("主 TeX 不存在", result.stdout)
            self.assertFalse(self.archive_path(root).exists())
            paper_archive = root / "archive" / "docs" / "paper"
            self.assertFalse(any(paper_archive.glob(".course-paper-*")))

    def test_retire_rejects_date_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "project"
            root.mkdir()
            self.make_project(root)
            escaped = root.parent / "escaped-course-paper"
            result = run_script(
                RETIRE,
                "--root",
                str(root),
                "--slug",
                "course-paper",
                "--date",
                "../../../escaped",
                "--apply",
                cwd=root,
            )
            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertIn("YYYY-MM-DD", result.stdout)
            self.assertFalse(escaped.exists())

    def test_retire_refuses_gitignored_archive_destination(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.make_project(root)
            (root / ".gitignore").write_text("/archive/\n", encoding="utf-8")
            result = run_script(
                RETIRE,
                "--root",
                str(root),
                "--slug",
                "course-paper",
                "--apply",
                cwd=root,
            )
            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertIn("Git 忽略", result.stdout)
            self.assertFalse((root / "archive" / "docs" / "paper").exists())

    def test_retire_includes_explicit_top_level_pdf_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.make_project(root)
            required = root / "paper" / "required.pdf"
            required.write_bytes(b"%PDF-1.4\nfigure\n")
            result = run_script(
                RETIRE,
                "--root",
                str(root),
                "--slug",
                "course-paper",
                "--date",
                "2026-08-23",
                "--include",
                "required.pdf",
                "--allow-unverified",
                "--apply",
                cwd=root,
            )
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertTrue((self.archive_path(root) / "source" / "required.pdf").is_file())


class InstallerTests(unittest.TestCase):
    def test_local_install_is_an_exact_mirror_and_does_not_edit_settings(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            claude = root / "claude"
            codex = root / "codex"
            for target in (claude / "skills" / "research", codex / "skills" / "research"):
                (target / "references").mkdir(parents=True)
                (target / "scripts").mkdir()
                (target / "references" / "stale.md").write_text("stale", encoding="utf-8")
                (target / "scripts" / "stale.py").write_text("stale", encoding="utf-8")
            settings = claude / "settings.json"
            original_settings = '{"hooks":{"Stop":[{"hooks":[{"command":"docs-hook.sh"}]}]}}\n'
            settings.write_text(original_settings, encoding="utf-8")

            env = os.environ.copy()
            env["CLAUDE_CONFIG_DIR"] = str(claude)
            env["CODEX_HOME"] = str(codex)
            result = subprocess.run(
                ["bash", str(INSTALL), "--local"],
                cwd=root,
                env=env,
                text=True,
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertEqual(settings.read_text(encoding="utf-8"), original_settings)
            self.assertFalse((root / "CLAUDE.md").exists())
            self.assertFalse((root / "AGENTS.md").exists())

            expected = {Path("SKILL.md")}
            expected.update(Path("references") / path.name for path in (REPO / "references").glob("*.md"))
            expected.update(Path("scripts") / path.name for path in (REPO / "scripts").glob("*.py"))
            for target in (claude / "skills" / "research", codex / "skills" / "research"):
                actual = {path.relative_to(target) for path in target.rglob("*") if path.is_file()}
                self.assertEqual(actual, expected)
                for rel in expected:
                    self.assertEqual((target / rel).read_bytes(), (REPO / rel).read_bytes())

    def test_install_preflight_keeps_both_existing_targets_unchanged_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            claude = root / "claude"
            codex = root / "codex"
            claude_target = claude / "skills" / "research"
            codex_target = codex / "skills" / "research"
            claude_target.mkdir(parents=True)
            marker = claude_target / "keep.txt"
            marker.write_text("original\n", encoding="utf-8")
            codex_target.parent.mkdir(parents=True)
            codex_target.write_text("not a directory\n", encoding="utf-8")

            env = os.environ.copy()
            env["CLAUDE_CONFIG_DIR"] = str(claude)
            env["CODEX_HOME"] = str(codex)
            result = subprocess.run(
                ["bash", str(INSTALL), "--local"],
                cwd=root,
                env=env,
                text=True,
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertEqual(marker.read_text(encoding="utf-8"), "original\n")
            self.assertEqual(codex_target.read_text(encoding="utf-8"), "not a directory\n")

    def test_install_rolls_back_a_partial_second_target_move(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            claude = root / "claude"
            codex = root / "codex"
            claude_target = claude / "skills" / "research"
            codex_target = codex / "skills" / "research"
            for target, marker_text in (
                (claude_target, "claude-original\n"),
                (codex_target, "codex-original\n"),
            ):
                target.mkdir(parents=True)
                (target / "keep.txt").write_text(marker_text, encoding="utf-8")

            fake_bin = root / "fake-bin"
            fake_bin.mkdir()
            fake_mv = fake_bin / "mv"
            fake_mv.write_text(
                """#!/bin/bash
source_path="$1"
target_path="$2"
if [[ "$target_path" == "$FAIL_TARGET" && "$source_path" == *research-skill-install* ]]; then
  mkdir -p "$target_path"
  printf 'partial\n' > "$target_path/partial.txt"
  exit 1
fi
exec /bin/mv "$@"
""",
                encoding="utf-8",
            )
            fake_mv.chmod(0o755)

            env = os.environ.copy()
            env["CLAUDE_CONFIG_DIR"] = str(claude)
            env["CODEX_HOME"] = str(codex)
            env["FAIL_TARGET"] = str(codex_target)
            env["PATH"] = f"{fake_bin}:{env['PATH']}"
            result = subprocess.run(
                ["bash", str(INSTALL), "--local"],
                cwd=root,
                env=env,
                text=True,
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertEqual(
                (claude_target / "keep.txt").read_text(encoding="utf-8"),
                "claude-original\n",
            )
            self.assertEqual(
                (codex_target / "keep.txt").read_text(encoding="utf-8"),
                "codex-original\n",
            )
            self.assertFalse((codex_target / "partial.txt").exists())
            self.assertFalse(any(codex_target.glob("research.backup.*")))


if __name__ == "__main__":
    unittest.main()
