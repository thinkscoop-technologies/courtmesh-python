# Releasing courtmesh (PyPI)

Releases are published by GitHub Actions when a `v*` tag is pushed, using PyPI Trusted Publishing (no API token is stored anywhere). The workflow is `.github/workflows/publish.yml`: the `build` job checks the tag against `pyproject.toml`, runs the tests, builds the sdist and wheel and runs `twine check`; the `publish` job (environment `pypi`, `id-token: write`) uploads with `pypa/gh-action-pypi-publish`.

## One time setup (a human with the right accounts)

1. Create or sign in to a PyPI account that will own the project, and enable two factor authentication.
2. Create a GitHub environment named `pypi` in `thinkscoop-technologies/courtmesh-python` (Settings, Environments, New environment). Optionally add yourself as a required reviewer so each release needs a click.
3. Because the `courtmesh` project does not exist on PyPI yet, register a pending trusted publisher: PyPI, Your account, Publishing, "Add a new pending publisher". Use:
   - PyPI project name: `courtmesh`
   - Owner: `thinkscoop-technologies`
   - Repository name: `courtmesh-python`
   - Workflow name: `publish.yml`
   - Environment name: `pypi`

   The first successful publish creates the project and turns the pending publisher into a normal one. (If the name `courtmesh` turns out to be taken on PyPI, choose a new name in `pyproject.toml` first.)
4. Make sure the repository is public.

## Every release

1. Update `version` in `pyproject.toml` and `src/courtmesh/_version.py` (they must match) and add a section to `CHANGELOG.md`.
2. Run the checks locally:

   ```bash
   python -m pip install -e ".[test]" build twine
   python -m pytest -q
   python -m build
   python -m twine check dist/*
   ```

3. Merge to `main`.
4. Tag and push the tag (the tag must be `v` plus the exact version):

   ```bash
   git checkout main && git pull
   git tag v0.6.0
   git push origin v0.6.0
   ```

5. Watch the Publish workflow (approve the `pypi` environment if you required review). When it is green, confirm with `pip index versions courtmesh`.

## If a release goes wrong

PyPI never lets you re-upload a version. Fix forward with a new patch version, and `yank` the bad release in the PyPI web UI if it should not be installed.
