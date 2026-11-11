# Design

This document explains how file_integrity is put together and why.

## 1. Goals

1. Detect unauthorized changes to critical files on RHEL 8, 9 and 10 with AIDE.
2. Keep the **known-good baseline off the host**, so a compromised host cannot
   silently re-baseline itself.
3. Run entirely from **AAP 2.6** using the supported `ee-supported-rhel9`
   execution environment and the certified `redhat.rhel_system_roles.aide`
   role, with no custom EE and no custom AIDE role.
4. Make every re-baseline **attributable**: who, when, which job, which
   approved change.

## 2. Components

| Component | Responsibility |
|---|---|
| `redhat.rhel_system_roles.aide` | Installs `aide`, templates `/etc/aide.conf`, runs `aide --init`, fetches the new DB to the controller, and removes any AIDE cron entry (`aide_cron_check: false`). |
| `playbooks/*.yml` | Orchestration: pre-flight, baseline pull/verify/restore, check, update, report, publish. |
| `playbooks/tasks/baseline_*.yml` | Backend-neutral baseline handling (see §5). |
| `playbooks/tasks/backends/git/` | Git implementation of the baseline store. |
| `playbooks/templates/aide.conf.j2` | Complete, data-driven AIDE configuration. |
| `playbooks/roles/file_integrity_defaults` | Defaults-only role holding every tunable variable (see §8). |
| Baseline repository | Private Git repo: `baselines/<inventory_hostname>/{aide.db.gz,metadata.yml}`. |
| `aap/` | Config as code: credential type, credential, EE, project, job templates, workflow, schedule. |

## 3. Trust model: why the baseline is off-host

AIDE compares the filesystem with a database. If that database only lives on
the host, anyone with root on the host can run `aide --update`, copy
`aide.db.new.gz` over `aide.db.gz`, and every later check comes back clean.

This project moves the source of truth off the host:

```
                 deploy / rebaseline (push)                  check (pull)
host ──aide --init/--update──► AAP EE ──git push──► baseline repo ──git clone──► AAP EE ──copy──► host ──aide --check
                                       metadata.yml (sha256, who, job, change ref)     verify sha256
```

- **Only Deploy and Rebaseline write to the baseline repo.** Check never
  pushes. Rebaseline requires a change reference, and the
  `AIDE - Change Rebaseline` workflow adds a human approval step.
- **Before every check** the baseline is cloned from the repo, and its sha256
  is compared with the value recorded in `metadata.yml` when it was published.
  The DB is copied onto the host, then hashed **on the host** again to confirm
  the copy is intact. Only then does `aide --check` run.
- **Whatever is on the host is ignored.** Check overwrites
  `/var/lib/aide/aide.db.gz` with the trusted copy every time, so a tampered
  on-host DB has no effect.
- **Config drift is corrected and reported.** Check renders `/etc/aide.conf`
  in check mode first. If it differs from the managed template (for example,
  someone excluded `/usr/bin`), the report sets
  `config_drift_corrected: true` and the role restores the managed config
  before the check runs.
- **Audit trail.** The Git history of the baseline repo records every
  baseline change: commit message `rebaseline: <hosts> by <user> (job <id>) [<change ref>]`,
  plus `metadata.yml` (timestamp, AAP job ID, launching user, sha256, AIDE
  version, OS, sha256 of the `aide.conf` used, and counts of accepted changes).

**What this does not protect against:** an attacker who controls AAP, the
baseline repository token, or the baseline repository itself. Protect those
with AAP RBAC, a token scoped to the single repository, branch protection
(see below) and repository audit logs.

Recommended hardening for the baseline repository:

- Private visibility; only the AAP token (and break-glass admins) can write.
- Use a fine-grained token scoped to **only** this repository with
  *Contents: read and write*. Rotate it in the AAP credential.
- Optional: require signed commits or protect `main` against force pushes so
  history cannot be rewritten.

## 4. The ephemeral-job constraint

