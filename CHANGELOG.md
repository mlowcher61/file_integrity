# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-11-11

### Added

- Playbooks `aide_deploy.yml`, `aide_check.yml`, `aide_rebaseline.yml` and
  `aide_config_validate.yml` wrapping `redhat.rhel_system_roles.aide`.
- Data-driven `aide.conf.j2` (SHA-512 only; AIDE 0.16 and 0.17+ syntax).
- Off-host baseline store with a Git backend: sha256-verified pull and
  restore, and push with `metadata.yml` and an audit-friendly commit message.
- Per-host check reports, `set_stats` publication, and fail-after-report
  behaviour controlled by `aide_fail_on_change`.
- `aap_schedule_mode` (`aap` | `cron`).
- AAP configuration as code (`infra.aap_configuration`): credential type,
  credential, EE, project, 4 job templates, approval workflow, daily schedule.
- CI: yamllint, ansible-lint (production), syntax checks, template render
  test and report parser test on ansible-core 2.16 and latest.
- Documentation: README, DESIGN, OPERATIONS, WATCHLIST, aap/README.

[0.1.0]: https://github.com/mlowcher61/file_integrity/releases/tag/v0.1.0
