# Agent Guidelines

## Git Safety

Before any `git push` or `gh pr create` command, verify that the target remote belongs to the Canva organisation:

```bash
git remote get-url origin | grep -q 'github.com/Canva/' || (echo "ERROR: origin is not a Canva repo" && exit 1)
```

Never push to or create PRs against `open-webui/open-webui` (the upstream open-source repo). All work targets `Canva/open-webui`.

## Validating Changes

After making changes, run the format and lint step to ensure nothing is broken:

```bash
make fix
```

This formats (Prettier for frontend, Ruff for backend) and lints (ESLint for frontend, Ruff for backend) in one pass. Fix any errors before committing.

## Keep the .github directory

While we do not use the .github registry, keeping it allows much smoother updating from upstream with minimal merge conflicts.
