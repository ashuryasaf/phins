# How to Restore PHINS Platform to January 30, 2026 at 13:00

## Quick Answer

Run this command:

```bash
./restore_platform.sh
```

That's it! The script will:
1. Restore to commit `337d9aab` (Jan 30, 2026, 12:51:47 UTC)
2. Show you what's being restored
3. Ask for confirmation
4. Safely restore your platform

## Want to Preview First?

See what will be restored without making changes:

```bash
./preview_restore.sh
```

## Step-by-Step Instructions

### 1. Preview the Restore

```bash
cd /home/runner/work/phins/phins
./preview_restore.sh
```

This shows:
- Target commit details
- Files that will change
- How many commits you'll go back
- No changes are made

### 2. Perform the Restore

```bash
./restore_platform.sh
```

The script will:
- Show commit information
- Offer to stash any uncommitted changes
- Ask for confirmation
- Restore to the target version

### 3. After Restoring

You'll be in "detached HEAD" state. To continue working:

**Option A: Create a new branch from this point**
```bash
git checkout -b restored-jan30-version
```

**Option B: Go back to the latest version**
```bash
git checkout main
```

**Option C: Restore your previous changes (if stashed)**
```bash
git stash pop
```

## What Gets Restored?

✅ **Code**: All source files will be restored to Jan 30, 13:00 version
✅ **Configuration**: Config files and settings from that time
✅ **Documentation**: Documentation state from that date

⚠️ **Database**: NOT restored automatically
- Check `backups/` directory for database backups
- See `BACKUP.md` for database restore procedures

## Available Backups

Platform snapshots are **not** committed. After `scripts/backup_platform.sh` runs,
each snapshot is recorded for restoration:

```bash
bash scripts/restore_from_backup.sh --list
bash scripts/restore_from_backup.sh --print-commands
```

The commit-safe catalog (git SHA + checksums only) is
`docs/platform_restore_catalog.json`. The snapshot bytes live under `backups/`
(gitignored). See `BACKUP.md` for restore commands.

## Other Restore Options

### Restore to a different commit

```bash
./restore_platform.sh <COMMIT_HASH>
```

### Restore to a different date/time

```bash
./restore_platform.sh "2026-01-29 15:00"
```

### Find other commits

```bash
git log --all --format="%H %ai %s" --before="2026-01-31" | head -20
```

## Important Notes

1. **Save your work first**: The script will offer to stash changes, but commit or stash manually if you prefer
2. **Database separate**: Code restore doesn't restore database data
3. **Detached HEAD**: After restore, create a branch or return to main
4. **Reversible**: You can always go back to the latest version

## Need Help?

- **Full guide**: See `RESTORE_GUIDE.md`
- **Backup info**: See `BACKUP.md`
- **Deployment**: See `DEPLOYMENT.md`

## Troubleshooting

**"You have uncommitted changes"**
- Commit them: `git add . && git commit -m "Save work"`
- Or stash: `git stash`

**"Commit not found"**
- Fetch latest: `git fetch --all`

**"Detached HEAD" warning**
- This is normal! See step 3 above

## Quick Commands Reference

```bash
# Preview restore
./preview_restore.sh

# Perform restore
./restore_platform.sh

# Create branch after restore
git checkout -b my-restored-version

# Go back to latest
git checkout main

# View stashed changes
git stash list

# Restore stashed changes
git stash pop
```

---

**Questions?** See full documentation in `RESTORE_GUIDE.md`
