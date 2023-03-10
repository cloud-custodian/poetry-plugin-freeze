import csv
from email.parser import Parser
from io import StringIO
import zipfile
from poetry_plugin_freeze.app import IcedPoet, project_roots, get_sha256_digest


def test_project_roots(fixture_root):
    assert list(project_roots(fixture_root)) == [
        fixture_root / "nested_packages",
        fixture_root / "nested_packages" / "others" / "app_c",
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
        wheel.open(
            f"{iced_sub.distro_name}-{iced_sub.version}.dist-info/METADATA"
        ).read()
    )

    assert md._headers == [
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
        ("Requires-Dist", "pytest (==7.2.2)"),
        ("Requires-Dist", "pytest-cov (==4.0.0)"),
        ("Requires-Dist", "app-b (==0.1)"),
    ]

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
            "sha256=sTFPVGUHyrBa51vKxDR_p-4vAQS1pYWIsTepSOadLF4",
            "394",
        ],
    ]

    md_bytes = wheel.open(
        f"{iced_sub.distro_name}-{iced_sub.version}.dist-info/METADATA"
    ).read()
    assert len(md_bytes) == 394
    assert get_sha256_digest(md_bytes) == "sTFPVGUHyrBa51vKxDR_p-4vAQS1pYWIsTepSOadLF4"
