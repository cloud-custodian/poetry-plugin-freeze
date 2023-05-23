# Freeze Wheel Plugin

Poetry plugin for creating frozen wheels using lockfiles.

## Why

A common issue when publishing a Python application's release into PyPI, is whether or not the dependencies specified will continue to work over time. This tends to happen due to a confluence of reasons, poor dependency specification, bad observance of semantic versioning, or poor release management by the dependency. That translates to a reality where installing an older release of the application is unlikely to work, due to changes in the underlying dependency graph.

The dependency ecosystem is both complex and fragile. The emergence of lock files to ensure repeatability is testimony both to the problem and one solution. Yet when we go to publish in the packaging ecosystem we do so with non frozen dependencies specifications not with lockfiles. That means the testing pipelines that goes to produce and validate a release is against a lockfile but the release artifact is divorced of the lockfile contents, and starts to diverge from the moment of publication.

The various language package distribution channels (npm, pypi, rubygems, etc) are used for two different primary distribution purposes, for both libraries and applications. Generally speaking the extant behavior is reasonable for a library. Libraries should be relatively liberal on their own dependencies baring perhaps major versions to minimize conflicts for applications depending on them and ideally consist of minimal dependencies graphs. But for applications distribution, repeatable and verifyable installs are fundamental goals with potentially large dependency graphs. Using a frozen dependency graph versus version specifications is the only way to ensure repeatiblity of installation over time. Fundamentally the two different distribution purposes have different audiences, ie.  libraries have developers and applications as consumers, applications have users as consumers.

## What

A post build / pre publish command to allow for creating wheels with frozen dependencies. Basically we update wheel metadata for Requires-Dist to replace the pyproject.toml based version specification to a frozen (ie. ==version) one based on the version from the poetry lock information.


Note we can't use poetry to publish because the frozen wheel because it uses metadata from pyproject.toml instead
of frozen wheel metadata.

### Optional Dependencies

Frozen wheel metadata will contain [Provides-Extra](https://packaging.python.org/en/latest/specifications/core-metadata/#provides-extra-multiple-use) entries for any [extra / optional dependencies](https://packaging.python.org/en/latest/specifications/declaring-project-metadata/#dependencies-optional-dependencies). Frozen [Requires-Dist](https://packaging.python.org/en/latest/specifications/core-metadata/#core-metadata-requires-dist) lines will specify `extra` names _for packages that appear only in the optional/extra dependency graph.

If a package appears as both a nested "main" dependency and also as an "extra" dependency, its `Requires-Dist` entry in the frozen wheel _will not_ specify an extra name.

To define this behavior in relation to poetry's [export plugin](https://github.com/python-poetry/poetry-plugin-export/), these two flows should result in the same installed package set:

```console
# Export Flow
poetry export -f requirements.txt > requirements.txt && pip install -r requirements.txt

# Freeze-wheel Flow
poetry build && poetry freeze-wheel && pip install my_frozen_wheel
```

And introducing extras:

```console
# Export Flow
poetry export --extras gcp -f requirements.txt && pip install -r requirements.txt

# Freeze-wheel Flow
poetry build && poetry freeze-wheel && pip install my_frozen_wheel[gcp]
```

The difference is in when to choose which extras to install - `export` does that at freeze time. `freeze-wheel` embeds the extra _context_ at freeze time, but defers the actual extra selection until install time.

## Usage

```shell
# install plugin
poetry self add poetry-plugin-freeze

# build per normal
poetry build

# add freeze step
poetry freeze-wheel

# Note we can't use poetry to publish because it uses metadata from pyproject.toml instead 
# of frozen wheel metadata.

# publish per normal
twine upload dist/*.whl
```

## Mono-Repo Support

To support mono repos consisting of multiple libraries/applications, when creating a frozen wheel, main group dependencies specified by path can be optionally substituted out for references to their release artifact versions.

This assumes automation to run build and publish across the various subpackages, ie typically via make or just.
