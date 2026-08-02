from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

import yaml

from scripts.verify_coolify_bundle import (
    CANONICAL_TOP_LEVEL_KEYS,
    COMPOSE_DIRECT_MODULES,
    EXPECTED_BUILD_DOCKERFILES,
    EXPECTED_DEPENDENCIES,
    EXPECTED_FORMATTING_LIMITS,
    EXPECTED_NETWORK_MEMBERSHIPS,
    EXPECTED_SECRET_PLACEMENTS,
    EXPECTED_SECRET_RECIPIENTS,
    EXPECTED_SERVICE_MOUNTS,
    EXPECTED_SERVICE_COUNT,
    EXPECTED_IMAGE_SERVICES,
    FRONTEND_LOCKFILES,
    LONG_RUNNING_SERVICES,
    MIGRATION_NAME,
    ONE_SHOT_SERVICES,
    REQUIRED_NETWORKS,
    REQUIRED_SERVICES,
    REQUIRED_SOURCE_FILES,
    REQUIRED_VOLUMES,
    ROOT,
    _validate_dependencies,
    _validate_builds,
    _validate_compose_document,
    _validate_formatting_limits,
    _validate_formatting_storage,
    _validate_gateway_hardening,
    _validate_gateway_network,
    _validate_healthchecks,
    _validate_migrations,
    _validate_named_volumes,
    _validate_proxy_contract,
    _validate_redis_authentication,
    _validate_secret_distribution,
    _validate_runtime_overrides,
    _validate_topology,
    verify,
)


