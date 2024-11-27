from base64 import urlsafe_b64encode
import csv
from email.parser import Parser
from functools import lru_cache
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
from poetry.core.version.markers import MultiMarker, SingleMarker
from poetry.packages import DependencyPackage
from poetry.core.masonry.metadata import Metadata
from poetry.core.masonry.utils.helpers import distribution_name
from poetry.core.version.markers import union as marker_union
from poetry.factory import Factory
from poetry.plugins.application_plugin import ApplicationPlugin

from poetry_plugin_export.walker import get_project_dependency_packages, walk_dependencies


class PetrifyCommand(Command):
    name = "petrify"

    options = [
        option("wheel-dir", None, "Sub-directory containing wheels", default="dist", flag=False),
        option(
            "exclude",
            short_name="-e",
            description="A package name to exclude from petrifying",
            flag=False,
            value_required=False,
            multiple=True,
        ),
    ]

    def handle(self) -> int:
        self.line("petrifying wheels")
        root_dir = self._io and self._io.input.option("directory") or Path.cwd()

        fridge = {}
        for project_root in project_roots(root_dir):
            iced = IcedPoet(project_root, self.option("wheel-dir"), self.option("exclude"))
            iced.check()
            fridge[iced.name] = iced

        for iced in fridge.values():
            iced.set_fridge(fridge)
            for w in iced.freeze():
                self.line(f"froze {iced.name} {iced.version} -> {w}")

        return 0


def factory():
    return PetrifyCommand()


class PetrifyApplicationPlugin(ApplicationPlugin):
    def activate(self, application):
        application.command_loader.register_factory("petrify", factory)


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

    def __init__(self, project_dir, wheel_dir="dist", exclude_packages=()):
        self.project_dir = project_dir
        self.wheel_dir = wheel_dir
        self.poetry = self.factory.create_poetry(project_dir)
        self.meta = Metadata.from_package(self.poetry.package)
        self.fridge = None
        self.exclude_packages = exclude_packages

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
                extras=root_package.extras,
            )
        )
        return {p.package.name: p for p in dep_packages}

    @lru_cache(maxsize=None)
    def get_dependency_sources(self):
        """Determine the root source of each locked dependency

        For each locked dependency, determine whether it came
        as a base requirement or part of one or more extras.
        """

        def _with_python_marker(requirements, root_package):
            """Augment requirements with the root package's python marker"""
            marked_requirements = []
            for require in requirements:
                require = require.clone()
                require.marker = require.marker.intersect(root_package.python_marker)
                marked_requirements.append(require)
            return marked_requirements

        repository = self.poetry.locker.locked_repository()
        root_package = self.poetry.package
        locked_packages_by_name = {p.name: [p] for p in repository.packages}
        dependency_sources = {}
        base_requires = [
            dep
            for dep in root_package.requires
            if not dep.is_optional() or set(dep.in_extras) <= root_package.features
        ]

        # Identify nested dependencies that don't require extra selections.
        base_nested_dependencies = walk_dependencies(
            _with_python_marker(base_requires, root_package),
            packages_by_name=locked_packages_by_name,
            root_package_name=root_package.name,
        )
        for d in base_nested_dependencies:
            dependency_sources.setdefault(d.name, set()).add("base")

        # Identify nested dependencies that come from one or more extra
        # selections.
        for extra in root_package.extras:
            extra_nested_dependencies = walk_dependencies(
                _with_python_marker(root_package.extras[extra], root_package),
                packages_by_name=locked_packages_by_name,
                root_package_name=root_package.name,
            )
            for d in extra_nested_dependencies:
                dependency_sources.setdefault(d.name, set()).add(extra)
        return dependency_sources

    def compact_markers(self, dependency):
        """Update a dependency to consolidate its markers.

        This avoids duplication when there are multiple markers
        (for sets of python versions, for example). It also records
        extra dependency markers which are lost in the conversion
        from installed package to dependency.
        """
        dep_sources = self.get_dependency_sources().get(dependency.name, set())

        # Record extra markers only if a dependency is not included
        # in the base requirement set.
        new_marker = dependency.marker.without_extras()
        in_base = "base" in dep_sources
        in_extras = dep_sources - {"base"}
        if in_extras and not in_base:
            extra_markers = marker_union(*(SingleMarker("extra", extra) for extra in in_extras))
            new_marker = MultiMarker(new_marker, extra_markers)
        dependency.marker = new_marker

    def get_frozen_deps(self, dep_packages, exclude_packages=None):
        lines = []
        dependency_sources = self.get_dependency_sources()
        for pkg_name, dep_package in dep_packages.items():
            self.compact_markers(dep_package.dependency)
            # Freeze extra markers for dependencies which were pulled in via extras
            # Don't freeze markers if a dependency is also part of the base
            # dependency tree.
            freeze_extras = "base" not in dependency_sources.get(dep_package.dependency.name, set())
            requirement = dep_package.dependency.to_pep_508(with_extras=freeze_extras)

            if dep_package.package.name in exclude_packages:
                lines.append(requirement)
                continue

            require_dist = "%s (==%s)" % (pkg_name, dep_package.package.version)
            if ";" in requirement:
                markers = requirement.split(";", 1)[1].strip()
                require_dist += f" ; {markers}"
            lines.append(require_dist)
        return lines

    def replace_deps(self, dist_meta, dep_lines):
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
            iced = IcedPoet(dep.full_path)
            # Carry markers from the root package dependency through to the iced package
            self.compact_markers(dep)
            iced_dep = iced.poetry.package.to_dependency()
            iced_dep.marker = MultiMarker(dep.marker, iced_dep.marker)
            package_dep = DependencyPackage(dependency=iced_dep, package=iced.poetry.package)
            package_deps[dep.name] = package_dep
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
            deps = self.get_path_deps(MAIN_GROUP)
            deps.update(dep_packages)
            dep_lines = self.get_frozen_deps(deps, self.exclude_packages)
            self.replace_deps(dist_meta, dep_lines)

            with source_whl.open(record_path) as record_fh:
                record_text = self.freeze_record(record_fh, dist_meta, md_path)

            (fd, temp_path) = tempfile.mkstemp(suffix=".whl")
            with (
                os.fdopen(fd, "w+b") as fd_file,
                zipfile.ZipFile(fd_file, mode="w", compression=zipfile.ZIP_DEFLATED) as frozen_whl,
            ):
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
