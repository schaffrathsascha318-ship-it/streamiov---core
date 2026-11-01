# Credential exposure remediation

Credential-like files were found tracked in the repository. Removing them from the current tree does not erase prior Git history or invalidate credentials that may have been copied.

## Required owner actions before the next public release

1. Rotate/revoke every credential that was ever stored in tracked secret files, including administrator, service, TikTok OAuth and token-encryption credentials.
2. Create replacement values outside the repository and store them as GitHub Actions secrets or environment-specific secret bindings.
3. Never paste secret values into issues, pull requests, logs or chat.
4. Confirm no active deployment depends on the removed local files; migrate runtime configuration to environment variables or a managed secret store.
5. If the repository is public, consider a history rewrite to purge old blobs after coordinating all collaborators and invalidate/reclone instructions. A current-tree deletion alone is not history cleanup.
6. Run a repository-wide secret scan and review GitHub Actions permissions before creating a production release.

## Release gate

Do not mark credential remediation complete until credentials have been rotated and a history/secret scan has been reviewed. This document intentionally contains no credential values.
