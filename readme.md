# Freeze Wheel Plugin

Poetry plugin for creating frozen wheels using lockfiles.

## Why

A common issue when publishing a Python application's release into PyPI, is whether or not the dependencies specified will continue to work over time. This tends to happen due to a confluence of reasons, poor dependency specification, bad observance of semantic versioning, poor release management. That translates to a reality where installing an older release is unlikely to work, due to changes in the underlying dependecy graph.

The dependency ecosystem is both complex and fragile. The emergence of lock files to ensure repeatability is testimony both to the problem and one solution. Yet when we go to publish in the packaging ecosystem we do so with non frozen dependencies not with lockfiles. That means the testing pieplines that goes to produce a release is against a lockfile but the release is divorced of its contents.

The various language package distribution channels (npm, pypi, rubygems, etc) are used for two different distribution purposes, for both libraries and applications. Generally speaking libraries should be relatively liberal on their own dependencies baring perhaps major versions to minimize conflicts for applications depending on them and ideal consist of minimal dependencies graphs. But for applications repeatible, verifyable installs are fundamental goals with potentially large dependency graphs. ie. libraries have developers and applications as 
consumers, applications have users as consumers.

## What

A post build / pre publish command to allow for creating wheels with frozen dependencies.

## Usage

```shell
# install plugin
poetry self install poetry-plugin-freeze

# build per normal
poetry build

# add freeze step
poetry freeze-wheel

# publish per normal
poetry publish
```

## Mono-Repo Support

To support mono repos consisting of multiple libraries/applications, when creating a frozen wheel, dev dependencies specified by path can be optionally substituted out for references to their release artifact versions.

This assumes automation to run build and publish across the various subpackages.





