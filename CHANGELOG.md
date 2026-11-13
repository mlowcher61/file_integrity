# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.4.0] - 2026-11-13

### Added

- Check and Rebaseline reports now show **what changed** on every changed
  path, not only the path: one `attribute : old -> new` line per changed
  attribute (for example `Perm`, `Uid`, `SELinux`, `ACL`, `SHA512`), parsed
  from AIDE's "Detailed information about changes" section.
- `changed_details` (`{path: [{attribute, old, new}]}`, full hash values) in
  `aide_check_results` / `aide_rebaseline_results` (`set_stats`).
- `aide_report_hash_chars` (default `16`): how much of each hash is printed
  in the job output (`0` = full value).
- Filter plugins `aide_change_details` and `aide_change_lines`
  (`playbooks/roles/file_integrity_defaults/filter_plugins/aide_report.py`).
- Report parser test: change-detail assertions for AIDE 0.16 and 0.19, and a
  new fixture covering `Perm`, `Uid`, multi-line `ACL` and wrapped `SELinux`
  values.
- README "Reading a Check report" and docs/OPERATIONS.md "Reading the report"
  sections; new triage patterns (setuid added, SELinux context change).

### Fixed

- Baseline repository clone and push failed in AAP: the token was inserted
  into the HTTPS URL with a `regex_replace` backreference inside a folded YAML
  scalar, which rendered as a literal `\1` and dropped the `https://` scheme.
  The URL is now built with a plain string replace, and `/` in tokens is
  percent-encoded.
- A failed baseline clone now shows git's error message (token masked)
  instead of only a generic hint.

## [0.3.1] - 2026-11-12

### Fixed

- `AIDE - Configure AAP` hid the cause of failures (`censored ... no_log`)
  because secure logging was enabled for every role. Only the credentials
  role (which handles the baseline token) is now secure-logged; all other
  errors are shown in full.
- `community.general` pinned to `>=10.0.0,<12.0.0`; 12.x does not support
  the ansible-core 2.16 shipped in the AAP 2.6 supported EEs.

### Added

- Pre-flight checks in `configure_aap.yml` confirm that the organization,
  inventories and credentials named in the site settings exist (and that the
  baseline credential exists when no token is entered), and name any that
  are missing before anything is created.

## [0.3.0] - 2026-11-12

### Added

- `file_integrity` label (`aap_fim_label`) created by config as code and
  applied to every object that supports labels in AAP: the 5 job templates,
  the `AIDE - Change Rebaseline` workflow and the `AIDE - Daily Check`
  schedule. `AIDE - Check` now prompts for labels on launch, which AAP
  requires for a schedule to carry a label.

## [0.2.0] - 2026-11-11

### Changed

- **AAP-only scheduling.** Removed cron mode (`aide_schedule_mode`). The
  playbooks always pass `aide_cron_check: false`, which removes any AIDE cron
  entry from hosts. Checks run only from the AAP schedule against the
  verified off-host baseline.
- **Configuration as code now runs from AAP.** The new self-managed job
  template *AIDE - Configure AAP* runs `aap/configure_aap.yml` with a
  *Red Hat Ansible Automation Platform* credential (accepts `AAP_*` or
  `CONTROLLER_*` variables). The baseline repository token is entered in an
  encrypted survey (blank keeps the existing token, a new value rotates it).
- `infra.aap_configuration`, `ansible.platform` and `ansible.controller`
  moved into `collections/requirements.yml` (installed at project sync);
  removed `aap/requirements.yml`.
- `aap/README.md` rewritten as a step-by-step guide to deploying from the AAP UI.
- README: local `ansible-navigator` usage moved to an optional
  "Testing outside AAP" section.

### Fixed

- Deploy took the initial baseline before removing an existing AIDE cron
  entry, so the first check reported `/etc/crontab` as changed. Deploy now
  configures the host (including cron removal) before initializing.

### Added

- `aap_fim_aap_credential` and `aap_fim_config_inventory` site settings.

## [0.1.0] - 2026-11-11

### Added

- Playbooks `aide_deploy.yml`, `aide_check.yml`, `aide_rebaseline.yml` and
  `aide_config_validate.yml` wrapping `redhat.rhel_system_roles.aide`.
- Data-driven `aide.conf.j2` (SHA-512 only; AIDE 0.16 and 0.17+ syntax).
- Off-host baseline store with a Git backend: sha256-verified pull and
  restore, and push with `metadata.yml` and an audit-friendly commit message.
- Per-host check reports, `set_stats` publication, and fail-after-report
  behaviour controlled by `aide_fail_on_change`.
- Scheduling mode switch (`aap` | `cron`); removed in 0.2.0.
- AAP configuration as code (`infra.aap_configuration`): credential type,
  credential, EE, project, 4 job templates, approval workflow, daily schedule.
- CI: yamllint, ansible-lint (production), syntax checks, template render
  test and report parser test on ansible-core 2.16 and latest.
- Documentation: README, DESIGN, OPERATIONS, WATCHLIST, aap/README.

[0.4.0]: https://github.com/mlowcher61/file_integrity/releases/tag/v0.4.0
[0.3.1]: https://github.com/mlowcher61/file_integrity/releases/tag/v0.3.1
[0.3.0]: https://github.com/mlowcher61/file_integrity/releases/tag/v0.3.0
[0.2.0]: https://github.com/mlowcher61/file_integrity/releases/tag/v0.2.0
[0.1.0]: https://github.com/mlowcher61/file_integrity/releases/tag/v0.1.0
