# file_integrity_defaults

A **defaults-only** role (no tasks) that lives next to the playbooks
(`playbooks/roles/`), so Ansible always finds it. Every playbook lists it
under `roles:` so the variables in `defaults/main.yml` are loaded at the
lowest possible precedence.

Why not `inventory/group_vars/all`? In Ansible Automation Platform the
inventory is a separate object, so `group_vars/` that live next to an
inventory file in the project are **not** loaded unless that inventory is
sourced from this project. Role defaults are always loaded, and anything you
set in AAP (inventory, group, host variables, or extra vars) overrides them.

See `docs/DESIGN.md` and the variable reference in the top-level `README.md`.
