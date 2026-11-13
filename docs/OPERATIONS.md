# Operations runbook

These runbooks assume AAP has been set up by following
[aap/README.md](../aap/README.md). Everything is done in the AAP UI; the
occasional `ansible-navigator` command is only for lab testing outside AAP.

| Job template / workflow | Playbook |
|---|---|
| AIDE - Validate Config | `playbooks/aide_config_validate.yml` |
| AIDE - Deploy | `playbooks/aide_deploy.yml` |
| AIDE - Check | `playbooks/aide_check.yml` |
| AIDE - Rebaseline | `playbooks/aide_rebaseline.yml` |
| AIDE - Change Rebaseline (workflow) | Validate → Approval → Rebaseline → Check |

---

## 1. First deployment

**Before you start**

- [ ] RHEL 8, 9 or 10 hosts are in the AAP inventory group `aide`.
- [ ] The private baseline repository exists and has at least one commit.
- [ ] **AIDE - Configure AAP** has run successfully (credential type,
      credential, project, job templates, workflow and schedule exist).
- [ ] The hosts are patched and in a known-good state. **The first baseline
      is trusted by definition**, so deploy right after a build or a clean
      patch cycle, not on a system you suspect is compromised.

**Steps**

1. Launch **AIDE - Validate Config**. Every host should report `Config: VALID`.
   (On a brand-new host AIDE is not installed yet, so this job fails with
   "AIDE is not installed". That is expected; continue to step 2.)
2. Launch **AIDE - Deploy**. Use *Limit* to roll out to a few hosts first.
3. In the job output, each host shows `new baseline published`. The last
   task prints the baseline repository commit, for example:
   `Baselines for web01, db01 pushed to https://github.com/... (main) as commit 7f3bec7.`
4. Launch **AIDE - Check**. Every host should be `CLEAN`.

```bash
ansible-navigator run playbooks/aide_deploy.yml -i inventory/example.yml --limit web01.example.com
```

Deploy is idempotent. Re-running it keeps existing baselines (and restores
them onto the host) unless you pass `aide_force_init=true`.

---

## 2. The daily check

**AIDE - Check** runs every day at 03:00 America/Los_Angeles (schedule
*AIDE - Daily Check*). For each host it:

1. Re-renders `/etc/aide.conf` (reporting drift if someone changed it).
2. Clones the baseline repo, verifies the baseline sha256 against `metadata.yml`.
3. Copies the trusted baseline onto the host and re-verifies it there.
4. Runs `aide --check` and prints a summary like this:

```
Host:     web01.example.com
Result:   CHANGES DETECTED - differences from the baseline
Counts:   added 2, removed 1, changed 3 (entries scanned: 45581)
Baseline: 2026-11-11T20:19:53Z sha256 5cbb36d9...
  added    /etc/cron.d/backup-new
  added    /root/.ssh/authorized_keys
  removed  /etc/motd
  changed  /etc/hosts
             SHA512 : IGtQPh5xQpisR8jU... -> Uo+VC5nvqkrSrGOo...
  changed  /usr/sbin/sshd
             Perm   : -rwxr-xr-x -> -rwsr-xr-x
             SHA512 : YIY15TBP9sed8sbJ... -> VDZIJNdi/vCxtlcq...
  changed  /root/.ssh
             Uid     : 0 -> 1000
             ACL     : A: user::rwx, A: group::---, A: other::--- -> A: user::rwx, A: group::---, A: user:1000:rwx, A: other::---
```

### Reading the report

| Line | Meaning |
|---|---|
| `Result:` | `CLEAN`, `CHANGES DETECTED`, or `ERROR` (AIDE did not finish; the error follows). |
| `Counts:` | Number of added, removed and changed entries, and how many entries AIDE scanned. |
| `Baseline:` | When the trusted baseline was created and its sha256. Every difference happened **after** this time. |
| `Config:` | Only shown when `/etc/aide.conf` had been edited on the host. It was put back. |
| `Packages:` | Count of package verdicts for the listed paths (see below). |
| `added` / `removed` | A file or directory appeared or disappeared since the baseline. |
| `changed` + indented lines | The file still exists but some attributes differ. Each indented line is `attribute : baseline value -> current value`. |
| `Package :` (indented) | Owning RPM, its install time (flagged **after the baseline** when newer), and the verdict below. |
| `Diff` (indented) | Unified diff against the content snapshot taken at the last Deploy/Rebaseline (files in `aide_content_snapshot_paths` only). Lines starting with `-` were in the baseline, `+` are new. |

Package verdicts (`aide_report_package_check`, from `rpm -qf` and `rpm -V` on
the host):

