# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

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

[0.3.0]: https://github.com/mlowcher61/file_integrity/releases/tag/v0.3.0
[0.2.0]: https://github.com/mlowcher61/file_integrity/releases/tag/v0.2.0
[0.1.0]: https://github.com/mlowcher61/file_integrity/releases/tag/v0.1.0
