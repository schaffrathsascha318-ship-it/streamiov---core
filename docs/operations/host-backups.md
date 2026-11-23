# Streamiov Host Backup

This backup path is intentionally independent from Cloudflare R2. It snapshots the host's SQLite databases consistently with SQLite's online backup API, packages a manifest with per-database SHA-256 hashes, and encrypts the archive using the free `age` public-key encryption tool.

## Configure once on the private Linux host

1. Install age (Debian/Ubuntu): `sudo apt install age`.
2. Generate an owner-controlled identity away from the server where possible: `age-keygen -o streamiov-backup.agekey`. Keep the private identity offline and record the printed `age1…` recipient.
3. Create `/etc/streamiov/backup.env` with only the public recipient and backup path:

   ```ini
   STREAMIOV_BACKUP_AGE_RECIPIENT=age1REPLACE_WITH_OWNER_PUBLIC_RECIPIENT
   STREAMIOV_BACKUP_DIR=/var/backups/streamiov
   ```

4. Create the directory with restricted ownership: `sudo install -d -o streamiov -g streamiov -m 0700 /var/backups/streamiov`.
5. Protect the environment file: `sudo chown root:streamiov /etc/streamiov/backup.env && sudo chmod 0640 /etc/streamiov/backup.env`.
6. Install and enable the timer:

   ```sh
   sudo install -m 0644 host/systemd/streamiov-backup.service /etc/systemd/system/
   sudo install -m 0644 host/systemd/streamiov-backup.timer /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now streamiov-backup.timer
   ```

The timer creates one encrypted snapshot daily at approximately 03:17 and then attempts retention cleanup. The service reads only the allowlisted host DBs: accounts, forum, data catalog and (when present) Voice rooms. SQLite's backup API includes a consistent snapshot even while the host is running. It does not open legacy `data/db/*.sqlite3` files.

## Verify and restore safely

Copy the encrypted `.tar.gz.age` file and its `.meta.json` sidecar to an owner-controlled workstation. Keep the age private identity separate from the backup host. With the repository available and age installed:

```sh
python3 -m host.backup --backup-dir /path/to/copied/backups verify streamiov-host-YYYYMMDDTHHMMSSZ-xxxxxxxx.tar.gz.age --identity /secure/path/streamiov-backup.agekey
python3 -m host.backup --backup-dir /path/to/copied/backups restore-stage streamiov-host-YYYYMMDDTHHMMSSZ-xxxxxxxx.tar.gz.age --identity /secure/path/streamiov-backup.agekey
```

Verification checks the age authentication tag, archive paths/types, manifest, every database SHA-256 and SQLite integrity. It writes a `.verified.json` sidecar tied to the ciphertext hash. Restore creates a new private `restore-staging/` directory. **It never overwrites or swaps live databases.** Applying a staged restore remains a separate, explicitly approved maintenance operation while the host is stopped.

Retention removes only backups with an owner verification sidecar whose ciphertext hash still matches. It never deletes the last verified backup. Newly created backups remain `encrypted_pending_restore_verification` until the owner verifies them.

## Important limits

- This is encrypted local filesystem backup, not off-site replication. Put `STREAMIOV_BACKUP_DIR` on a separate disk or separately managed backup volume for disk-failure protection.
- The server has only the age public recipient; it cannot decrypt owner backups. Losing the private identity means losing the ability to restore.
- No automatic live restore, destructive database replacement, Cloudflare resource change, R2 integration, or production secret is part of this implementation.
- Install the systemd timer only after configuring the real age recipient and backup volume. A placeholder recipient must not be used.
