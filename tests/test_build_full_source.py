from __future__ import annotations

import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from scripts.build_full_source_from_original import (
    BuildError,
    KNOWN_BASE_SHA256,
    build,
    excluded,
    suspicious_secret_like,
    write_zip,
)


class BuildFullSourceTests(unittest.TestCase):
    def create_source(self, root: Path) -> Path:
        project = root / "youtube-deepgram-transcriber"
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
            "backend/alembic.ini": "original alembic config\n",
            "backend/alembic/env.py": "original env\n",
            "backend/alembic/script.py.mako": "original template\n",
            "backend/Dockerfile": "original backend image\n",
            "backend/alembic/versions/0001_base.py": 'revision = "base1"\ndown_revision = None\n',
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
            ".env.formatting.example": "SAFE=example\n",
        }
        for relative, content in files.items():
            path = project / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        archive_path = root / "base.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            for path in project.rglob("*"):
                if path.is_file():
                    archive.write(path, arcname=(Path(project.name) / path.relative_to(project)).as_posix())
        return archive_path

    def test_build_creates_clean_merged_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.create_source(root)
            output = root / "merged.zip"
            messages = build(
                source,
                output,
                allow_different_base=True,
                acknowledge_unverified_base=True,
            )
            self.assertTrue(zipfile.is_zipfile(output))
            with zipfile.ZipFile(output) as archive:
                names = set(archive.namelist())
                prefix = "youtube-deepgram-transcriber/"
                self.assertIn(prefix + "backend/app/formatting/tasks.py", names)
                self.assertIn(prefix + "frontend/src/pages/Skills.tsx", names)
                self.assertIn(prefix + "docker-compose.yml", names)
                self.assertNotIn(prefix + "docker-compose.formatting.yml", names)
                compose = archive.read(prefix + "docker-compose.yml").decode("utf-8")
                self.assertIn("formatting-worker:", compose)
                self.assertIn(prefix + ".env.formatting.example", names)
                self.assertIn(
                    prefix + "tools/formatting-integration/verify_coolify_bundle.py",
                    names,
                )
                merged_readme = archive.read(
                    prefix + "docs/formatting-integration/README_INTEGRATION_AR.md"
                ).decode("utf-8")
                self.assertIn("tools/formatting-integration/verify_coolify_bundle.py", merged_readme)
                self.assertNotIn("scripts/verify_coolify_bundle.py", merged_readme)
                self.assertNotIn("build_full_source_from_original.py", merged_readme)
                self.assertNotIn("apply_formatting_integration.py", merged_readme)
                merged_upload = archive.read(prefix + "UPLOAD_NOW_README_AR.md").decode(
                    "utf-8"
                )
                self.assertIn("tools/formatting-integration/verify_coolify_bundle.py", merged_upload)
                self.assertNotIn("python scripts/", merged_upload)
                self.assertFalse(any(".formatting-integration-backup-" in name for name in names))
            self.assertTrue(any("SHA-256 للناتج:" in message for message in messages))
            self.assertTrue(any("غير مُتحقق" in message for message in messages))
            self.assertFalse(
                list(root.glob(".formatting-integration-recovery-*"))
            )

    def test_zip_filter_excludes_legacy_overlay_and_local_state_independently(self) -> None:
        excluded_paths = (
            Path("docker-compose.formatting.yml"),
            Path("DOCKER-COMPOSE.FORMATTING.YML"),
            Path(".env.production"),
            Path(".ENV"),
            Path("AUTH.JSON"),
            Path(".npmrc"),
            Path("id_ed25519"),
            Path(".docker/config.json"),
            Path(".SSH/config"),
            Path(".git-credentials"),
            Path("kubeconfig"),
            Path("certificate.CRT"),
            Path("identity.PFX"),
            Path(".config/gcloud/credentials.db"),
            Path("browser-cookies.sqlite"),
            Path("local.sqlite3"),
            Path("terraform.tfstate"),
            Path("credentials/local.json"),
            Path("cache/value.bin"),
            Path("source.py.orig"),
        )
        for path in excluded_paths:
            self.assertTrue(excluded(path), path.as_posix())
        self.assertFalse(excluded(Path(".env.coolify.manual.example")))
        self.assertFalse(excluded(Path("backend/app/core/security.py")))
        self.assertFalse(excluded(Path("backend/app/cookies.py")))
        self.assertFalse(excluded(Path(".env.example")))
        self.assertFalse(excluded(Path(".env.production.sample")))

        self.assertTrue(suspicious_secret_like(Path("prod-password.conf")))
        self.assertTrue(suspicious_secret_like(Path("client-secret-copy.yaml")))
        self.assertFalse(suspicious_secret_like(Path("docs/security.md")))

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            overlay = project / "nested/legacy/docker-compose.formatting.yml"
            overlay.parent.mkdir(parents=True)
            overlay.write_text(
                "services: {}\n", encoding="utf-8"
            )
            (project / "keep.txt").write_text("keep\n", encoding="utf-8")
            output = root / "output.zip"
            with self.assertRaisesRegex(BuildError, "لن تُحذف بصمت"):
                write_zip(project, output)
            self.assertFalse(output.exists())

    def test_zip_fails_closed_for_unclassified_secret_like_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            (project / "prod-password.conf").write_text("secret\n", encoding="utf-8")
            with self.assertRaisesRegex(BuildError, "مشتبه بأنها أسرار"):
                write_zip(project, root / "output.zip")

    def test_verifier_failure_blocks_output_publication(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.create_source(root)
            output = root / "merged.zip"
            with mock.patch(
                "scripts.build_full_source_from_original.verify",
                return_value=["injected verifier error"],
            ):
                with self.assertRaisesRegex(BuildError, "injected verifier error"):
                    build(
                        source,
                        output,
                        allow_different_base=True,
                        acknowledge_unverified_base=True,
                    )
            self.assertFalse(output.exists())
            recovery = list(root.glob(".formatting-integration-recovery-*"))
            self.assertEqual(len(recovery), 1)
            self.assertEqual(
                len(list(recovery[0].glob(".formatting-integration-backup-*"))),
                1,
            )

    def test_exact_known_hash_remains_the_default_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.create_source(root)
            with self.assertRaisesRegex(BuildError, "المتوقع:") as raised:
                build(source, root / "merged.zip", allow_different_base=False)
            message = str(raised.exception)
            self.assertIn(f"المتوقع: {KNOWN_BASE_SHA256}", message)
            self.assertIn("الفعلي:", message)
            self.assertNotIn(f"الفعلي: {KNOWN_BASE_SHA256}", message)

    def test_different_base_still_requires_the_full_baseline_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.create_source(root)
            incomplete = root / "incomplete-base.zip"
            with zipfile.ZipFile(source) as original, zipfile.ZipFile(
                incomplete, "w"
            ) as rewritten:
                for info in original.infolist():
                    if not info.filename.endswith("backend/app/core/security.py"):
                        rewritten.writestr(info, original.read(info.filename))

            with self.assertRaisesRegex(BuildError, "security.py"):
                build(
                    incomplete,
                    root / "merged.zip",
                    allow_different_base=True,
                    acknowledge_unverified_base=True,
                )
            self.assertFalse((root / "merged.zip").exists())

    def test_build_failure_does_not_publish_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.create_source(root)
            output = root / "merged.zip"
            with self.assertRaises(BuildError):
                build(
                    source,
                    output,
                    allow_different_base=True,
                    source_root=root / "incomplete-bundle",
                    acknowledge_unverified_base=True,
                )
            self.assertFalse(output.exists())
            self.assertFalse(list(root.glob(".merged.zip.*.quarantine")))

    def test_existing_output_is_always_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.create_source(root)
            output = root / "merged.zip"
            output.write_bytes(b"existing-output")

            with self.assertRaisesRegex(BuildError, "اختر مسارًا جديدًا"):
                build(
                    source,
                    output,
                    allow_different_base=True,
                    acknowledge_unverified_base=True,
                )

            self.assertEqual(output.read_bytes(), b"existing-output")

    def test_base_and_output_paths_must_always_differ(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.create_source(root)

            with self.assertRaisesRegex(BuildError, "base_zip.*output_zip"):
                build(
                    source,
                    source,
                    allow_different_base=True,
                    acknowledge_unverified_base=True,
                )

    def test_final_no_clobber_publish_failure_leaves_no_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.create_source(root)
            output = root / "merged.zip"
            real_link = os.link

            def fail_final_publish(source_path: Path, destination: Path) -> None:
                if Path(destination) == output:
                    raise OSError("injected final publication failure")
                real_link(source_path, destination)

            with mock.patch(
                "scripts.build_full_source_from_original.os.link",
                side_effect=fail_final_publish,
            ):
                with self.assertRaisesRegex(BuildError, "final publication failure"):
                    build(
                        source,
                        output,
                        allow_different_base=True,
                        acknowledge_unverified_base=True,
                    )

            self.assertFalse(output.exists())
            self.assertFalse(list(root.glob(".merged.zip.*.quarantine")))

    def test_keyboard_interrupt_leaves_output_absent_and_is_reraised(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.create_source(root)
            output = root / "merged.zip"

            with mock.patch(
                "scripts.build_full_source_from_original.verify",
                side_effect=KeyboardInterrupt,
            ):
                with self.assertRaises(KeyboardInterrupt):
                    build(
                        source,
                        output,
                        allow_different_base=True,
                        acknowledge_unverified_base=True,
                    )

            self.assertFalse(output.exists())
            self.assertFalse(list(root.glob(".merged.zip.*.quarantine")))


if __name__ == "__main__":
    unittest.main()
