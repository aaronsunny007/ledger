# Keeping `ledger-mirror` identical to `ledger`

`aaronsunny007/ledger-mirror` is a copy of this repository's `main`. The workflow
[`sync-mirror.yml`](../.github/workflows/sync-mirror.yml) force-pushes `main` to it on every push to
`main` and once a day, so the two never drift. Nothing is ever committed to the mirror by hand.

One-time setup (about two minutes, no cost):

1. On GitHub, create an **empty public repository** named `ledger-mirror` under your account
   (no README, no licence, no `.gitignore`).
2. Create a **fine-grained personal access token**: Settings, Developer settings, Personal access
   tokens, Fine-grained tokens, Generate new token. Resource owner: you. Repository access: **Only
   select repositories**, then `ledger-mirror`. Permissions: **Contents: Read and write**. Choose an
   expiry you are comfortable with (the sync stops, harmlessly, when it expires).
3. In the `ledger` repository open Settings, Secrets and variables, Actions, New repository secret.
   Name it `MIRROR_PUSH_TOKEN` and paste the token there. Do not put it anywhere else.
4. Run the workflow once from the Actions tab (`sync-mirror`, Run workflow). The mirror then matches `main`.

Because the push is a force-push, anything committed directly to the mirror is overwritten. Treat it as
read-only and send changes to `ledger`.
