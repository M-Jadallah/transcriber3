from __future__ import annotations

import io
import stat
import tempfile
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.formatting.config import FormattingConfig
from app.formatting.skills import (
    SkillArchiveError,
    install_skill_archive,
    materialize_verified_skill,
)


class SkillArchiveTests(unittest.TestCase):
    def config(self, root: Path) -> FormattingConfig:
        return FormattingConfig(
            root=root,
            execution_root=root.parent / "execution-exchange",
            exports_root=root.parent / "exports",
            opencode_url="http://localhost:4096",
            opencode_control_url="http://localhost:4097",
            opencode_username="opencode",
            opencode_password="secret",
            default_model="openai/test",
            default_reasoning="high",
            task_timeout_seconds=60,
            skill_max_archive_bytes=5_000_000,
            skill_max_files=100,
            skill_max_unpacked_bytes=10_000_000,
            output_max_files=10,
            output_max_total_bytes=10_000_000,
            output_max_single_file_bytes=5_000_000,
        )

    def make_zip(self, name: str = "lesson-format", nested: bool = True) -> bytes:
        prefix = f"{name}/" if nested else ""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(
                f"{prefix}SKILL.md",
                (
                    "---\n"
                    f"name: {name}\n"
                    "description: Format a lesson transcript\n"
                    "---\n\n"
                    "# Workflow\n"
                ),
            )
            archive.writestr(f"{prefix}references/rules.md", "rules")
        return buffer.getvalue()

    def test_valid_nested_skill_is_versioned(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            installed = install_skill_archive(
                self.make_zip(),
                self.config(Path(temp)),
            )
            self.assertTrue((installed.extracted_path / "SKILL.md").is_file())
            self.assertTrue((installed.extracted_path / "references" / "rules.md").is_file())
            self.assertTrue(installed.archive_path.is_file())

    def test_root_skill_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            installed = install_skill_archive(
                self.make_zip(nested=False),
                self.config(Path(temp)),
            )
            self.assertEqual(installed.name, "lesson-format")
            self.assertTrue((installed.extracted_path / "SKILL.md").is_file())

    def test_same_archive_reuses_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            config = self.config(Path(temp))
            blob = self.make_zip()
            first = install_skill_archive(blob, config)
            second = install_skill_archive(blob, config)
            self.assertEqual(first.sha256, second.sha256)
            self.assertEqual(first.extracted_path, second.extracted_path)

    def test_concurrent_identical_archives_reuse_atomic_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            config = self.config(Path(temp))
            blob = self.make_zip()
            with ThreadPoolExecutor(max_workers=4) as executor:
                installed = list(
                    executor.map(lambda _: install_skill_archive(blob, config), range(8))
                )
            self.assertEqual({item.sha256 for item in installed}, {installed[0].sha256})
            self.assertEqual(
                {item.extracted_path for item in installed},
                {installed[0].extracted_path},
            )
            self.assertTrue((installed[0].extracted_path / "SKILL.md").is_file())

    def test_existing_archive_is_verified_before_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            config = self.config(Path(temp))
            blob = self.make_zip()
            installed = install_skill_archive(blob, config)
            installed.archive_path.write_bytes(b"corrupt")
            repaired = install_skill_archive(blob, config)
            self.assertEqual(repaired.archive_path.read_bytes(), blob)

    def test_existing_version_is_verified_before_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            config = self.config(Path(temp))
            blob = self.make_zip()
            installed = install_skill_archive(blob, config)
            (installed.extracted_path / "SKILL.md").write_text("changed", encoding="utf-8")
            repaired = install_skill_archive(blob, config)
            self.assertIn(
                "# Workflow",
                (repaired.extracted_path / "SKILL.md").read_text(encoding="utf-8"),
            )

    def test_runtime_materialization_uses_verified_archive_not_extracted_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            config = self.config(Path(temp).resolve() / "formatting")
            installed = install_skill_archive(self.make_zip(), config)
            (installed.extracted_path / "SKILL.md").write_text(
                "mutated extracted tree",
                encoding="utf-8",
            )
            destination = (
                config.execution_root
                / "job-g1"
                / ".opencode"
                / "skills"
                / installed.name
            )
            destination.parent.mkdir(parents=True)

            materialize_verified_skill(
                config,
                archive_path=installed.archive_path,
                expected_sha256=installed.sha256,
                expected_name=installed.name,
                expected_slug=installed.slug,
                destination=destination,
            )

            self.assertIn(
                "# Workflow",
                (destination / "SKILL.md").read_text(encoding="utf-8"),
            )

    def test_runtime_materialization_rejects_record_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp).resolve()
            config = self.config(base / "formatting")
            installed = install_skill_archive(self.make_zip(), config)
            destination = (
                config.execution_root
                / "job-g1"
                / ".opencode"
                / "skills"
                / installed.name
            )
            destination.parent.mkdir(parents=True)

            with self.assertRaises(SkillArchiveError):
                materialize_verified_skill(
                    config,
                    archive_path=base / "outside.zip",
                    expected_sha256=installed.sha256,
                    expected_name=installed.name,
                    expected_slug=installed.slug,
                    destination=destination,
                )

    def test_path_traversal_is_rejected(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("../SKILL.md", "bad")
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(SkillArchiveError):
                install_skill_archive(buffer.getvalue(), self.config(Path(temp)))

    def test_multiple_skill_files_are_rejected(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(
                "one/SKILL.md",
                "---\nname: one\ndescription: First skill\n---\n",
            )
            archive.writestr(
                "two/SKILL.md",
                "---\nname: two\ndescription: Second skill\n---\n",
            )
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(SkillArchiveError):
                install_skill_archive(buffer.getvalue(), self.config(Path(temp)))

    def test_symlink_is_rejected(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(
                "safe/SKILL.md",
                "---\nname: safe\ndescription: Safe skill\n---\n",
            )
            link = zipfile.ZipInfo("safe/link")
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(link, "target")
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(SkillArchiveError):
                install_skill_archive(buffer.getvalue(), self.config(Path(temp)))

    def test_invalid_name_is_rejected(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(
                "SKILL.md",
                "---\nname: Invalid Name\ndescription: Invalid\n---\n",
            )
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(SkillArchiveError):
                install_skill_archive(buffer.getvalue(), self.config(Path(temp)))


    def test_nested_folder_must_match_skill_name(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(
                "wrong-folder/SKILL.md",
                "---\nname: right-name\ndescription: Valid skill\n---\n",
            )
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(SkillArchiveError):
                install_skill_archive(buffer.getvalue(), self.config(Path(temp)))

    def test_metadata_values_must_be_strings(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(
                "safe/SKILL.md",
                (
                    "---\n"
                    "name: safe\n"
                    "description: Safe skill\n"
                    "metadata:\n"
                    "  version: 2\n"
                    "---\n"
                ),
            )
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(SkillArchiveError):
                install_skill_archive(buffer.getvalue(), self.config(Path(temp)))

    def test_duplicate_case_insensitive_path_is_rejected(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(
                "safe/SKILL.md",
                "---\nname: safe\ndescription: Safe skill\n---\n",
            )
            archive.writestr("safe/RULES.md", "one")
            archive.writestr("safe/rules.md", "two")
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(SkillArchiveError):
                install_skill_archive(buffer.getvalue(), self.config(Path(temp)))


if __name__ == "__main__":
    unittest.main()
