from __future__ import annotations

import hashlib
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
DELIVERABLE = REPO / "scripts" / "deliverable.py"
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

    def test_full_audit_rejects_broken_deliverable_package(self) -> None:
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
            broken = root / "docs" / "deliverables" / "broken"
            broken.mkdir(parents=True)
            (broken / "README.md").write_text("---\nstatus: submitted\n---\n", encoding="utf-8")

            result = run_script(AUDIT, "--root", str(root), "--full", "--json", cwd=root)
            self.assertEqual(result.returncode, 0, result.stdout)
            report = json.loads(result.stdout)
            codes = {issue["code"] for issue in report["issues"]}
            self.assertIn("invalid-deliverable-package", codes)
            self.assertIn("deliverable-not-tracked", codes)
            self.assertIn("legacy-agents-pointer", codes)
            self.assertEqual(report["active_deliverables"], 1)


class DeliverableTests(unittest.TestCase):
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

    def test_freeze_is_dry_run_then_creates_minimal_verified_package(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.make_project(root)

            dry = run_script(
                DELIVERABLE,
                "freeze",
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
            package = root / "docs" / "deliverables" / "course-paper"
            self.assertFalse(package.exists())

            apply = run_script(
                DELIVERABLE,
                "freeze",
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
            self.assertTrue((package / "submitted.pdf").is_file())
            self.assertTrue((package / "source" / "main.tex").is_file())
            self.assertTrue((package / "source" / "figures" / "plot.png").is_file())
            self.assertTrue((package / "source" / "banner.png").is_file())
            self.assertFalse((package / "source" / "main.aux").exists())
            self.assertFalse((package / "source" / "main-round1.pdf").exists())
            self.assertIn("untracked", apply.stdout)

            for line in (package / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
                expected, rel = line.split("  ", 1)
                actual = hashlib.sha256((package / rel).read_bytes()).hexdigest()
                self.assertEqual(actual, expected)

            duplicate = run_script(
                DELIVERABLE,
                "freeze",
                "--root",
                str(root),
                "--slug",
                "course-paper",
                "--allow-unverified",
                "--apply",
                cwd=root,
            )
            self.assertEqual(duplicate.returncode, 2, duplicate.stdout)
            self.assertIn("拒绝覆盖", duplicate.stdout)

    @unittest.skipUnless(shutil.which("latexmk"), "latexmk is required for isolated compile test")
    def test_freeze_compiles_isolated_source_when_latexmk_is_available(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.make_project(root)
            result = run_script(
                DELIVERABLE,
                "freeze",
                "--root",
                str(root),
                "--slug",
                "compiled-paper",
                "--apply",
                cwd=root,
            )
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn("verification: passed", result.stdout)
            readme = root / "docs" / "deliverables" / "compiled-paper" / "README.md"
            self.assertIn("verification: passed", readme.read_text(encoding="utf-8"))

    def test_freeze_rejects_a_github_oversized_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.make_project(root)
            oversized = root / "paper" / "figures" / "large.png"
            with oversized.open("wb") as handle:
                handle.seek(100 * 1024 * 1024 - 1)
                handle.write(b"x")
            result = run_script(
                DELIVERABLE,
                "freeze",
                "--root",
                str(root),
                "--slug",
                "course-paper",
                "--allow-unverified",
                cwd=root,
            )
            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertIn("100 MiB", result.stdout)

    def test_freeze_refuses_pdf_only_package(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / "paper").mkdir()
            (root / "paper" / "main.pdf").write_bytes(b"%PDF-1.4\nsubmitted\n")
            result = run_script(
                DELIVERABLE,
                "freeze",
                "--root",
                str(root),
                "--slug",
                "course-paper",
                cwd=root,
            )
            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertIn("未找到可冻结源码", result.stdout)

    def test_retire_refuses_uncovered_source_then_archives_without_deleting_paper(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.make_project(root)
            freeze = run_script(
                DELIVERABLE,
                "freeze",
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
            self.assertEqual(freeze.returncode, 0, freeze.stdout)

            new_source = root / "paper" / "appendix.tex"
            new_source.write_text("new", encoding="utf-8")
            refused = run_script(
                DELIVERABLE,
                "retire",
                "--root",
                str(root),
                "--slug",
                "course-paper",
                "--date",
                "2026-09-01",
                cwd=root,
            )
            self.assertEqual(refused.returncode, 2, refused.stdout)
            self.assertIn("appendix.tex", refused.stdout)

            new_source.unlink()
            retired = run_script(
                DELIVERABLE,
                "retire",
                "--root",
                str(root),
                "--slug",
                "course-paper",
                "--date",
                "2026-09-01",
                "--apply",
                cwd=root,
            )
            self.assertEqual(retired.returncode, 0, retired.stdout)
            archive = root / "archive" / "docs" / "2026-09-01-course-paper"
            self.assertTrue(archive.is_dir())
            self.assertFalse((root / "docs" / "deliverables" / "course-paper").exists())
            self.assertTrue((root / "paper" / "main.tex").is_file())
            self.assertIn("status: archived", (archive / "README.md").read_text(encoding="utf-8"))

    def test_retire_refuses_checksum_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.make_project(root)
            freeze = run_script(
                DELIVERABLE,
                "freeze",
                "--root",
                str(root),
                "--slug",
                "course-paper",
                "--allow-unverified",
                "--apply",
                cwd=root,
            )
            self.assertEqual(freeze.returncode, 0, freeze.stdout)
            package = root / "docs" / "deliverables" / "course-paper"
            (package / "submitted.pdf").write_bytes(b"%PDF-1.4\ntampered\n")
            retired = run_script(
                DELIVERABLE,
                "retire",
                "--root",
                str(root),
                "--slug",
                "course-paper",
                cwd=root,
            )
            self.assertEqual(retired.returncode, 2, retired.stdout)
            self.assertIn("checksum mismatch", retired.stdout)

    def test_retire_rejects_date_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "project"
            root.mkdir()
            self.make_project(root)
            freeze = run_script(
                DELIVERABLE,
                "freeze",
                "--root",
                str(root),
                "--slug",
                "course-paper",
                "--allow-unverified",
                "--apply",
                cwd=root,
            )
            self.assertEqual(freeze.returncode, 0, freeze.stdout)
            escaped = root.parent / "escaped-course-paper"
            retired = run_script(
                DELIVERABLE,
                "retire",
                "--root",
                str(root),
                "--slug",
                "course-paper",
                "--date",
                "../../../escaped",
                "--apply",
                cwd=root,
            )
            self.assertEqual(retired.returncode, 2, retired.stdout)
            self.assertIn("YYYY-MM-DD", retired.stdout)
            self.assertTrue((root / "docs" / "deliverables" / "course-paper").is_dir())
            self.assertFalse(escaped.exists())

    def test_retire_refuses_unchecksummed_package_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.make_project(root)
            freeze = run_script(
                DELIVERABLE,
                "freeze",
                "--root",
                str(root),
                "--slug",
                "course-paper",
                "--allow-unverified",
                "--apply",
                cwd=root,
            )
            self.assertEqual(freeze.returncode, 0, freeze.stdout)
            package = root / "docs" / "deliverables" / "course-paper"
            (package / "source" / "injected.tex").write_text("injected", encoding="utf-8")
            retired = run_script(
                DELIVERABLE,
                "retire",
                "--root",
                str(root),
                "--slug",
                "course-paper",
                cwd=root,
            )
            self.assertEqual(retired.returncode, 2, retired.stdout)
            self.assertIn("uncovered package file", retired.stdout)

    def test_retire_refuses_missing_pdf_even_if_manifest_line_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.make_project(root)
            freeze = run_script(
                DELIVERABLE,
                "freeze",
                "--root",
                str(root),
                "--slug",
                "course-paper",
                "--allow-unverified",
                "--apply",
                cwd=root,
            )
            self.assertEqual(freeze.returncode, 0, freeze.stdout)
            package = root / "docs" / "deliverables" / "course-paper"
            (package / "submitted.pdf").unlink()
            checksum_file = package / "SHA256SUMS"
            lines = checksum_file.read_text(encoding="utf-8").splitlines()
            checksum_file.write_text(
                "\n".join(line for line in lines if not line.endswith("  submitted.pdf")) + "\n",
                encoding="utf-8",
            )
            retired = run_script(
                DELIVERABLE,
                "retire",
                "--root",
                str(root),
                "--slug",
                "course-paper",
                cwd=root,
            )
            self.assertEqual(retired.returncode, 2, retired.stdout)
            self.assertIn("submitted.pdf missing", retired.stdout)
            self.assertTrue(package.is_dir())

    def test_retire_rechecks_explicitly_included_source(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.make_project(root)
            required = root / "paper" / "required.pdf"
            required.write_bytes(b"%PDF-1.4\nfigure\n")
            freeze = run_script(
                DELIVERABLE,
                "freeze",
                "--root",
                str(root),
                "--slug",
                "course-paper",
                "--include",
                "required.pdf",
                "--allow-unverified",
                "--apply",
                cwd=root,
            )
            self.assertEqual(freeze.returncode, 0, freeze.stdout)
            required.write_bytes(b"%PDF-1.4\nchanged\n")
            retired = run_script(
                DELIVERABLE,
                "retire",
                "--root",
                str(root),
                "--slug",
                "course-paper",
                cwd=root,
            )
            self.assertEqual(retired.returncode, 2, retired.stdout)
            self.assertIn("required.pdf", retired.stdout)

    def test_retire_refuses_gitignored_archive_destination(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.make_project(root)
            (root / ".gitignore").write_text("/archive/\n", encoding="utf-8")
            freeze = run_script(
                DELIVERABLE,
                "freeze",
                "--root",
                str(root),
                "--slug",
                "course-paper",
                "--allow-unverified",
                "--apply",
                cwd=root,
            )
            self.assertEqual(freeze.returncode, 0, freeze.stdout)
            retired = run_script(
                DELIVERABLE,
                "retire",
                "--root",
                str(root),
                "--slug",
                "course-paper",
                "--apply",
                cwd=root,
            )
            self.assertEqual(retired.returncode, 2, retired.stdout)
            self.assertIn("Git 忽略", retired.stdout)
            self.assertTrue((root / "docs" / "deliverables" / "course-paper").is_dir())

    def test_retire_decodes_quoted_source_path_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.make_project(root)
            source = root / 'paper "draft"'
            (root / "paper").rename(source)
            freeze = run_script(
                DELIVERABLE,
                "freeze",
                "--root",
                str(root),
                "--source",
                source.name,
                "--slug",
                "course-paper",
                "--allow-unverified",
                "--apply",
                cwd=root,
            )
            self.assertEqual(freeze.returncode, 0, freeze.stdout)
            (source / "main.tex").write_text("changed", encoding="utf-8")
            retired = run_script(
                DELIVERABLE,
                "retire",
                "--root",
                str(root),
                "--slug",
                "course-paper",
                cwd=root,
            )
            self.assertEqual(retired.returncode, 2, retired.stdout)
            self.assertIn("main.tex", retired.stdout)


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


if __name__ == "__main__":
    unittest.main()
