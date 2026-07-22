## Objective

Describe the problem and intended outcome.

## Changes

- 

## Verification

- [ ] `ruff check .`
- [ ] Python 3.11 tests
- [ ] Python 3.12 tests
- [ ] Package build and `twine check`
- [ ] `docker compose config --quiet`
- [ ] Relevant Docker smoke tests
- [ ] Documentation updated

## Security boundary

Explain changes to target scope, networking, credentials, runner isolation, resource limits, and evidence handling.

- [ ] No secrets or private target data are included.
- [ ] The change preserves owned or explicitly authorized private-range operation.
- [ ] The change does not add destructive behavior, persistence, denial of service, credential reuse outside scope, or host escape.
