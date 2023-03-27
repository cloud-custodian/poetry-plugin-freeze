from base64 import urlsafe_b64encode
import csv
from email.parser import Parser
import hashlib
from io import StringIO, TextIOWrapper
from pathlib import Path
import shutil
import os
import tempfile
import zipfile

from cleo.helpers import option
from poetry.console.commands.command import Command
from poetry.core.packages.dependency_group import MAIN_GROUP
from poetry.packages import DependencyPackage
from poetry.core.masonry.metadata import Metadata
from poetry.core.masonry.utils.helpers import distribution_name
from poetry.factory import Factory
from poetry.plugins.application_plugin import ApplicationPlugin

from poetry_plugin_export.walker import get_project_dependency_packages


class FreezeCommand(Command):
    name = "freeze-wheel"

    options = [option("wheel-dir", None, "Sub-directory containing wheels")]

    def handle(self) -> int:
        self.line("freezing wheels")
        root_dir = self._io and self._io.input.option("directory") or Path.cwd()

        fridge = {}
        for project_root in project_roots(root_dir):
            iced = IcedPoet(project_root)
            iced.check()
            fridge[iced.name] = iced

        for iced in fridge.values():
            iced.set_fridge(fridge)
            for w in iced.freeze():
                self.line(f"froze {iced.name} {iced.version} -> {w}")

        return 0


def factory():
    return FreezeCommand()


class FreezeApplicationPlugin(ApplicationPlugin):
    def activate(self, application):
        application.command_loader.register_factory("freeze-wheel", factory)


def project_roots(root):
    for config_path in Path(root).rglob("pyproject.toml"):
        yield config_path.parent


def get_sha256_digest(content: bytes):
    hashsum = hashlib.sha256()
    hashsum.update(content)
    hash_digest = urlsafe_b64encode(hashsum.digest()).decode("ascii").rstrip("=")
    return hash_digest