| Verdict | Meaning | What it tells you |
|---|---|---|
| `file matches the package` | `rpm -V` finds no difference (mtime-only differences ignored) | The content is exactly what the vendor shipped. If the package was installed **after the baseline**, the change is a package update: check `dnf history` for who or what ran it. |
| `config file modified locally` | A `%config` file differs from the package default | Normal for edited configuration. Look at the diff (if snapshotted) or your config management. |
| `DIFFERS FROM THE PACKAGE` | A **non-config** file (binary, library, script) differs from what its package shipped | **Suspicious.** No package update explains it. Escalate unless you know of a manual hotfix. |
| `rpm does not verify this file's contents` | The package excludes the file's digest from verification (`%verify(not md5 ...)`, for example `/etc/passwd`, `/etc/hosts`, `/etc/group` from `setup`) | RPM can neither explain nor clear the change. Use the diff or investigate. |
| `package file is missing` | The package expects the file, but it is gone | Investigate. |
| `not owned by any package` | No RPM owns the path | Locally created file: check the diff, your config management, or who created it. New unowned files in `/etc/cron.d`, `/etc/systemd/system`, `/etc/sudoers.d` or `/root/.ssh` are classic persistence. |

The RPM database lives on the monitored host, so treat verdicts as a quick
triage aid, not as proof; an attacker with root can alter it. The AIDE result
(hashes compared with the off-host baseline) is the trustworthy part.

Diffs are only shown for files listed in `aide_content_snapshot_paths`, and
only when the stored copy still matches the sha256 in `metadata.yml`. AIDE
itself stores hashes, not content, so there is no diff for other files. For
those, compare against the package (`rpm -V`, or extract the original with
`dnf download <package>` and `rpm2cpio <package>.rpm | cpio -idmv`), your
configuration management source, or a backup.

The attributes you can see:

| Attribute | What changed | Example |
|---|---|---|
| `SHA512` (or `SHA256`) | The file **contents** | Edited config file, replaced binary |
| `Perm` | Permission bits, including setuid/setgid/sticky | `-rwxr-xr-x -> -rwsr-xr-x` (setuid added) |
| `Uid` / `Gid` | Owner / group (numeric IDs) | `0 -> 1000` |
| `ACL` | POSIX ACL entries | an extra `A: user:1000:rwx` entry |
| `SELinux` | SELinux context | `ssh_home_t -> user_home_t` |
| `XAttrs` | Extended attributes | |
| `Linkcount` | Number of hard links | a new hard link to a binary |
| `File type` | Type of the entry | regular file replaced by a symlink |

