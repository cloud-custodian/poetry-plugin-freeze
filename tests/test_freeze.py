import csv
from email.parser import Parser
from io import StringIO
import zipfile
from poetry_plugin_freeze.app import IcedPoet, project_roots, get_sha256_digest


def test_project_roots(fixture_root):
    assert sorted(project_roots(fixture_root)) == [
        fixture_root / "nested_packages",
        fixture_root / "nested_packages" / "others" / "app_c",
        fixture_root / "nested_packages" / "others" / "app_with_extras",
    ]


def parse_md(md_text: bytes):
    return Parser().parsestr(md_text.decode("utf8"))


def parse_record(record_text: bytes):
    return list(csv.reader(StringIO(record_text.decode("utf8"))))


def test_freeze_nested(fixture_root, fixture_copy):
    package = fixture_copy(fixture_root / "nested_packages")
    sub_package = fixture_copy(fixture_root / "nested_packages" / "others" / "app_c")

    iced_pkg = IcedPoet(package)
    iced_sub = IcedPoet(sub_package)
    fridge = {iced_pkg.name: iced_pkg, iced_sub.name: iced_sub}
    iced_sub.set_fridge(fridge)

    wheels = iced_sub.freeze()
    assert len(wheels) == 1

    wheel = zipfile.ZipFile(wheels[0])

    records = parse_record(
        wheel.open(f"{iced_sub.distro_name}-{iced_sub.version}.dist-info/RECORD").read()
    )
    md = parse_md(
        wheel.open(f"{iced_sub.distro_name}-{iced_sub.version}.dist-info/METADATA").read()
    )

    expected_headers = [
        ("Metadata-Version", "2.1"),
        ("Name", "app-c"),
        ("Version", "0.2"),
        ("Summary", "lorem ipsum"),
        ("License", "Apache-2.0"),
        ("Author", "SideCars"),
        ("Requires-Python", ">=3.11,<4.0"),
        ("Classifier", "License :: OSI Approved :: Apache Software License"),
        ("Classifier", "Programming Language :: Python :: 3"),
        ("Classifier", "Programming Language :: Python :: 3.11"),
        (
            "Requires-Dist",
            'pytest (==7.2.2) ; python_version >= "3.10" and python_version < "4.0"',
        ),
        (
            "Requires-Dist",
            'attrs (==22.2.0) ; python_version >= "3.10" and python_version < "4.0"',
        ),
        (
            "Requires-Dist",
            'colorama (==0.4.6) ; python_version >= "3.10" and python_version < "4.0" '
            'and sys_platform == "win32"',
        ),
        (
            "Requires-Dist",
            'exceptiongroup (==1.1.0) ; python_version >= "3.10" and python_version < "3.11"',
        ),
        (
            "Requires-Dist",
            'iniconfig (==2.0.0) ; python_version >= "3.10" and python_version < "4.0"',
        ),
        (
            "Requires-Dist",
            'packaging (==23.0) ; python_version >= "3.10" and python_version < "4.0"',
        ),
        (
            "Requires-Dist",
            'pluggy (==1.0.0) ; python_version >= "3.10" and python_version < "4.0"',
        ),
        (
            "Requires-Dist",
            'tomli (==2.0.1) ; python_version >= "3.10" and python_full_version <= ' '"3.11.0a6"',
        ),
        (
            "Requires-Dist",
            'pytest-cov (==4.0.0) ; python_version >= "3.10" and python_version < "4.0"',
        ),
        (
            "Requires-Dist",
            'coverage (==7.2.1) ; python_version >= "3.10" and python_version < "4.0"',
        ),
    ]
    assert sorted(md._headers) == sorted(expected_headers)

    assert records == [
        [
            "app_c/__init__.py",
            "sha256=47DEQpj8HBSa-_TImW-5JCeuQeRkm5NMpJWZG3hSuFU",
            "0",
        ],
        [
            "app_c-0.2.dist-info/WHEEL",
            "sha256=kLuE8m1WYU0Ig0_YEGrXyTtiJvKPpLpDEiChiNyei5Y",
            "88",
        ],
        ["app_c-0.2.dist-info/RECORD", "", ""],
        [
            "app_c-0.2.dist-info/METADATA",
            "sha256=ZTdp4AJVW1WFj_Wv5oUVdtUC1_5r9bYWNxDzssJgO6o",
            "1217",
        ],
    ]

    md_bytes = wheel.open(f"{iced_sub.distro_name}-{iced_sub.version}.dist-info/METADATA").read()
    assert len(md_bytes) == 1217
    assert get_sha256_digest(md_bytes) == "ZTdp4AJVW1WFj_Wv5oUVdtUC1_5r9bYWNxDzssJgO6o"


def test_freeze_extras(fixture_root, fixture_copy):
    nested_packages = fixture_copy(fixture_root / "nested_packages")

    iced_pkg = IcedPoet(nested_packages / "others" / "app_with_extras")
    iced_pkg.set_fridge({iced_pkg.name: iced_pkg})
    wheels = iced_pkg.freeze()
    assert len(wheels) == 1

    wheel = zipfile.ZipFile(wheels[0])

    md = parse_md(
        wheel.open(f"{iced_pkg.distro_name}-{iced_pkg.version}.dist-info/METADATA").read()
    )

    md_requirements = {}
    for header_type, header_value in md._headers:
        if header_type != "Requires-Dist":
            continue
        pkg_name, requirements = header_value.split(maxsplit=1)
        md_requirements[pkg_name] = requirements

    # app-c is installed as part of the "bells" extra
    assert 'extra == "bells"' in md_requirements["app-c"]

    # ruff shows up in both the base dependency tree
    # and as part of extras. Its inclusion in the base
    # set of dependencies should prevent it from carrying
    # an extra marker.
    assert "extra" not in md_requirements["ruff"]

    # tomli is an optional/extra dependency of coverage,
    # which can be pulled in by one or more top-level extra selections.
    # The frozen requirement should only include markers for
    # extras defined in the root package.
    assert all(
        [
            'extra == "bells"' in md_requirements["tomli"],
            'extra == "whistles"' in md_requirements["tomli"],
            'extra == "toml"' not in md_requirements["tomli"],
        ]
    )
