from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from scripts import apply_formatting_integration as integration_tool
from scripts.apply_formatting_integration import (
    MIGRATION_PATH,
    NEW_SOURCE_FILES,
    ORIGINAL_BASELINE_FILES,
    ROOT,
    IntegrationError,
    apply,
    current_alembic_head,
    patch_backend_requirements,
    render_migration,
    validate_project,
    validate_source_assets,
)


class ApplyIntegrationTests(unittest.TestCase):
    def create_project(self, root: Path) -> None:
        files = {
            "backend/app/main.py": (
                "from fastapi import FastAPI\n"
                "from app.api.bulk_exports import router as bulk_exports_router\n"
                "from app.api.routes import router\n"
                "app = FastAPI()\n"
                "app.include_router(router)\n"
                "app.include_router(bulk_exports_router)\n"
            ),
            "backend/requirements.txt": "fastapi>=0.100\ncelery>=5\n",
            "backend/app/celery_app.py": "class Dummy:\n    pass\ncelery_app = Dummy()\n",
            "backend/app/db_wait.py": "# original database wait module\n",
            "backend/app/scheduler.py": "# original scheduler module\n",
            "backend/app/core/db.py": "# original database module\n",
            "backend/app/core/models.py": "# original model module\n",
            "backend/app/core/security.py": "# original security module\n",
            "backend/app/services/export_service.py": "# original export service\n",
            "backend/app/services/log_service.py": "# original log service\n",
            "backend/alembic/versions/0001_base.py": (
                'revision = "base1"\n'
                "down_revision = None\n"
            ),
            "backend/alembic.ini": "original alembic config\n",
            "backend/alembic/env.py": "original env\n",
            "backend/alembic/script.py.mako": "original template\n",
            "backend/Dockerfile": "original backend image\n",
            "frontend/Dockerfile": "original frontend image\n",
            "frontend/package.json": '{"scripts":{"build":"vite build"}}\n',
            "frontend/src/api.ts": "export const api = {};\n",
            "frontend/src/hooks/useFetch.ts": "export function useFetch() {}\n",
            "frontend/src/App.tsx": (
                "import { Route, Routes } from 'react-router-dom';\n"
                "import JobDetail from './pages/JobDetail';\n"
                "import Jobs from './pages/Jobs';\n"
                "import Workers from './pages/Workers';\n"
                "export default function App(){return (<Routes>\n"
                "        <Route path=\"jobs\" element={<Jobs />} />\n"
                "        <Route path=\"jobs/:id\" element={<JobDetail />} />\n"
                "</Routes>)}\n"
            ),
            "frontend/src/pages/Jobs.tsx": (
                "import { useEffect, useState } from 'react';\n"
                "import StatusBadge from '../components/StatusBadge';\n"
                "import './Jobs.bulk-download.css';\n"
                "export default function Jobs(){\n"
                "  const [message, setMessage] = useState('');\n"
                "  const [selected, setSelected] = useState<string[]>([]);\n"
                "  const data: any = {items: []};\n"
                "  useEffect(() => {\n"
                "    const visible = new Set(data?.items.map((item) => item.id) ?? []);\n"
                "    setSelected((current) => current.filter((id) => visible.has(id)));\n"
                "  }, [data]);\n"
                "  return (<table><thead><tr>\n"
                "                <th className=\"download-column\">التنزيل</th>\n"
                "  </tr></thead><tbody>{data.items.map((job: any) => (<tr key={job.id}>\n"
                "                  <td>{new Date(job.created_at).toLocaleDateString('ar-JO')}</td>\n"
                "                  <td className=\"download-column\">\n"
                "                    download\n"
                "                  </td>\n"
                "  </tr>))}<tr><td colSpan={9}>empty</td></tr></tbody></table>);\n"
                "}\n"
            ),
            "frontend/src/pages/Settings.tsx": (
                "export default function Settings(){\n"
                "  return (<><section>existing</section></>);\n"
                "}\n"
            ),
            "frontend/src/components/ProtectedLayout.tsx": (
                "export default function ProtectedLayout(){\n"
                "  return (<div><nav><a href='/'>home</a></nav></div>);\n"
                "}\n"
            ),
            "docker-compose.yml": "services:\n  api:\n    image: example\n",
        }
        for relative, content in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    def test_apply_resolves_migration_and_backs_up(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            self.create_project(project)
            messages = apply(project, acknowledge_unverified_base=True)
            migration = (
                project
                / "backend/alembic/versions/20260801_0100_add_formatting_subsystem.py"
            ).read_text(encoding="utf-8")
            self.assertIn('down_revision = "base1"', migration)
            self.assertNotIn("REPLACE_WITH_CURRENT_HEAD", migration)
            self.assertTrue((project / "backend/app/formatting/tasks.py").is_file())
            self.assertTrue(
                (project / "backend/app/formatting/outbox_dispatcher.py").is_file()
            )
            self.assertTrue((project / "frontend/src/pages/Skills.tsx").is_file())
            self.assertTrue(
                (
                    project
                    / "tools/formatting-integration/verify_coolify_bundle.py"
                ).is_file()
            )
            self.assertTrue(
                (
                    project
                    / "tools/formatting-integration/formatting_integration_tree.py"
                ).is_file()
            )
            self.assertFalse((project / "docker-compose.formatting.yml").exists())
            self.assertEqual(
                (project / "docker-compose.yml").read_bytes(),
                (ROOT / "docker-compose.yml").read_bytes(),
            )
            self.assertEqual(
                (project / "backend/Dockerfile").read_bytes(),
                (ROOT / "backend/Dockerfile").read_bytes(),
            )
            self.assertEqual(
                (project / "backend/alembic.ini").read_text(encoding="utf-8"),
                "original alembic config\n",
            )
            self.assertEqual(
                (project / "backend/alembic/env.py").read_text(encoding="utf-8"),
                "original env\n",
            )
            self.assertEqual(
                (project / "backend/alembic/script.py.mako").read_text(encoding="utf-8"),
                "original template\n",
            )
            self.assertEqual(
                (project / "backend/app/db_wait.py").read_text(encoding="utf-8"),
                "# original database wait module\n",
            )
            self.assertEqual(
                (project / "backend/app/scheduler.py").read_text(encoding="utf-8"),
                "# original scheduler module\n",
            )
            self.assertEqual(
                (project / "backend/app/core/db.py").read_text(encoding="utf-8"),
                "# original database module\n",
            )
            self.assertEqual(
                (project / "backend/app/core/models.py").read_text(encoding="utf-8"),
                "# original model module\n",
            )
            self.assertEqual(
                (project / "backend/app/core/security.py").read_text(encoding="utf-8"),
                "# original security module\n",
            )
            self.assertEqual(
                (project / "backend/app/services/export_service.py").read_text(encoding="utf-8"),
                "# original export service\n",
            )
            self.assertEqual(
                (project / "backend/app/services/log_service.py").read_text(encoding="utf-8"),
                "# original log service\n",
            )
            self.assertEqual(
                (project / "frontend/package.json").read_text(encoding="utf-8"),
                '{"scripts":{"build":"vite build"}}\n',
            )
            self.assertEqual(
                (project / "frontend/src/api.ts").read_text(encoding="utf-8"),
                "export const api = {};\n",
            )
            self.assertEqual(
                (project / "frontend/src/hooks/useFetch.ts").read_text(encoding="utf-8"),
                "export function useFetch() {}\n",
            )
            requirements = (project / "backend/requirements.txt").read_text(encoding="utf-8")
            self.assertIn("fastapi>=0.100", requirements)
            self.assertIn("python-docx>=1.1,<2", requirements)
            self.assertIn("FormattingSettingsPanel", (project / "frontend/src/pages/Settings.tsx").read_text())
            self.assertIn("FormattingNavigationLink", (project / "frontend/src/components/ProtectedLayout.tsx").read_text())
            backups = list(project.glob(".formatting-integration-backup-*"))
            self.assertEqual(len(backups), 1)
            self.assertTrue((backups[0] / "backend/app/main.py").is_file())
            metadata = (backups[0] / "integration-backup.json").read_text(
                encoding="utf-8"
            )
            self.assertIn('"created_files"', metadata)
            self.assertIn('"commit_completed": true', metadata)
            self.assertEqual(
                (backups[0] / "backend/Dockerfile").read_text(encoding="utf-8"),
                "original backend image\n",
            )
            self.assertTrue(any("Deepgram" in message for message in messages))
            self.assertTrue(any("قبل Verifier" in message for message in messages))

    def test_bundle_and_compose_validation_require_dispatcher(self) -> None:
        dispatcher = Path("backend/app/formatting/outbox_dispatcher.py")
        self.assertIn(dispatcher, NEW_SOURCE_FILES)
        migration_text = (ROOT / MIGRATION_PATH).read_text(encoding="utf-8")
        compose_without_dispatcher = (
            "services:\n"
            "  api: {}\n"
            "  opencode-runtime: {}\n"
            "  formatting-worker: {}\n"
            "  gateway: {}\n"
        )

        def source_text(boundary: Path, path: Path) -> str:
            if path == ROOT / MIGRATION_PATH:
                return migration_text
            if path == ROOT / "docker-compose.yml":
                return compose_without_dispatcher
            return path.read_text(encoding="utf-8")

        with mock.patch(
            "scripts.apply_formatting_integration.read_text",
            side_effect=source_text,
        ):
            with self.assertRaisesRegex(IntegrationError, "formatting-dispatcher"):
                validate_source_assets(ROOT)

    def test_requirement_merge_accepts_an_exact_text_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            requirements = project / "backend/requirements.txt"
            formatting = project / "backend/requirements-formatting.txt"
            formatting.parent.mkdir(parents=True)
            requirements.write_text(
                "fastapi>=0.100\npython-docx>=1.1.2,<2\n",
                encoding="utf-8",
            )
            formatting.write_text("python-docx>=1.1.2,<2\n", encoding="utf-8")

            message = patch_backend_requirements(
                project, project / ".preflight-backup"
            )

            self.assertIn("موجودة مسبقًا", message)
            self.assertEqual(
                requirements.read_text(encoding="utf-8").count(
                    "python-docx>=1.1.2,<2"
                ),
                1,
            )

    def test_requirement_merge_rejects_normalized_name_constraint_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            requirements = project / "backend/requirements.txt"
            formatting = project / "backend/requirements-formatting.txt"
            formatting.parent.mkdir(parents=True)
            original = "fastapi>=0.100\nPython_Docx>=1.0,<2\n"
            requirements.write_text(original, encoding="utf-8")
            formatting.write_text("python-docx>=1.1.2,<2\n", encoding="utf-8")

            with self.assertRaisesRegex(IntegrationError, "قيدًا موحدًا يدويًا"):
                patch_backend_requirements(
                    project, project / ".preflight-backup"
                )

            self.assertEqual(requirements.read_text(encoding="utf-8"), original)
            self.assertFalse((project / ".preflight-backup").exists())

    def test_project_preflight_requires_compose_runtime_modules(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            self.create_project(project)
            (project / "backend/app/db_wait.py").unlink()
            (project / "backend/app/scheduler.py").unlink()

            with self.assertRaises(IntegrationError) as raised:
                validate_project(project)
            self.assertIn("db_wait.py", str(raised.exception))
            self.assertIn("scheduler.py", str(raised.exception))

    def test_project_preflight_requires_complete_original_baseline(self) -> None:
        expected = {
            Path("backend/alembic.ini"),
            Path("backend/alembic/env.py"),
            Path("backend/alembic/script.py.mako"),
            Path("backend/app/core/db.py"),
            Path("backend/app/core/models.py"),
            Path("backend/app/core/security.py"),
            Path("backend/app/services/export_service.py"),
            Path("backend/app/services/log_service.py"),
            Path("backend/app/main.py"),
            Path("backend/app/celery_app.py"),
            Path("backend/app/db_wait.py"),
            Path("backend/app/scheduler.py"),
            Path("frontend/package.json"),
            Path("frontend/src/App.tsx"),
            Path("frontend/src/api.ts"),
            Path("frontend/src/hooks/useFetch.ts"),
            Path("frontend/src/pages/Jobs.tsx"),
        }
        self.assertTrue(expected.issubset(set(ORIGINAL_BASELINE_FILES)))
        self.assertTrue(expected.isdisjoint(set(NEW_SOURCE_FILES)))

        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            self.create_project(project)
            for relative in (
                "backend/alembic/env.py",
                "backend/app/core/models.py",
                "backend/app/core/security.py",
                "backend/app/services/export_service.py",
                "backend/app/services/log_service.py",
                "frontend/package.json",
                "frontend/src/api.ts",
                "frontend/src/hooks/useFetch.ts",
            ):
                (project / relative).unlink()

            with self.assertRaises(IntegrationError) as raised:
                validate_project(project)
            message = str(raised.exception)
            self.assertIn("backend/alembic/env.py", message)
            self.assertIn("backend/app/core/models.py", message)
            self.assertIn("backend/app/core/security.py", message)
            self.assertIn("backend/app/services/export_service.py", message)
            self.assertIn("backend/app/services/log_service.py", message)
            self.assertIn("frontend/package.json", message)
            self.assertIn("frontend/src/hooks/useFetch.ts", message)

    def test_unsafe_frontend_shape_fails_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            self.create_project(project)
            jobs = project / "frontend/src/pages/Jobs.tsx"
            jobs.write_text("export default function Jobs(){return null}\n", encoding="utf-8")
            original_main = (project / "backend/app/main.py").read_text(encoding="utf-8")
            with self.assertRaises(Exception):
                apply(project, acknowledge_unverified_base=True)
            self.assertEqual(
                (project / "backend/app/main.py").read_text(encoding="utf-8"),
                original_main,
            )
            self.assertFalse((project / "backend/app/formatting").exists())
            self.assertFalse(list(project.glob(".formatting-integration-backup-*")))

    def test_reserved_revision_collision_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            self.create_project(project)
            collision = project / "backend/alembic/versions/0002_collision.py"
            collision.write_text(
                'revision = "20260801_0100"\ndown_revision = "base1"\n',
                encoding="utf-8",
            )
            with self.assertRaises(Exception):
                apply(project, acknowledge_unverified_base=True)
            self.assertFalse((project / "backend/app/formatting").exists())

    def test_inherited_legacy_overlay_is_rejected_before_writes(self) -> None:
        for overlay_relative in (
            Path("docker-compose.formatting.yml"),
            Path("nested/legacy/DOCKER-COMPOSE.FORMATTING.YML"),
        ):
            with self.subTest(overlay=overlay_relative), tempfile.TemporaryDirectory() as temp:
                project = Path(temp) / "project"
                self.create_project(project)
                overlay = project / overlay_relative
                overlay.parent.mkdir(parents=True, exist_ok=True)
                overlay.write_text("services: {}\n", encoding="utf-8")
                original_main = (project / "backend/app/main.py").read_bytes()

                with self.assertRaisesRegex(IntegrationError, overlay_relative.name):
                    apply(project, acknowledge_unverified_base=True)

                self.assertEqual((project / "backend/app/main.py").read_bytes(), original_main)
                self.assertEqual(overlay.read_text(encoding="utf-8"), "services: {}\n")
                self.assertFalse(list(project.glob(".formatting-integration-backup-*")))

    def test_existing_integrated_formatting_revision_stops_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            self.create_project(project)
            migration = project / MIGRATION_PATH
            migration.write_text(render_migration(ROOT, "base1"), encoding="utf-8")

            with self.assertRaisesRegex(IntegrationError, "مدمج مسبقًا"):
                apply(project, acknowledge_unverified_base=True)

            self.assertFalse((project / "backend/app/formatting").exists())
            self.assertFalse(list(project.glob(".formatting-integration-backup-*")))

    def test_alembic_graph_rejects_duplicates_malformed_dangling_and_multiple_heads(self) -> None:
        cases = {
            "duplicate": (
                "0002_bad.py",
                'revision = "base1"\ndown_revision = None\n',
                "مكررة",
            ),
            "malformed": ("0002_bad.py", "def upgrade(): pass\n", "لا يعرّف revision"),
            "malformed-down-revision": (
                "0002_bad.py",
                'revision = "next1"\ndown_revision = get_parent()\n',
                "down_revision",
            ),
            "malformed-depends-on": (
                "0002_bad.py",
                'revision = "next1"\ndown_revision = "base1"\ndepends_on = get_parent()\n',
                "depends_on",
            ),
            "ambiguous-revision": (
                "0002_bad.py",
                'revision = "next1"\nrevision = "other1"\ndown_revision = "base1"\n',
                "لا يعرّف revision",
            ),
            "ambiguous-depends-on": (
                "0002_bad.py",
                'revision = "next1"\ndown_revision = "base1"\n'
                'depends_on = ("base1", "base1")\n',
                "depends_on",
            ),
            "dangling": (
                "0002_bad.py",
                'revision = "next1"\ndown_revision = "missing"\n',
                "معلّقًا",
            ),
            "dangling-depends-on": (
                "0002_bad.py",
                'revision = "next1"\ndown_revision = "base1"\ndepends_on = "missing"\n',
                "معلّقًا",
            ),
            "multiple-heads": (
                "0002_bad.py",
                'revision = "other1"\ndown_revision = None\n',
                "رأس Alembic واحد",
            ),
        }
        for label, (name, content, message) in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp:
                project = Path(temp) / "project"
                self.create_project(project)
                (project / "backend/alembic/versions" / name).write_text(
                    content, encoding="utf-8"
                )
                with self.assertRaisesRegex(IntegrationError, message):
                    current_alembic_head(project)

    def test_reserved_formatting_filename_cannot_hide_an_unrelated_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            self.create_project(project)
            (project / MIGRATION_PATH).write_text(
                'revision = "unrelated1"\ndown_revision = "base1"\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(IntegrationError, "اسم ملف ترحيل التنسيق محجوز"):
                current_alembic_head(project)

    def test_alembic_graph_rejects_cycles_and_post_formatting_revisions(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            self.create_project(project)
            versions = project / "backend/alembic/versions"
            (versions / "0001_base.py").write_text(
                'revision = "base1"\ndown_revision = "next1"\n', encoding="utf-8"
            )
            (versions / "0002_next.py").write_text(
                'revision = "next1"\ndown_revision = "base1"\n', encoding="utf-8"
            )
            with self.assertRaisesRegex(IntegrationError, "دورة"):
                current_alembic_head(project)

        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            self.create_project(project)
            versions = project / "backend/alembic/versions"
            (versions / "0001_base.py").write_text(
                'revision = "base1"\ndown_revision = None\ndepends_on = "next1"\n',
                encoding="utf-8",
            )
            (versions / "0002_next.py").write_text(
                'revision = "next1"\ndown_revision = "base1"\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(IntegrationError, "دورة"):
                current_alembic_head(project)

        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            self.create_project(project)
            migration = project / MIGRATION_PATH
            migration.write_text(render_migration(ROOT, "base1"), encoding="utf-8")
            (migration.parent / "20260802_later.py").write_text(
                'revision = "later1"\ndown_revision = "20260801_0100"\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(IntegrationError, "أحدث يعتمد"):
                current_alembic_head(project)

        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            self.create_project(project)
            migration = project / MIGRATION_PATH
            migration.write_text(render_migration(ROOT, "base1"), encoding="utf-8")
            (migration.parent / "20260802_later.py").write_text(
                'revision = "later1"\ndown_revision = "base1"\n'
                'depends_on = "20260801_0100"\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(IntegrationError, "أحدث يعتمد"):
                current_alembic_head(project)

    def test_alembic_heads_use_only_down_revision_edges(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            self.create_project(project)
            (project / "backend/alembic/versions/0002_other.py").write_text(
                'revision = "other1"\ndown_revision = None\ndepends_on = "base1"\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(IntegrationError, "رأس Alembic واحد"):
                current_alembic_head(project)

    def test_missing_source_asset_fails_without_target_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            self.create_project(project)
            original = (project / "backend/app/main.py").read_bytes()
            with self.assertRaises(IntegrationError):
                apply(
                    project,
                    source_root=root / "incomplete-bundle",
                    acknowledge_unverified_base=True,
                )
            self.assertEqual((project / "backend/app/main.py").read_bytes(), original)
            self.assertFalse((project / "backend/app/formatting").exists())
            self.assertFalse(list(project.glob(".formatting-integration-backup-*")))

    def test_commit_failure_rolls_back_all_target_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            self.create_project(project)
            tracked = {
                path.relative_to(project): path.read_bytes()
                for path in project.rglob("*")
                if path.is_file()
            }
            real_replace = os.replace

            def fail_on_requirements(source: Path, destination: Path) -> None:
                if Path(destination) == project / "backend/requirements.txt":
                    raise OSError("injected commit failure")
                real_replace(source, destination)

            with mock.patch(
                "scripts.apply_formatting_integration.os.replace",
                side_effect=fail_on_requirements,
            ):
                with self.assertRaises(OSError):
                    apply(project, acknowledge_unverified_base=True)

            for relative, content in tracked.items():
                self.assertEqual((project / relative).read_bytes(), content)
            self.assertFalse((project / "backend/app/formatting").exists())
            self.assertFalse(list(project.glob(".formatting-integration-backup-*")))

    def test_post_replace_validation_failure_rolls_back_attempted_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            self.create_project(project)
            tracked = {
                path.relative_to(project): path.read_bytes()
                for path in project.rglob("*")
                if path.is_file()
            }
            real_atomic_copy = integration_tool._atomic_copy

            def fail_after_requirements_replace(*args, **kwargs):
                result = real_atomic_copy(*args, **kwargs)
                if (
                    Path(args[3]) == project / "backend/requirements.txt"
                    and kwargs.get("ownership_registry") is not None
                ):
                    raise OSError("injected post-replace validation failure")
                return result

            with mock.patch(
                "scripts.apply_formatting_integration._atomic_copy",
                side_effect=fail_after_requirements_replace,
            ):
                with self.assertRaises(OSError):
                    apply(project, acknowledge_unverified_base=True)

            for relative, content in tracked.items():
                self.assertEqual((project / relative).read_bytes(), content)
            self.assertFalse((project / "backend/app/formatting").exists())
            self.assertFalse(list(project.glob(".formatting-integration-backup-*")))

    def test_existing_project_integration_lock_is_never_auto_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            self.create_project(project)
            lock = project.parent / f".{project.name}.formatting-integration.lock"
            lock.write_text("stale\n", encoding="utf-8")

            with self.assertRaisesRegex(IntegrationError, "لن يُحذف تلقائيًا"):
                apply(project, acknowledge_unverified_base=True)

            self.assertEqual(lock.read_text(encoding="utf-8"), "stale\n")
            self.assertFalse(list(project.glob(".formatting-integration-backup-*")))

    def test_final_locked_tree_recheck_refuses_concurrent_edit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            self.create_project(project)
            main = project / "backend/app/main.py"
            real_acquire = integration_tool.acquire_project_lock

            def acquire_then_edit(target: Path):
                project_lock = real_acquire(target)
                main.write_text("concurrent edit\n", encoding="utf-8")
                return project_lock

            with mock.patch(
                "scripts.apply_formatting_integration.acquire_project_lock",
                side_effect=acquire_then_edit,
            ):
                with self.assertRaisesRegex(IntegrationError, "تغيرت شجرة خط الأساس"):
                    apply(project, acknowledge_unverified_base=True)

            self.assertEqual(main.read_text(encoding="utf-8"), "concurrent edit\n")
            self.assertFalse(list(project.glob(".formatting-integration-backup-*")))
            self.assertFalse(
                (project.parent / f".{project.name}.formatting-integration.lock").exists()
            )

    def test_restore_failure_preserves_backup_and_reports_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            self.create_project(project)
            real_replace = os.replace

            def fail_commit_and_restore(source: Path, destination: Path) -> None:
                source_path = Path(source)
                destination_path = Path(destination)
                if destination_path == project / "backend/requirements.txt":
                    raise OSError("injected commit failure")
                if (
                    destination_path == project / "backend/app/main.py"
                    and ".restore-" in source_path.name
                ):
                    raise OSError("injected restore failure")
                real_replace(source, destination)

            with mock.patch(
                "scripts.apply_formatting_integration.os.replace",
                side_effect=fail_commit_and_restore,
            ):
                with self.assertRaisesRegex(IntegrationError, "حُفظت كل النسخ") as raised:
                    apply(project, acknowledge_unverified_base=True)

            backups = list(project.glob(".formatting-integration-backup-*"))
            self.assertEqual(len(backups), 1)
            self.assertIn(str(backups[0]), str(raised.exception))
            self.assertTrue((backups[0] / "backend/app/main.py").is_file())

    def test_migration_placeholder_must_appear_exactly_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source_root = Path(temp) / "bundle"
            source_root.mkdir()
            migration = source_root / MIGRATION_PATH
            migration.parent.mkdir(parents=True)
            shutil.copy2(ROOT / MIGRATION_PATH, migration)
            rendered = render_migration(source_root, "base1")
            self.assertIn('down_revision = "base1"', rendered)
            self.assertNotIn("REPLACE_WITH_CURRENT_HEAD", rendered)

            migration.write_text(
                migration.read_text(encoding="utf-8")
                + '\ndown_revision = "REPLACE_WITH_CURRENT_HEAD"\n',
                encoding="utf-8",
            )
            with self.assertRaises(IntegrationError):
                render_migration(source_root, "base1")


if __name__ == "__main__":
    unittest.main()