class IcedPoet:
    factory = Factory()

    def __init__(self, project_dir, wheel_dir="dist"):
        self.project_dir = project_dir
        self.wheel_dir = wheel_dir
        self.poetry = self.factory.create_poetry(project_dir)
        self.meta = Metadata.from_package(self.poetry.package)
        self.fridge = None

    def set_fridge(self, fridge):
        self.fridge = fridge

    def check(self):
        assert self.poetry.locker.is_locked() is True
        assert self.poetry.locker.is_fresh() is True

    @property
    def name(self):
        return self.poetry.package.name

    @property
    def distro_name(self):
        return distribution_name(self.name)

    @property
    def version(self):
        return self.poetry.package.version

    def get_wheels(self):
        dist_dir = self.project_dir / self.wheel_dir
        wheels = list(dist_dir.glob("*whl"))
        prefix = "%s-%s" % (self.distro_name, self.meta.version)
        for w in wheels:
            if not w.name.startswith(prefix):
                continue
            yield w

    def freeze(self):
        wheels = list(self.get_wheels())
        if not wheels:
            return []
        dep_package_map = self.get_dep_packages()
        for w in wheels:
            self.freeze_wheel(w, dep_package_map)
        return wheels

    def get_dep_packages(self):
        root_package = self.poetry.package.with_dependency_groups([MAIN_GROUP], only=True)

        dep_packages = list(
            get_project_dependency_packages(
                self.poetry.locker,
                project_requires=root_package.all_requires,
                root_package_name=root_package.name,
                project_python_marker=root_package.python_marker,
            )
        )
        return {p.package.name: p for p in dep_packages}

    def get_frozen_deps(self, dep_packages):
        lines = []
        for pkg_name, dep_package in dep_packages.items():
            require_dist = "%s (==%s)" % (pkg_name, dep_package.package.version)
            requirement = dep_package.dependency.to_pep_508(with_extras=False)
            if ";" in requirement:
                markers = requirement.split(";", 1)[1].strip()
                require_dist += f" ; {markers}"
            lines.append(require_dist)
        return lines

    def replace_deps(self, dist_meta, dep_lines):
        frozen_headers = []
        start_pos = 0
        for m in dist_meta.get_all("Requires-Dist"):
            if not start_pos:
                start_pos = dist_meta._headers.index(("Requires-Dist", m))
            dist_meta._headers.remove(("Requires-Dist", m))

        for idx, h in enumerate(dep_lines):
            dist_meta._headers.insert(start_pos + idx, ("Requires-Dist", h))

        return dist_meta

    def get_path_deps(self, group="dev"):
        # assuming we're consistent install across deps.
        package_deps = {}
        group = self.poetry.package.dependency_group(group)
        for dep in group.dependencies:
            if not (dep.is_file() or dep.is_directory()):
                continue
            if dep.is_vcs() or dep.is_url():
                continue
            assert dep.name in self.fridge, f"Unknown path dependency {dep.name}"
            iced = self.fridge[dep.name]
            package_deps[dep.name] = DependencyPackage(
                dependency=iced.poetry.package.to_dependency(), package=iced.poetry.package
            )
            package_deps.update(iced.get_dep_packages())
        return package_deps

    def freeze_record(self, records_fh, dist_meta, md_path):
        hash_digest = get_sha256_digest(str(dist_meta).encode("utf8"))
        output = StringIO()
        csv_params = {
            "delimiter": csv.excel.delimiter,
            "quotechar": csv.excel.quotechar,
            "lineterminator": "\n",
        }
        writer = csv.writer(output, **csv_params)
        reader = csv.reader(TextIOWrapper(records_fh, encoding="utf8"), **csv_params)

        for row in reader:
            if row[0] == md_path:
                continue
            writer.writerow(row)

        writer.writerow((md_path, f"sha256={hash_digest}", len(str(dist_meta).encode("utf8"))))
        return output.getvalue()

    def freeze_wheel(self, wheel_path, dep_packages):
        dist_info = "%s-%s.dist-info" % (
            self.distro_name,
            self.meta.version,
        )
        md_path = f"{dist_info}/METADATA"
        record_path = f"{dist_info}/RECORD"

        with zipfile.ZipFile(wheel_path) as source_whl:
            # freeze deps in metadata and update records
            md_text = source_whl.open(md_path).read().decode("utf8")
            dist_meta = Parser().parsestr(md_text)
            deps = self.get_path_deps()
            deps.update(dep_packages)
            dep_lines = self.get_frozen_deps(deps)
            self.replace_deps(dist_meta, dep_lines)

            with source_whl.open(record_path) as record_fh:
                record_text = self.freeze_record(record_fh, dist_meta, md_path)

            (fd, temp_path) = tempfile.mkstemp(suffix=".whl")
            with os.fdopen(fd, "w+b") as fd_file, zipfile.ZipFile(
                fd_file, mode="w", compression=zipfile.ZIP_DEFLATED
            ) as frozen_whl:
                # first copy all files to frozen zip
                for info in source_whl.infolist():
                    if info.filename in (md_path, record_path):
                        sample = info
                        continue
                    info_fh = source_whl.open(info)
                    frozen_whl.writestr(info, info_fh.read(), compress_type=zipfile.ZIP_DEFLATED)

                # finally add in our modified files
                date_time = (2016, 1, 1, 0, 0, 0)

                md_info = zipfile.ZipInfo(md_path, date_time)
                md_info.external_attr = sample.external_attr
                frozen_whl.writestr(
                    md_info,
                    str(dist_meta).encode("utf8"),
                    compress_type=zipfile.ZIP_DEFLATED,
                )

                record_info = zipfile.ZipInfo(record_path, date_time)
                record_info.external_attr = sample.external_attr
                frozen_whl.writestr(record_path, record_text, compress_type=zipfile.ZIP_DEFLATED)

        shutil.move(temp_path, str(wheel_path))