Which attributes are compared depends on the path's rule group (see
[WATCHLIST.md](WATCHLIST.md#rule-groups)). For example, `/var/log` uses `LOG`,
which never reports `SHA512`.

Hash values are shortened in the job output (`aide_report_hash_chars`,
default 16 characters; set `0` to print them in full). The full old and new
values are always in the published stats:
`aide_check_results.<host>.changed_details["<path>"]`, a list of
`{attribute, old, new}`. A workflow node or EDA rulebook can use them
directly, for example to add them to a ticket.

At most `aide_report_max_paths` (200) paths are listed per host. Beyond that a
`... list truncated` line is printed, and the full report is on the host in
`/var/log/aide/aide.log`. You can also use the counts and `rpm -Va` to triage
a large patch run.

The job **fails** if any host has changes (`aide_fail_on_change: true`), but
only after every host has been checked. Add a notification template (email,
Slack, ServiceNow, etc.) on job failure to *AIDE - Check* to be alerted.

Structured results are published with `set_stats` as `aide_check_results` and
`aide_hosts_with_changes` (see the README), so a workflow node or an
Event-Driven Ansible rulebook can open a ticket automatically.

---

## 3. Triaging a failed check

Work through these questions for each reported path. The indented
`attribute : old -> new` lines under each changed path tell you *what* changed,
which usually answers the first question quickly.

**Step 1: Is it explained by an approved change?**

- Start with the `Package :` lines. A path whose package was installed
  **after the baseline** and whose file **matches the package** is a package
  update; `dnf history list` and `dnf history info <id>` show what ran it.
- Was there a patch window, package update, or configuration management run
  since the baseline timestamp (`Baseline:` line)? Check your CMDB or change
  calendar and AAP job history for the host.
- A changed `/usr/sbin/sshd` with the verdict `DIFFERS FROM THE PACKAGE` and
  no update in `dnf history` is **suspicious**.
- For snapshotted files, the `Diff` shows exactly what changed.

**Worked example (AIDE - Check job 1163, RHEL 9 on AWS).** All four hosts
reported about 30 paths the morning after deployment:

| Paths | Explanation |
|---|---|
| 22 RHUI files (`/usr/bin/rhui-*`, `/etc/pki/rhui/*`, `/etc/yum.repos.d/redhat-rhui*`, ...) | `rh-amazon-rhui-client` updated itself at 03:40 via its own `/etc/cron.daily/update-client-config-packages` (`dnf history` ID 10); `rpm -V` confirmed the files match the package. Rebaseline under a change ref. |
| `/etc/pki/entitlement/*.pem` | `rhsmcertd` renewed the subscription certificate. Excluded by default since v0.5.0. |
| `/etc/insights-client/.lastupload` | Daily Insights upload. Excluded by default since v0.5.0. |
| `/var/log/nginx/*-YYYYMMDD*`, `/var/log/audit/audit.log.1` | Log rotation. Excluded by default since v0.5.0. |

With v0.5.0 the RHUI paths show `Package : rh-amazon-rhui-client-... (installed ..., after the baseline) - file matches the package`,
so this triage takes seconds. The RHUI client keeps updating itself whenever
Amazon publishes a new version: either rebaseline when it does, or disable
that cron job and update RHUI in your normal patch window.

**Step 2: Classify it**

| Pattern | Typical cause | Action |
|---|---|---|
| Many `/usr/bin`, `/usr/lib*`, `/boot` changes right after patching | Expected package updates | Rebaseline under the patch change ref (§4). |
| `/etc/<service>/*.conf` changed, matching a config-management job | Expected config change | Rebaseline under that change ref. |
| `/etc/aide.conf` changed | You changed the watch list (expected after a watch list change) **or** someone edited it by hand (`config_drift_corrected: true`) | If expected, rebaseline. If drift, investigate who edited it. |
| New file in `/etc/cron.d`, `/etc/systemd/system`, `/etc/sudoers.d`, `/root/.ssh` | Persistence mechanisms | **Suspicious.** Escalate (Step 3). |
| Changed binary in `/usr/bin` or `/usr/sbin` with no package update | Trojaned binary | **Suspicious.** Escalate. |
| Permission or owner change only (`Perm`, `Uid`, `Gid` lines, no `SHA512`) | Manual `chmod`/`chown`, or a misbehaving script | Investigate; fix or rebaseline. |
| `Perm` gains an `s` (for example `-rwxr-xr-x -> -rwsr-xr-x`) | setuid/setgid bit added | **Suspicious** unless a package update explains it. Escalate. |
| `SELinux` context changed on a file or directory | Manual `chcon`, files moved instead of copied, or a relabel | Run `restorecon -nv <path>` to see the expected label. Escalate if it weakens confinement. |
| `SHA512` changed, `Package :` says *matches the package*, installed *after the baseline* | Legitimate package update | Rebaseline under the patch change ref. |
| `Package :` says *DIFFERS FROM THE PACKAGE* on a binary or library | Replaced or patched binary | **Suspicious.** Escalate. |
| `Diff` shows an added user, sudo rule, cron entry or weakened SSH setting | Manual change or persistence | Confirm against a change; otherwise escalate. |
| The same benign path flags on every check (e.g. an app writes a state file under `/etc`) | Noisy path | Add an exclusion or a looser rule (see [WATCHLIST.md](WATCHLIST.md)), validate, then rebaseline. |

**Step 3: If it is suspicious**

1. **Do not rebaseline.** The baseline repo is your evidence of the last
   known-good state.
2. Keep the failed AAP job output and the `aide_check_results` stats. They
   include the full old and new hashes (`changed_details`), the package
   verdicts (`package_checks`) and the diffs (`content_diffs`). Compare the
   hashes with known-good packages or threat-intelligence hashes. The content
   snapshots in the baseline repository are your copy of the known-good files.
3. Follow your incident response process (isolate the host, capture memory
   and disk, etc.).
4. After the host is rebuilt or cleaned, re-deploy it (§5, or §6 if the
   baseline itself is in question).

---

## 4. Re-baselining after an approved change

Use the **AIDE - Change Rebaseline** workflow (recommended):

1. Launch the workflow. Enter the **change reference** (e.g. `CHG0012345`)
   and the target group. Use **Limit** to re-baseline specific hosts.
2. **Validate Config** runs.
3. An approver reviews the Validate output and the change, then **approves**
   the *Approve AIDE re-baseline* node in AAP (Workflow Approvals). It expires
   after 24 hours by default (`aap_fim_approval_timeout`).
4. **Rebaseline** restores the trusted baseline, runs `aide --update`, lists
   the changes being accepted, and pushes the new DB with `metadata.yml`.
   The commit message is
   `rebaseline: <hosts> by <user> (job <id>) [CHG0012345]`.
5. **Check** runs immediately afterwards and should be `CLEAN`.

Single-host re-baseline from the job template directly: launch
**AIDE - Rebaseline**, answer the survey, and set *Limit* to the host.

```bash
ansible-navigator run playbooks/aide_rebaseline.yml -i inventory/example.yml \
  -e aide_change_ref=CHG0012345 --limit web01.example.com
```

Rebaseline **refuses to run** without `aide_change_ref`, or if it does not
match `aide_change_ref_pattern`.

---

## 5. Adding a new host

1. Add the host to the AAP inventory, in the `aide` group (or a child group).
2. Optionally set host or group variables (`aide_watch_paths_extra`, etc.).
3. Launch **AIDE - Deploy** with *Limit* set to the new host. Only that host
   gets a new baseline; existing hosts are untouched.
4. Launch **AIDE - Check** with the same limit. It should be `CLEAN`.

If you run Check before Deploy, the new host fails with:
`No AIDE baseline exists for <host> ... Run the "AIDE - Deploy" job template`.

**Renamed hosts:** baselines are stored per `inventory_hostname`. After a
rename, deploy the host under its new name, and optionally `git rm` the old
`baselines/<old-name>/` folder from the baseline repository.

**Decommissioned hosts:** remove the host from the inventory and
`git rm -r baselines/<host>` in the baseline repository (with a commit message
that references the decommission ticket).

---

## 6. Recovering a lost or corrupt baseline

**Symptoms**

- `BASELINE INTEGRITY FAILURE for <host>: the stored database sha256 ... does not match metadata.yml`
- `The baseline for <host> has no metadata.yml`
- The baseline folder for a host was deleted.

**Step 1: Find out what happened.** In the baseline repository, run:

```bash
git log --stat -- baselines/<host>/
git show <commit>          # who changed it, from which AAP job?
```

Every legitimate change is made by the AAP token with a structured commit
message. A commit by anyone else, or a force-push, is a security event.

**Step 2a: Restore from history (preferred).** If an earlier commit has a
consistent DB + `metadata.yml` pair, and you trust that state:

```bash
git checkout <good-commit> -- baselines/<host>/
git commit -m "restore: baselines/<host> from <good-commit> (INC0012345)"
git push
```

Then run **AIDE - Check** for that host and triage the results normally.

**Step 2b: Re-create the baseline.** Do this only if the host is known-good,
for example freshly rebuilt or verified with `rpm -Va`:

```bash
ansible-navigator run playbooks/aide_deploy.yml -i inventory/example.yml \
  --limit <host> -e aide_force_init=true
```

In AAP: launch **AIDE - Deploy**, set *Limit* to the host and add the extra
variable `aide_force_init: true`. The commit message starts with
`deploy-forced:` so it stands out in the audit history.

**Step 3:** Run **AIDE - Check** for the host. It should be `CLEAN`.

---

## 7. Troubleshooting

| Message | Cause | Fix |
|---|---|---|
| `AIDE is not installed on <host>` | Validate/Check/Rebaseline ran before Deploy | Run AIDE - Deploy. |
| `Could not clone the baseline repository` | Wrong URL or branch, empty repo, or a token without access | Check `aide_baseline_repo_url`, `aide_baseline_repo_branch`, that the repo has a commit, and that the credential token has read/write. |
| `the AIDE_BASELINE_GIT_TOKEN environment variable must be provided` | The baseline credential is not attached to the job template | Attach *file_integrity baseline repo token* to the template. |
| Baseline token expired or revoked | Clone or push fails with an authentication error | Launch **AIDE - Configure AAP** and enter a new token in the survey. |
| `Pushing baselines ... FAILED` | Token lacks write access, branch protection, or another job pushed at the same time | Fix permissions; for concurrent pushes, simply re-run. The new baseline was **not** saved. |
| `These rules are used in the watch list but not defined in aide_rule_groups` | Typo in a `rule:` value | Fix the variable; run Validate. |
| `Rule group names may contain only letters and digits` | e.g. `CONTENT_EX` | Rename the group (AIDE 0.19 deprecates other characters). |
| Check takes too long or times out | Very large watch list | Narrow the watch list, or raise `aide_command_timeout`. |
| `changed=1` on AIDE - Validate Config | The compare task found that Deploy would update `/etc/aide.conf` | Informational; nothing was changed. |