AAP jobs run in a fresh container. Anything written to the project directory
(for example the system role's default `aide_db_fetch_dir: files`) is
discarded when the job ends. Therefore:

- Every playbook creates a scratch directory on the EE with
  `ansible.builtin.tempfile` (`playbooks/tasks/controller_workdir.yml`) and
  removes it at the end.
- The role's `aide_db_fetch_dir` points into that scratch directory. The
  fetched DB is published to the baseline backend in the **same job**.
- Nothing needs to persist between jobs except what is in the backend.

All controller-side tasks use `delegate_to: localhost` and `become: false`.
The EE has no sudo, and those tasks never need root.

## 5. Baseline backend abstraction

`aide_baseline_backend` selects the backend (default `git`, the only one
implemented). The backend-neutral task files define the contract:

| File | Role |
|---|---|
| `tasks/baseline_pull.yml` | Includes `backends/<backend>/pull.yml`, then (backend-neutral) checks that `<stage>/<prefix>/<host>/aide.db.gz` exists, loads `metadata.yml`, and verifies the sha256. Fails hosts without a baseline when `aide_baseline_required` is true. |
| `tasks/baseline_restore.yml` | Copies the verified DB onto the host and re-verifies it there. |
| `tasks/baseline_push.yml` | Copies fetched DBs into the stage dir, writes `metadata.yml`, then includes `backends/<backend>/push.yml`. |

**Backend contract**

- `pull.yml` must populate `{{ __aide_fim_stage_dir }}` on the controller so
  that `{{ aide_baseline_path_prefix }}/<inventory_hostname>/aide.db.gz` and
  `metadata.yml` exist for every host that has a baseline. Run it once
  (`run_once: true`, `delegate_to: localhost`, `become: false`).
- `push.yml` must persist everything under
  `{{ __aide_fim_stage_dir }}/{{ aide_baseline_path_prefix }}/` for the hosts
  in `aide_baseline_push_hosts`, and **fail** if persistence fails. It
  receives `__aide_fim_commit_subject` and `__aide_fim_commit_body` for
  audit records.

**Adding an `s3` backend later**

1. Create `playbooks/tasks/backends/s3/pull.yml`, which downloads
   `s3://<bucket>/<prefix>/` into the stage dir (for example with
   `amazon.aws.s3_object` or `aws s3 sync`).
2. Create `playbooks/tasks/backends/s3/push.yml`, which uploads the changed
   host folders. Enable bucket versioning and Object Lock to get the same
   history and tamper-resistance Git provides.
3. Add `s3` to `__aide_fim_supported_backends` in the defaults role, add
   backend-specific variables (bucket, region), and add a credential type
   that injects AWS credentials.
4. Add `amazon.aws` to `collections/requirements.yml`.

No playbook changes are required.

## 6. Scheduling: AAP only

Checks are scheduled **only** by the AAP scheduler (schedule
*AIDE - Daily Check* → job template *AIDE - Check*, daily at 03:00
America/Los_Angeles). This is deliberate:

| | AAP scheduler (used) | On-host cron (not used) |
|---|---|---|
| Reference DB | **Off-host** baseline, sha256-verified, restored before each run | On-host `/var/lib/aide/aide.db.gz`, which root on the host can replace |
| Tamper resistance | Strong | Weak: a compromised host can hide its own changes |
| Results | AAP job output, `set_stats`, notifications, workflows, EDA | Local log file and cron mail, easy to suppress |
| Central visibility and audit | Yes: one place for every host, with job history and RBAC | No |
| Config drift detection | Yes (re-renders `aide.conf` every run) | No |

Every playbook passes `aide_cron_check: false` to the system role. That
**removes** any `/etc/crontab` line matching `... root /usr/sbin/aide --check`
(the format the role uses), so hosts previously scheduled through the role are
cleaned up on the next Deploy, Check or Rebaseline. AIDE jobs created some
other way (for example `/etc/cron.daily/aide` or a systemd timer) are not
touched; remove them with your normal configuration management.

The trade-off is that no checks run while AAP is unavailable. Monitor the
schedule (for example, alert when *AIDE - Check* has not succeeded for more
than 24 hours) rather than adding cron as a fallback.

## 7. Role behaviour verified against the source

The spec asked for the role's variables to be verified against its README and
`defaults/main.yml` (collection `redhat.rhel_system_roles` 1.120.5). Variable
names match the spec: `aide_config_template`, `aide_db_fetch_dir`, `aide_init`,
`aide_fetch_db`, `aide_check`, `aide_update`, `aide_cron_check`,
`aide_cron_interval` (unused here, because scheduling is AAP-only).
Reading `tasks/main.yml` showed behaviour that drove these decisions:

| Finding in the role | Consequence / decision |
|---|---|
| `aide_check: true` runs `aide --check` **without registering output**. AIDE exits non-zero (1/2/4 bit flags) on any difference, so the task simply fails and the output cannot be parsed. | The check playbook runs `aide --check` itself with `failed_when: false`, parses the output in `tasks/report.yml`, and fails hosts at the very end (§9). The role still installs and configures. |
| `aide_update: true` uses `failed_when: "...NO differences..." not in stdout`, so it **fails whenever there are differences**, which is exactly the rebaseline case. | The rebaseline playbook runs `aide --update` itself (rc 0-7 = success, 14+ = error) and fetches `aide.db.new.gz`. |
| "Push baseline from controller before check" exists only as `aide_check: true` + `aide_fetch_db: true`. That combination also runs the fetch block, which fails because `aide.db.new.gz` does not exist during a check. | Baselines are restored with our own `copy` + on-host sha256 verification (`tasks/baseline_restore.yml`). |
| `aide_init` + `aide_fetch_db` fetch the new DB to `<aide_db_fetch_dir>/<host>/var/lib/aide/aide.db.new.gz` and **delete it from the host without installing it** as `aide.db.gz`. | Deploy copies the fetched DB back to the host as `aide.db.gz`, so the host matches the published baseline. |
| DB paths are hardcoded in the role's `vars/main.yml` (`/var/lib/aide/aide.db.gz`, `.new.gz`). | `aide_db_dir` must be `/var/lib/aide`; pre-flight asserts this. |
| A custom template must start with `{{ ansible_managed \| comment }}` and `system_role:aide`. The role exports `aide_version` for version-specific syntax. | `aide.conf.j2` includes both headers plus the project header, and switches between `database=`/`verbose=` (AIDE < 0.17) and `database_in=`/`log_level=`/`report_level=` (AIDE ≥ 0.17). |

## 8. Other decisions and deviations from the spec

| Spec said | Implemented | Why |
|---|---|---|
| §5.4: support `aide_schedule_mode: aap \| cron` | **AAP scheduling only.** No `aide_schedule_mode`; `aide_cron_check: false` is always passed, which removes any AIDE cron entry | Decided by the solution owner (v0.2.0). Cron checks use the on-host database and bypass the off-host trust model; see §6. |
| §6: `aap/README.md` explains running `configure_aap.yml` against a controller from a workstation | Configuration is applied **from AAP** by the self-managed *AIDE - Configure AAP* job template; `aap/README.md` is a step-by-step UI guide | The solution targets AAP, not ansible-core on a workstation. The baseline token comes from an encrypted survey; API access comes from a *Red Hat Ansible Automation Platform* credential (`AAP_*` or `CONTROLLER_*` variables). |
| `infra.aap_configuration` in a separate `aap/requirements.yml` | In `collections/requirements.yml` | AAP only installs `collections/requirements.yml` at project sync, so the config-as-code job needs its collections there. |
| Remote `gitlab.com/mlowcher/aide-fim` or `github.com/mlowcher61/aide-fim` | `github.com/mlowcher61/file_integrity` (public) and `github.com/mlowcher61/file_integrity_baselines` (private) | Chosen by the repository owner. The name `file_integrity` is used for the AAP project and the config header. |
| Rule group `CONTENT_EX` | `CONTENTEX` | AIDE 0.19 (shipped in RHEL 9.8+ and 10) deprecates non-alphanumeric group names and warns on every run. Pre-flight enforces alphanumeric names so a future AIDE release cannot break configs. |
| Global defaults in `inventory/group_vars/all/aide.yml` | Defaults in `playbooks/roles/file_integrity_defaults/defaults/main.yml`; `inventory/group_vars/all/aide.yml` holds local overrides | In AAP the inventory is a separate object, so `group_vars/` next to a project inventory file is **not loaded** unless that inventory is sourced from the project. A playbook-adjacent `group_vars/all` would load, but it would **override** group variables set in an AAP inventory (variable precedence 5 vs 3). Role defaults are always loaded at the lowest precedence. |
| `roles_path = ./roles` | Role at `playbooks/roles/`, `roles_path = ./playbooks/roles` | AAP sets `ANSIBLE_ROLES_PATH` itself. A `roles/` directory next to the playbook is always searched. |
| `collections_path = ./collections` | `./collections:~/.ansible/collections:/usr/share/ansible/collections` | `collections_path` *replaces* the default search path. Without the standard paths, collections bundled in `ee-supported-rhel9` would not be found under `ansible-navigator`. |
| `.github/workflows/lint.yml` runs linters | Also runs a report parser test with real AIDE 0.16 and 0.19 output, on ansible-core 2.16 and latest | Output formats differ between AIDE versions (for example, `Number of entries` vs `Total number of entries`), and ansible-core 2.21 changed `regex_search` behaviour. |
| `aap/vars/` files listed | Added `aap/vars/00_site.yml` (placeholders) and `aap/vars/execution_environments.yml` | Placeholders are "at the top of aap/vars/". The EE object ensures `ee-supported-rhel9` exists under that name (it is not a default AAP EE name). |
| Config validate makes no changes | Renders to a temp file on the host (removed in `always`) and compares with the live file in check mode | The job may report `changed=1` for the comparison task. That means "Deploy would update `/etc/aide.conf`"; nothing is modified. |
| `ansible.platform` preferred over `ansible.controller` | `collections/requirements.yml` lists both | `infra.aap_configuration` (validated content) uses `ansible.platform` for gateway objects and `ansible.controller` for controller objects (job templates, workflows, schedules), which `ansible.platform` does not manage. |

## 9. Check exit behaviour

`aide --check` exit codes: `0` clean; `1`, `2`, `4` (bitwise OR) = added,
removed, changed; `14` and above = error. The check playbook:

1. Runs `aide --check` with `failed_when: false` (async, up to `aide_command_timeout`).
2. Parses and reports every host (`tasks/report.yml`).
3. Prints a run-once summary of all hosts, including hosts that failed earlier.
4. Fails hosts with `status: error` (always), then hosts with
   `status: changes` when `aide_fail_on_change` is true.

Hosts that fail pre-flight or baseline verification fail immediately, but
other hosts carry on, so one bad host never hides results from the rest.

## 10. FIPS

Rule groups use `sha512` only, and pre-flight rejects md5, sha1, rmd160, tiger,
crc32/crc32b, haval, gost and whirlpool. Baseline integrity uses sha256.

AIDE 0.16 still prints MD5/SHA1/RMD160/TIGER digests *of the database file
itself* in the trailer of its report. That is AIDE's own behaviour and is not
used for any decision here.
