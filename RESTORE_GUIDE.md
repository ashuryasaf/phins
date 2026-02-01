# Platform Restore Guide

This guide explains how to restore the PHINS platform to a specific version from the git history.

## Quick Restore to January 30, 2026 at 13:00

To restore the platform to the version valid on **January 30, 2026, at 13:00 UTC**, simply run:

```bash
./restore_platform.sh
```

This will restore to commit `337d9aab5340184e499598f3174452db5f99fd93`, which was the last commit before 13:00 on that date.

## Restore to a Specific Commit

If you know the exact commit hash you want to restore to:

```bash
./restore_platform.sh <COMMIT_HASH>
```

Example:
```bash
./restore_platform.sh 337d9aab5340184e499598f3174452db5f99fd93
```

## Restore to a Specific Date/Time

You can also restore to any date/time by providing a date string:

```bash
./restore_platform.sh "YYYY-MM-DD HH:MM:SS"
```

Examples:
```bash
./restore_platform.sh "2026-01-30 13:00:00"
./restore_platform.sh "2026-01-29 12:00"
./restore_platform.sh "2026-01-01"
```

The script will find the last commit before the specified date/time and restore to that point.

## What the Script Does

1. **Validates the restore point**: Checks if the commit exists or finds the commit from the date/time
2. **Shows commit information**: Displays details about the target commit
3. **Handles uncommitted changes**: Offers to stash your current work
4. **Confirms the action**: Asks for confirmation before proceeding
5. **Restores the platform**: Checks out the target commit

## Important Notes

### Detached HEAD State

After restoring, you'll be in a "detached HEAD" state. This means you're not on any branch, just viewing a specific commit.

**To continue working from this restored point:**

```bash
# Create a new branch from the restored commit
git checkout -b restored-version-jan30

# Now you can make changes and commit them to this new branch
```

**To return to the latest version:**

```bash
git checkout main
```

### Uncommitted Changes

If you have uncommitted changes when running the restore script:
- The script will offer to stash them automatically
- You can restore them later with `git stash pop`
- Or you can view all stashes with `git stash list`

### Database State

**Important**: Restoring the code does not restore database data. If you need to restore database data:

1. **Check available backups:**
   ```bash
   ls -lah backups/
   ```

2. **Restore from a backup** (if available):
   - Backups are located in `backups/YYYYMMDD_HHMMSS/`
   - Follow the backup-specific restore instructions in `BACKUP.md`

## Available Backups

The repository includes several backups:

| Backup Date | Location | Type |
|------------|----------|------|
| January 5, 2026 | `backups/20260105T165208Z/` | Full platform snapshot |
| January 9, 2026 | `backups/20260109_210945/` | Git bundle + config |
| January 12, 2026 | `backups/20260112_222044/` | Data snapshots |

## Finding Other Restore Points

### View commits around a specific date:

```bash
git log --all --format="%H %ai %s" --before="2026-01-31" --after="2026-01-29"
```

### View commits by a specific author:

```bash
git log --all --author="name" --format="%H %ai %s" -20
```

### Search commits by message:

```bash
git log --all --grep="keyword" --format="%H %ai %s"
```

## Specific Restore Points

Here are some notable commits from January 30, 2026:

| Time (UTC) | Commit Hash | Description |
|-----------|-------------|-------------|
| 09:34:55 | 9ccf8bb91352501e8352abe6d89f1bf2c37c3e4b | Add customer marketplace API |
| 09:48:55 | 18b2728e2540adb2677453d723d9d4fa4f6cbb18 | Merge supplier marketplace changes |
| 09:51:10 | 5a12e9fa36f60f30c8ecc428defbbfddd3243a66 | Trigger deployment for supplier marketplace |
| **12:51:47** | **337d9aab5340184e499598f3174452db5f99fd93** | **Fix customer login redirect** ⭐ (13:00 default) |
| 19:41:03 | 6ce1150777a8ea5c13e9f01d148c24e58dca6595 | Redirect customers to dashboard |
| 19:46:43 | c128217ade2f550493df4e5a6f6966072ba75a3c | Add database retry logic |
| 20:07:38 | ae3b002b7e4f363d854a77b4372d82a097ebdeef | Update AGENTS.md documentation |
| 20:18:18 | 197db2cb590d21c16c586d92e258a33bc8d4930f | Fix PostgreSQL deployment issues |

⭐ The highlighted commit (12:51:47) is the version that was valid at 13:00 UTC on January 30, 2026.

## Troubleshooting

### "You are in 'detached HEAD' state"

This is normal after restoring. See the "Detached HEAD State" section above.

### "Your local changes would be overwritten"

You have uncommitted changes. Either:
- Commit them: `git add . && git commit -m "Save current work"`
- Stash them: `git stash`
- Or run the restore script again and choose to stash when prompted

### "Commit not found"

The commit might not exist in your local repository. Try:
```bash
git fetch --all
```

## Getting Help

For more information about git time travel:
```bash
man git-checkout
man git-log
```

For PHINS-specific backup/restore procedures, see:
- `BACKUP.md` - Backup procedures
- `DEPLOYMENT.md` - Deployment and rollback procedures

## Safety Tips

1. **Always commit or stash your work** before restoring
2. **Create a new branch** if you want to work from the restored point
3. **Check the backup dates** if you need to restore database data too
4. **Test the restored version** before deploying to production
5. **Document why you restored** and what version you chose

---

*Last Updated: February 1, 2026*