class VerifyCoolifyBundleTests(unittest.TestCase):
    def test_compose_runtime_modules_are_required_source(self) -> None:
        self.assertTrue(
            {
                "backend/app/celery_app.py",
                "backend/app/db_wait.py",
                "backend/app/scheduler.py",
                "backend/alembic.ini",
                "backend/alembic/env.py",
                "backend/alembic/script.py.mako",
                "backend/app/core/db.py",
                "backend/app/core/models.py",
                "backend/app/core/security.py",
                "backend/app/services/export_service.py",
                "backend/app/services/log_service.py",
                "frontend/package.json",
                "frontend/index.html",
                "frontend/src/api.ts",
                "frontend/src/hooks/useFetch.ts",
                "tools/formatting-integration/apply_formatting_integration.py",
                "tools/formatting-integration/build_full_source_from_original.py",
                "tools/formatting-integration/formatting_integration_tree.py",
                "tools/formatting-integration/verify_coolify_bundle.py",
            }.issubset(REQUIRED_SOURCE_FILES)
        )
        self.assertEqual(
            FRONTEND_LOCKFILES,
            (
                "frontend/pnpm-lock.yaml",
                "frontend/yarn.lock",
                "frontend/package-lock.json",
            ),
        )
        self.assertFalse(
            {
                "frontend/vite.config.ts",
                "frontend/tsconfig.json",
            }
            & REQUIRED_SOURCE_FILES
        )
        self.assertTrue(
            {
                "backend/app/formatting/celery_bootstrap.py",
                "backend/app/formatting/config.py",
                "backend/app/formatting/opencode_client.py",
                "backend/app/formatting/opencode_control.py",
                "backend/app/formatting/outbox_dispatcher.py",
                "backend/app/formatting/repository.py",
                "backend/app/formatting/runtime.py",
                "backend/app/formatting/skills.py",
                "backend/app/formatting/tasks.py",
            }.issubset(REQUIRED_SOURCE_FILES)
        )
        self.assertEqual(
            {
                source_path
                for _module_marker, source_path in COMPOSE_DIRECT_MODULES.values()
            }
            - REQUIRED_SOURCE_FILES,
            set(),
        )
        compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
        for service_name, (module_marker, _source_path) in COMPOSE_DIRECT_MODULES.items():
            self.assertIn(module_marker, str(compose["services"][service_name]["command"]))

    def test_compose_names_networks_and_volumes_are_exact(self) -> None:
        compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
        self.assertEqual(set(compose), CANONICAL_TOP_LEVEL_KEYS)
        self.assertEqual(set(compose["services"]), REQUIRED_SERVICES)
        self.assertEqual(len(REQUIRED_SERVICES), EXPECTED_SERVICE_COUNT)
        self.assertEqual(set(compose["networks"]), REQUIRED_NETWORKS)
        self.assertEqual(len(REQUIRED_NETWORKS), 6)
        self.assertIs(compose["networks"]["data"]["internal"], True)
        self.assertIs(compose["networks"]["formatting-control"]["internal"], True)
        self.assertIs(compose["networks"]["gateway"]["internal"], True)
        for name in ("edge", "formatting-egress", "transcription-egress"):
            self.assertIs(compose["networks"][name]["internal"], False)
        self.assertEqual(set(compose["volumes"]), REQUIRED_VOLUMES)
        self.assertEqual(len(REQUIRED_VOLUMES), 9)
        self.assertEqual(set(EXPECTED_NETWORK_MEMBERSHIPS), REQUIRED_SERVICES)
        self.assertEqual(set(EXPECTED_SERVICE_MOUNTS), REQUIRED_SERVICES)

    def test_top_level_compose_contract_rejects_external_composition(self) -> None:
        source = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        compose = yaml.safe_load(source)
        self.assertEqual(_validate_compose_document(source, compose), [])

        for key in ("include", "extends", "configs", "secrets", "fragments", "name"):
            with self.subTest(key=key):
                broken = copy.deepcopy(compose)
                broken[key] = {"external": "other-compose.yml"}
                errors = _validate_compose_document(source, broken)
                self.assertTrue(any(key in error for error in errors))

        merge_source = (
            "x-external: &external\n"
            "  include: other-compose.yml\n"
            "<<: *external\n"
            + source
        )
        merge_data = yaml.safe_load(merge_source)
        self.assertTrue(
            any(
                "top-level YAML merge key" in error
                for error in _validate_compose_document(merge_source, merge_data)
            )
        )

    def test_dispatcher_compose_role_is_isolated_and_counted(self) -> None:
        compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
        services = compose["services"]
        self.assertEqual(len(services), EXPECTED_SERVICE_COUNT)

        dispatcher = services["formatting-dispatcher"]
        self.assertEqual(dispatcher["networks"], ["data"])
        self.assertEqual(
            dispatcher["volumes"],
            ["formatting-execution-exchange:/data/formatting-execution"],
        )
        self.assertEqual(
            dispatcher["environment"]["FORMATTING_EXECUTION_ROOT"],
            "/data/formatting-execution",
        )
        self.assertNotIn("OPENCODE_", str(dispatcher["environment"]))
        self.assertIn("app.db_wait", str(dispatcher["command"]))
        self.assertIn("app.formatting.outbox_dispatcher", str(dispatcher["command"]))
        self.assertNotIn("/proc/", str(dispatcher["healthcheck"]))
        self.assertIn("HEARTBEAT_PATH", str(dispatcher["healthcheck"]))
        self.assertIn("MAX_AGE_SECONDS", str(dispatcher["healthcheck"]))
        self.assertIn(
            "FORMATTING_OUTBOX_MAX_DISPATCH_PER_CYCLE", dispatcher["environment"]
        )
        self.assertIn(
            "FORMATTING_QUEUED_RECONCILE_AGE_SECONDS", dispatcher["environment"]
        )

    def test_canonical_build_and_image_matrix_is_exact(self) -> None:
        compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
        services = compose["services"]
        self.assertEqual(_validate_builds(ROOT, services), [])
        self.assertEqual(
            set(EXPECTED_BUILD_DOCKERFILES) | set(EXPECTED_IMAGE_SERVICES),
            REQUIRED_SERVICES,
        )

        broken = copy.deepcopy(services)
        broken["api"].pop("build")
        broken["api"]["image"] = "registry.example/api:latest"
        errors = _validate_builds(ROOT, broken)
        self.assertTrue(any("api must not define image" in error for error in errors))
        self.assertTrue(any("api must use the canonical build" in error for error in errors))

        broken = copy.deepcopy(services)
        broken["formatting-worker"]["build"]["context"] = "backend"
        self.assertTrue(
            any(
                "formatting-worker build context must be exactly ." in error
                for error in _validate_builds(ROOT, broken)
            )
        )

        broken = copy.deepcopy(services)
        broken["gateway"]["build"]["dockerfile"] = "Dockerfile"
        self.assertTrue(
            any(
                "gateway must build with frontend/Dockerfile" in error
                for error in _validate_builds(ROOT, broken)
            )
        )

        broken = copy.deepcopy(services)
        broken["redis"]["image"] = "redis:latest"
        self.assertTrue(
            any(
                "redis image must be exactly redis:8-alpine" in error
                for error in _validate_builds(ROOT, broken)
            )
        )

        broken = copy.deepcopy(services)
        broken["redis"]["build"] = {
            "context": ".",
            "dockerfile": "backend/Dockerfile",
        }
        self.assertTrue(
            any(
                "Image-only service redis must not define build" in error
                for error in _validate_builds(ROOT, broken)
            )
        )

        broken = copy.deepcopy(services)
        broken["gateway"]["build"]["target"] = "unreviewed"
        self.assertTrue(
            any(
                "gateway build keys must be exactly" in error
                for error in _validate_builds(ROOT, broken)
            )
        )

    def test_every_service_topology_and_port_surface_are_exact(self) -> None:
        compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
        services = compose["services"]
        self.assertEqual(_validate_topology(services), [])

        broken = copy.deepcopy(services)
        broken["api"]["ports"] = ["8000:8000"]
        self.assertTrue(
            any("api must not publish" in error for error in _validate_topology(broken))
        )

        broken = copy.deepcopy(services)
        broken["scheduler"]["networks"].append("gateway")
        self.assertTrue(
            any(
                "scheduler network membership" in error
                for error in _validate_topology(broken)
            )
        )

        broken = copy.deepcopy(services)
        broken["api"]["volumes"].append("opencode-data:/data/opencode/data")
        self.assertTrue(
            any(
                "api named-volume mounts" in error
                for error in _validate_topology(broken)
            )
        )

        broken = copy.deepcopy(services)
        broken["api"]["expose"] = ["8000"]
        self.assertTrue(
            any(
                "api must not declare exposed" in error
                for error in _validate_topology(broken)
            )
        )

        broken = copy.deepcopy(services)
        broken["gateway"]["ports"] = ["80:80"]
        self.assertTrue(
            any("gateway must not publish" in error for error in _validate_topology(broken))
        )

        broken = copy.deepcopy(services)
        broken["gateway"]["expose"] = ["80", "443"]
        self.assertTrue(
            any("gateway must expose only" in error for error in _validate_topology(broken))
        )

    def test_gateway_edge_ipam_and_forwarded_trust_are_exact(self) -> None:
        compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
        services = compose["services"]
        networks = compose["networks"]
        self.assertEqual(_validate_gateway_network(services, networks), [])
        self.assertEqual(services["gateway"]["networks"]["edge"], None)
        self.assertEqual(
            services["gateway"]["networks"]["gateway"]["ipv4_address"],
            "${GATEWAY_PEER_IP:-10.99.42.2}",
        )
        self.assertEqual(
            services["api"]["environment"]["FORWARDED_ALLOW_IPS"],
            "${GATEWAY_PEER_IP:-10.99.42.2}",
        )
        self.assertIn(
            "--forwarded-allow-ips=$${FORWARDED_ALLOW_IPS}",
            services["api"]["command"][-1],
        )

        broken_services = copy.deepcopy(services)
        broken_services["api"]["command"][-1] = broken_services["api"]["command"][
            -1
        ].replace(
            "$${FORWARDED_ALLOW_IPS}",
            "*",
        )
        self.assertTrue(
            any(
                "trust only" in error
                for error in _validate_gateway_network(broken_services, networks)
            )
        )

        broken_services = copy.deepcopy(services)
        broken_services["api"]["environment"]["FORWARDED_ALLOW_IPS"] = (
            "${GATEWAY_PEER_IP:-10.99.42.3}"
        )
        self.assertTrue(
            any(
                "exactly match" in error
                for error in _validate_gateway_network(broken_services, networks)
            )
        )

        broken_networks = copy.deepcopy(networks)
        broken_networks["gateway"]["ipam"]["config"][0]["subnet"] = (
            "${GATEWAY_NETWORK_SUBNET:-10.99.99.0/24}"
        )
        self.assertTrue(
            any(
                "usable host" in error
                for error in _validate_gateway_network(services, broken_networks)
            )
        )

    def test_gateway_hardening_is_exact(self) -> None:
        compose = yaml.safe_load(
            (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        )
        services = compose["services"]
        self.assertEqual(_validate_gateway_hardening(services), [])

        broken = copy.deepcopy(services)
        broken["gateway"]["cap_add"].append("NET_RAW")
        self.assertTrue(
            any(
                "capabilities must be exactly" in error
                for error in _validate_gateway_hardening(broken)
            )
        )

        broken = copy.deepcopy(services)
        broken["gateway"]["read_only"] = False
        self.assertTrue(
            any(
                "root filesystem must be read-only" in error
                for error in _validate_gateway_hardening(broken)
            )
        )

        broken = copy.deepcopy(services)
        broken["gateway"]["privileged"] = True
        self.assertTrue(
            any(
                "privilege/host escape options" in error
                for error in _validate_gateway_hardening(broken)
            )
        )

    def test_forbidden_runtime_override_matrix_applies_to_every_service(self) -> None:
        compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
        services = compose["services"]
        self.assertEqual(_validate_runtime_overrides(services), [])
        for service_name in REQUIRED_SERVICES:
            self.assertFalse(
                {"profiles", "scale", "deploy", "extends"} & set(services[service_name])
            )

        forbidden_mutations = {
            "blkio_config": {"device_read_bps": [{"path": "/dev/sda", "rate": "1mb"}]},
            "configs": ["external-config"],
            "credential_spec": {"file": "host-credential.json"},
            "deploy": {"replicas": 0},
            "develop": {"watch": [{"action": "sync", "path": ".", "target": "/app"}]},
            "extends": {"file": "host-compose.yml", "service": "api"},
            "privileged": True,
            "devices": ["/dev/kvm:/dev/kvm"],
            "device_cgroup_rules": ["c 10:232 rwm"],
            "env_file": [".env"],
            "entrypoint": ["sh"],
            "extra_hosts": ["host.docker.internal:host-gateway"],
            "links": ["postgres:db"],
            "external_links": ["host-service:host-service"],
            "sysctls": {"kernel.unprivileged_userns_clone": "1"},
            "pid": "host",
            "post_start": [{"command": "true"}],
            "pre_stop": [{"command": "true"}],
            "profiles": ["optional"],
            "ipc": "host",
            "uts": "host",
            "userns_mode": "host",
            "cgroup": "host",
            "cgroup_parent": "docker.slice",
            "runtime": "runc",
            "scale": 0,
            "secrets": ["external-secret"],
            "isolation": "hyperv",
            "group_add": ["docker"],
            "volumes_from": ["storage-init"],
            "gpus": "all",
            "use_api_socket": True,
        }
        for key, value in forbidden_mutations.items():
            with self.subTest(key=key):
                broken = copy.deepcopy(services)
                broken["api"][key] = value
                self.assertTrue(
                    any(
                        key in error
                        for error in _validate_runtime_overrides(broken)
                    )
                )

        for key, value in (
            ("scale", 1),
            ("deploy", {"replicas": 1}),
            ("deploy", {"replicas": 2}),
        ):
            with self.subTest(default_instance_override=key, value=value):
                broken = copy.deepcopy(services)
                broken["api"][key] = value
                self.assertTrue(
                    any(key in error for error in _validate_runtime_overrides(broken))
                )

        broken = copy.deepcopy(services)
        broken["api"]["cap_add"] = ["SYS_ADMIN"]
        self.assertTrue(
            any("api must not declare cap_add" in error for error in _validate_runtime_overrides(broken))
        )

        for service_name in ("storage-init", "formatting-storage-init"):
            with self.subTest(service=service_name):
                broken = copy.deepcopy(services)
                broken[service_name]["network_mode"] = "host"
                self.assertTrue(
                    any(
                        "exactly network_mode: none" in error
                        for error in _validate_runtime_overrides(broken)
                    )
                )

        broken = copy.deepcopy(services)
        broken["api"]["network_mode"] = "host"
        self.assertTrue(
            any("must not override network_mode" in error for error in _validate_runtime_overrides(broken))
        )

    def test_runtime_user_hardening_and_mount_contract_are_exact(self) -> None:
        compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
        services = compose["services"]

        for root_user in (0, "0", "0:10001", "root", "root:root"):
            with self.subTest(root_user=root_user):
                broken = copy.deepcopy(services)
                broken["api"]["user"] = root_user
                self.assertTrue(
                    any(
                        "api must not specify a root user" in error
                        for error in _validate_runtime_overrides(broken)
                    )
                )

        hardening_mutations = (
            ("api", "security_opt", ["seccomp:unconfined"]),
            ("api", "cap_drop", []),
            ("gateway", "read_only", False),
            ("postgres", "security_opt", ["apparmor:unconfined"]),
        )
        for service_name, key, value in hardening_mutations:
            with self.subTest(service=service_name, key=key):
                broken = copy.deepcopy(services)
                broken[service_name][key] = value
                self.assertTrue(_validate_runtime_overrides(broken))

        host_mounts = (
            "./host-data:/data/audio",
            "/var/run/docker.sock:/var/run/docker.sock",
            {"type": "bind", "source": "/host", "target": "/data/audio"},
        )
        for mount in host_mounts:
            with self.subTest(mount=mount):
                broken = copy.deepcopy(services)
                broken["api"]["volumes"][0] = mount
                self.assertTrue(
                    any(
                        "host paths or bind mounts" in error
                        for error in _validate_runtime_overrides(broken)
                    )
                )

    def test_named_volume_definitions_are_empty_or_null_only(self) -> None:
        compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
        volumes = compose["volumes"]
        self.assertEqual(_validate_named_volumes(volumes), [])

        empty_mapping = copy.deepcopy(volumes)
        empty_mapping["audio-data"] = {}
        self.assertEqual(_validate_named_volumes(empty_mapping), [])

        invalid_definitions = (
            {"driver": "local"},
            {"driver_opts": {"type": "none", "o": "bind", "device": "/host"}},
            {"external": True},
            {"name": "host-volume"},
            {"labels": {"managed": "outside"}},
            "/host/path",
        )
        for definition in invalid_definitions:
            with self.subTest(definition=definition):
                broken = copy.deepcopy(volumes)
                broken["audio-data"] = definition
                self.assertTrue(
                    any(
                        "empty/null mappings only" in error
                        for error in _validate_named_volumes(broken)
                    )
                )

    def test_proxy_dockerfile_contract_is_statically_enforced(self) -> None:
        self.assertEqual(_validate_proxy_contract(ROOT), [])

        backend_source = (ROOT / "backend/Dockerfile").read_text(encoding="utf-8")
        frontend_dockerfile_source = (ROOT / "frontend/Dockerfile").read_text(encoding="utf-8")
        nginx_source = (ROOT / "frontend/nginx.conf").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "backend").mkdir()
            (root / "frontend").mkdir()
            (root / "backend/Dockerfile").write_text(
                backend_source.replace(
                    '"--no-proxy-headers"',
                    '"--proxy-headers", "--forwarded-allow-ips=*"',
                ),
                encoding="utf-8",
            )
            (root / "frontend/Dockerfile").write_text(frontend_dockerfile_source, encoding="utf-8")
            (root / "frontend/nginx.conf").write_text(
                nginx_source.replace(
                    "proxy_set_header X-Forwarded-For $remote_addr;",
                    "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
                ),
                encoding="utf-8",
            )
            errors = _validate_proxy_contract(root)
            self.assertTrue(
                any("must not configure forwarded trust" in error for error in errors)
            )
            self.assertTrue(any("append or reuse" in error for error in errors))

            (root / "backend/Dockerfile").write_text(backend_source, encoding="utf-8")
            (root / "frontend/nginx.conf").write_text(
                nginx_source.replace(
                    'set $api_upstream "api:8000";\n            proxy_pass http://$api_upstream;',
                    'set $api_upstream "api:8000";\n            proxy_pass http://$api_upstream;\n        proxy_pass http://other:8000;',
                ),
                encoding="utf-8",
            )
            self.assertTrue(
                any(
                    "must not define proxy_pass outside" in error
                    for error in _validate_proxy_contract(root)
                )
            )

    def test_healthcheck_roles_scheduler_child_and_dispatcher_heartbeat_are_enforced(self) -> None:
        compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
        services = compose["services"]
        self.assertEqual(_validate_healthchecks(services), [])
        self.assertEqual(ONE_SHOT_SERVICES | LONG_RUNNING_SERVICES, REQUIRED_SERVICES)

        scheduler_health = str(services["scheduler"]["healthcheck"])
        self.assertIn("/proc/1/task/1/children", scheduler_health)
        self.assertIn("len(children) != 1", scheduler_health)
        self.assertNotIn("/proc/1/cmdline", scheduler_health)

        broken = copy.deepcopy(services)
        broken["storage-init"]["restart"] = "unless-stopped"
        self.assertTrue(
            any(
                "storage-init must use restart" in error
                for error in _validate_healthchecks(broken)
            )
        )

        broken = copy.deepcopy(services)
        del broken["api"]["healthcheck"]
        self.assertTrue(
            any(
                "api is missing a health check" in error
                for error in _validate_healthchecks(broken)
            )
        )

        broken = copy.deepcopy(services)
        broken["formatting-dispatcher"]["healthcheck"]["test"] = [
            "CMD",
            "python",
            "-c",
            "open('/proc/1/cmdline').read()",
        ]
        self.assertTrue(
            any(
                "heartbeat freshness" in error
                for error in _validate_healthchecks(broken)
            )
        )

        broken = copy.deepcopy(services)
        broken["formatting-dispatcher"].pop("tmpfs")
        self.assertTrue(
            any(
                "heartbeat path must be tmpfs-backed" in error
                for error in _validate_healthchecks(broken)
            )
        )

        broken = copy.deepcopy(services)
        broken["api"]["healthcheck"]["test"] = ["CMD", "true"]
        self.assertTrue(
            any(
                "api health check does not verify" in error
                for error in _validate_healthchecks(broken)
            )
        )

    def test_dependency_conditions_and_formatting_limit_consumers_are_exact(self) -> None:
        compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
        services = compose["services"]
        self.assertEqual(_validate_dependencies(services), [])
        self.assertEqual(_validate_formatting_limits(services), [])
        self.assertEqual(set(EXPECTED_DEPENDENCIES), REQUIRED_SERVICES)
        self.assertEqual(
            set(EXPECTED_FORMATTING_LIMITS),
            {"FORMATTING_INPUT_MAX_BYTES", "FORMATTING_STORAGE_MAX_BYTES"},
        )

        broken = copy.deepcopy(services)
        broken["worker-3"]["depends_on"].pop("postgres")
        self.assertTrue(
            any(
                "worker-3 dependencies must be exactly" in error
                for error in _validate_dependencies(broken)
            )
        )

        broken = copy.deepcopy(services)
        broken["api"]["depends_on"]["migrate"]["condition"] = "service_started"
        self.assertTrue(
            any(
                "api must wait for migrate" in error
                for error in _validate_dependencies(broken)
            )
        )

        broken = copy.deepcopy(services)
        del broken["formatting-worker"]["environment"]["FORMATTING_STORAGE_MAX_BYTES"]
        self.assertTrue(
            any(
                "FORMATTING_STORAGE_MAX_BYTES recipients" in error
                for error in _validate_formatting_limits(broken)
            )
        )

    def test_dispatcher_source_uses_atomic_success_cycle_heartbeat(self) -> None:
        source = (ROOT / "backend/app/formatting/outbox_dispatcher.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("FORMATTING_DISPATCHER_HEARTBEAT_PATH", source)
        self.assertIn('relative_to(Path("/tmp").resolve(strict=True))', source)
        self.assertIn("tempfile.mkstemp", source)
        self.assertIn("os.replace(temporary_name, path)", source)
        self.assertIn("_write_heartbeat(heartbeat_path)", source)

    def test_formatting_storage_mounts_and_tmpfs_are_statically_enforced(self) -> None:
        compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
        services = compose["services"]
        self.assertEqual(_validate_formatting_storage(services), [])

        broken = copy.deepcopy(services)
        broken["opencode-runtime"]["volumes"].append(
            "formatting-data:/data/formatting"
        )
        self.assertTrue(
            any(
                "opencode-runtime must mount only" in error
                for error in _validate_formatting_storage(broken)
            )
        )

        broken = copy.deepcopy(services)
        broken["formatting-worker"]["volumes"] = [
            mount
            for mount in broken["formatting-worker"]["volumes"]
            if not mount.startswith("formatting-jobs-data:")
        ]
        self.assertTrue(
            any(
                "persistent formatting jobs" in error
                for error in _validate_formatting_storage(broken)
            )
        )

        broken = copy.deepcopy(services)
        broken["formatting-worker"]["volumes"].append(
            "opencode-data:/data/opencode/data"
        )
        self.assertTrue(
            any(
                "formatting-worker must mount only" in error
                for error in _validate_formatting_storage(broken)
            )
        )

        broken = copy.deepcopy(services)
        broken["formatting-dispatcher"]["volumes"] = []
        self.assertTrue(
            any(
                "dispatcher janitor must mount only" in error
                for error in _validate_formatting_storage(broken)
            )
        )

        broken = copy.deepcopy(services)
        broken["formatting-dispatcher"]["environment"][
            "OPENCODE_SERVER_PASSWORD"
        ] = "not-allowed"
        self.assertTrue(
            any(
                "must not receive OpenCode configuration or auth" in error
                for error in _validate_formatting_storage(broken)
            )
        )

        broken = copy.deepcopy(services)
        broken["formatting-worker"]["environment"]["FORMATTING_EXECUTION_ROOT"] = (
            "${FORMATTING_EXECUTION_ROOT}"
        )
        self.assertTrue(
            any(
                "hardcoded exchange path" in error
                for error in _validate_formatting_storage(broken)
            )
        )

        broken = copy.deepcopy(services)
        broken["formatting-storage-init"]["command"][-1] = "mkdir -p /data/formatting"
        self.assertTrue(
            any(
                "fixed execution sentinel" in error
                for error in _validate_formatting_storage(broken)
            )
        )

        broken = copy.deepcopy(services)
        broken["opencode-runtime"]["environment"]["XDG_CONFIG_HOME"] = (
            "/data/opencode/config"
        )
        self.assertTrue(
            any(
                "XDG_CONFIG_HOME" in error
                for error in _validate_formatting_storage(broken)
            )
        )

        broken = copy.deepcopy(services)
        broken["formatting-worker"]["environment"]["XDG_DATA_HOME"] = (
            "/data/opencode/data"
        )
        self.assertTrue(
            any(
                "XDG_DATA_HOME" in error
                for error in _validate_formatting_storage(broken)
            )
        )

    def test_redis_password_command_health_and_client_urls_are_structural(self) -> None:
        compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
        services = compose["services"]
        self.assertEqual(_validate_redis_authentication(services), [])

        broken = copy.deepcopy(services)
        broken["redis"]["environment"]["REDIS_PASSWORD"] = "plaintext"
        self.assertTrue(_validate_redis_authentication(broken))

        broken = copy.deepcopy(services)
        broken["redis"]["command"] = ["redis-server"]
        self.assertTrue(
            any(
                "password-protected config" in error
                for error in _validate_redis_authentication(broken)
            )
        )

        broken = copy.deepcopy(services)
        broken["redis"]["healthcheck"]["test"] = ["CMD", "redis-cli", "ping"]
        self.assertTrue(
            any(
                "health check must authenticate" in error
                for error in _validate_redis_authentication(broken)
            )
        )

        broken = copy.deepcopy(services)
        broken["formatting-worker"]["environment"]["REDIS_URL"] = (
            "redis://redis:6379/0"
        )
        self.assertTrue(
            any(
                "formatting-worker must use the shared authenticated REDIS_URL" in error
                for error in _validate_redis_authentication(broken)
            )
        )

    def test_generated_secrets_and_deepgram_keys_have_exact_recipients(self) -> None:
        compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
        services = compose["services"]
        self.assertEqual(_validate_secret_distribution(services), [])
        self.assertEqual(
            set(EXPECTED_SECRET_RECIPIENTS),
            {
                "SERVICE_PASSWORD_64_POSTGRES",
                "SERVICE_PASSWORD_64_REDIS",
                "SERVICE_PASSWORD_64_ADMIN",
                "SERVICE_HEX_128_SESSION",
                "SERVICE_PASSWORD_64_OPENCODE",
            },
        )
        self.assertEqual(set(EXPECTED_SECRET_PLACEMENTS), set(EXPECTED_SECRET_RECIPIENTS))

        broken = copy.deepcopy(services)
        broken["scheduler"]["environment"]["ADMIN_PASSWORD"] = (
            "${SERVICE_PASSWORD_64_ADMIN}"
        )
        self.assertTrue(
            any(
                "SERVICE_PASSWORD_64_ADMIN environment key placements" in error
                for error in _validate_secret_distribution(broken)
            )
        )

        broken = copy.deepcopy(services)
        broken["api"]["environment"]["WRONG_SESSION_KEY"] = broken["api"][
            "environment"
        ].pop("SESSION_SECRET")
        self.assertTrue(
            any(
                "SERVICE_HEX_128_SESSION environment key placements" in error
                for error in _validate_secret_distribution(broken)
            )
        )

        broken = copy.deepcopy(services)
        broken["api"]["command"].append("${SERVICE_PASSWORD_64_ADMIN}")
        self.assertTrue(
            any(
                "must not leak outside" in error
                for error in _validate_secret_distribution(broken)
            )
        )

        broken = copy.deepcopy(services)
        broken["scheduler"]["environment"]["OPENCODE_SERVER_PASSWORD"] = (
            "${OPENCODE_SERVER_PASSWORD}"
        )
        self.assertTrue(
            any(
                "Sensitive environment key OPENCODE_SERVER_PASSWORD" in error
                for error in _validate_secret_distribution(broken)
            )
        )

        broken = copy.deepcopy(services)
        broken["worker-2"]["environment"]["DEEPGRAM_API_KEY"] = (
            "${DEEPGRAM_API_KEY_WORKER_1:?Set worker 1 Deepgram key}"
        )
        self.assertTrue(_validate_secret_distribution(broken))

    def test_incomplete_context_and_placeholder_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            compose = root / "docker-compose.yml"
            compose.write_text(
                "services:\n"
                "  api: {}\n"
                "# SERVICE_PASSWORD_64_POSTGRES SERVICE_PASSWORD_64_ADMIN\n"
                "# SERVICE_HEX_128_SESSION SERVICE_PASSWORD_64_OPENCODE\n"
                "# SERVICE_PASSWORD_64_REDIS\n",
                encoding="utf-8",
            )
            migration = root / "backend/alembic/versions" / MIGRATION_NAME
            migration.parent.mkdir(parents=True)
            migration.write_text(
                'revision = "20260801_0100"\n'
                'down_revision = "REPLACE_WITH_CURRENT_HEAD"\n',
                encoding="utf-8",
            )
            overlay = root / "nested/legacy/DOCKER-COMPOSE.FORMATTING.YML"
            overlay.parent.mkdir(parents=True)
            overlay.write_text(
                "services: {}\n",
                encoding="utf-8",
            )

            errors = verify(root)
            self.assertTrue(any("Missing source/build files" in error for error in errors))
            self.assertTrue(any("Missing frontend lockfile" in error for error in errors))
            self.assertTrue(any("placeholder" in error for error in errors))
            self.assertTrue(any("Original Alembic history is missing" in error for error in errors))
            self.assertTrue(any("legacy formatting Compose overlay" in error for error in errors))

    def test_final_tree_scan_rejects_nested_backup_secrets_credentials_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
            prohibited = (
                "nested/.formatting-integration-backup-20260802/file.txt",
                "nested/config/.env.production",
                "nested/auth/AUTH.JSON",
                "nested/browser/youtube-cookies.txt",
                "nested/keys/private.key",
                "nested/state/runtime.sqlite3",
                "nested/cache/value.bin",
                "nested/__pycache__/value.pyc",
                "nested/.pytest_cache/state.bin",
                "nested/compiled.pyc",
                "nested/compiled.pyo",
                "nested/.tox/state.json",
                "nested/frontend/.vite/manifest.json",
                "nested/coverage/.coverage",
                "nested/os/Thumbs.db",
                "nested/pkg/example.egg-info/PKG-INFO",
                "nested/legacy/docker-compose.formatting.yml",
            )
            for relative in prohibited:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("local\n", encoding="utf-8")

            errors = verify(root)
            release_errors = [
                error for error in errors if "Release tree contains prohibited" in error
            ]
            self.assertEqual(len(release_errors), 1)
            for relative in prohibited:
                self.assertIn(relative, release_errors[0])

    def test_invalid_canonical_compose_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "docker-compose.yml").write_text("not yaml: [\n", encoding="utf-8")
            errors = verify(root)
            self.assertTrue(any("invalid YAML" in error for error in errors))

    def test_migration_verifier_rejects_malformed_dangling_cycles_and_later_revisions(self) -> None:
        cases = {
            "malformed": {
                "0001_bad.py": "def upgrade(): pass\n",
            },
            "malformed-down-revision": {
                "0001_base.py": (
                    'revision = "base1"\n'
                    "down_revision = get_parent()\n"
                ),
            },
            "malformed-depends-on": {
                "0001_base.py": (
                    'revision = "base1"\n'
                    "down_revision = None\n"
                    "depends_on = get_parent()\n"
                ),
            },
            "ambiguous-revision": {
                "0001_base.py": (
                    'revision = "base1"\n'
                    'revision = "other1"\n'
                    "down_revision = None\n"
                ),
            },
            "ambiguous-depends-on": {
                "0001_base.py": (
                    'revision = "base1"\n'
                    "down_revision = None\n"
                    'depends_on = ("20260801_0100", "20260801_0100")\n'
                ),
            },
            "duplicate": {
                "0001_base.py": 'revision = "base1"\ndown_revision = None\n',
                "0002_duplicate.py": 'revision = "base1"\ndown_revision = None\n',
            },
            "dangling": {
                "0001_base.py": 'revision = "base1"\ndown_revision = "missing"\n',
            },
            "dangling-depends-on": {
                "0001_base.py": (
                    'revision = "base1"\n'
                    "down_revision = None\n"
                    'depends_on = "missing"\n'
                ),
            },
            "cycle": {
                "0001_base.py": 'revision = "base1"\ndown_revision = "next1"\n',
                "0002_next.py": 'revision = "next1"\ndown_revision = "base1"\n',
            },
            "later": {
                "0001_base.py": 'revision = "base1"\ndown_revision = None\n',
                "0002_later.py": (
                    'revision = "later1"\n'
                    'down_revision = "20260801_0100"\n'
                ),
            },
            "later-depends-on": {
                "0001_base.py": 'revision = "base1"\ndown_revision = None\n',
                "0002_later.py": (
                    'revision = "later1"\n'
                    'down_revision = "base1"\n'
                    'depends_on = "20260801_0100"\n'
                ),
            },
        }
        expected = {
            "malformed": "Unparsable Alembic migration revision",
            "malformed-down-revision": "Unparsable Alembic down_revision",
            "malformed-depends-on": "Unparsable Alembic depends_on",
            "ambiguous-revision": "Unparsable Alembic migration revision",
            "ambiguous-depends-on": "Unparsable Alembic depends_on",
            "duplicate": "Duplicate Alembic revision",
            "dangling": "Dangling Alembic down_revision/depends_on",
            "dangling-depends-on": "Dangling Alembic down_revision/depends_on",
            "cycle": "Alembic revision cycle",
            "later": "Later Alembic revisions depend",
            "later-depends-on": "Later Alembic revisions depend",
        }
        formatting_source = (ROOT / "backend/alembic/versions" / MIGRATION_NAME).read_text(
            encoding="utf-8"
        ).replace("REPLACE_WITH_CURRENT_HEAD", "base1")
        for label, files in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                versions = root / "backend/alembic/versions"
                versions.mkdir(parents=True)
                (versions / MIGRATION_NAME).write_text(
                    formatting_source, encoding="utf-8"
                )
                for name, content in files.items():
                    (versions / name).write_text(content, encoding="utf-8")
                self.assertTrue(
                    any(expected[label] in error for error in _validate_migrations(root))
                )


if __name__ == "__main__":
    unittest.main()
