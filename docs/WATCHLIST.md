# Managing the AIDE watch list

`/etc/aide.conf` is rendered entirely from Ansible variables by
`playbooks/templates/aide.conf.j2`. Do not edit `/etc/aide.conf` on a host.
**AIDE - Check** puts the managed version back and reports the drift.

The defaults are in
[`playbooks/roles/file_integrity_defaults/defaults/main.yml`](../playbooks/roles/file_integrity_defaults/defaults/main.yml).
Override them wherever you manage variables:

| Where | Scope | Typical use |
|---|---|---|
| AAP inventory → *Variables* | Every host in the inventory | Site-wide watch list changes |
| AAP inventory group → *Variables* | Hosts in that group | Role-specific additions (`webservers`, `dbservers`) |
| AAP host → *Variables* | One host | One-off exceptions |
| `inventory/group_vars/<group>/aide.yml` | Local runs (or an inventory sourced from this project) | Same as above |
| Job template *Extra variables* | Every run of that template (highest precedence) | Avoid for watch lists: it overrides everything |

## Workflow for any watch list change

1. Change the variables.
2. Run **AIDE - Validate Config**. It renders the new config and runs
   `aide --config-check`, without changing anything.
3. Run **AIDE - Change Rebaseline** with a change reference. The next check
   would otherwise report every newly watched file as `added` (and
   `/etc/aide.conf` as `changed`).

## Adding paths

### For every host

Add an entry to `aide_watch_paths` at the inventory level. Because this
replaces the whole default list, copy the defaults and append:

```yaml
aide_watch_paths:
  - { path: /boot, rule: CONTENTEX }
  - { path: /etc, rule: CONTENTEX }
  - { path: /usr/bin, rule: CONTENTEX }
  - { path: /usr/sbin, rule: CONTENTEX }
  - { path: /usr/lib, rule: CONTENTEX }
  - { path: /usr/lib64, rule: CONTENTEX }
  - { path: /root/.ssh, rule: CONTENTEX }
  - { path: /var/log, rule: LOG }
  - { path: /opt/company/bin, rule: CONTENTEX }   # new
```

### For a group or a single host

Use `aide_watch_paths_extra`. It is **merged** with `aide_watch_paths`, so
there is no need to copy the defaults:

```yaml
# AAP group "webservers" → Variables
aide_watch_paths_extra:
  - { path: /var/www/cgi-bin, rule: CONTENTEX }
  - { path: /var/www/html, rule: PERMS }
```

Merge rules:

- Entries are de-duplicated by `path`.
- If a path appears in both lists, the `aide_watch_paths_extra` entry wins.
  This is how you change the rule for a default path on some hosts:

  ```yaml
  aide_watch_paths_extra:
    - { path: /etc, rule: PERMS }   # these hosts: only ownership/permissions for /etc
  ```

**Note:** Ansible does not merge a variable set at two levels (for example,
group `webservers` and group `rhel9`). The more specific group wins. If a host
needs additions from several groups, put the combined list at the most
specific level, or on the host.

### Path syntax

Each `path` is an AIDE *selection line*, which is a regular expression
anchored at the start of the full path:

| You write | AIDE watches |
|---|---|
| `/etc` | `/etc` and everything below it (also `/etcetera`, if it existed) |
| `/usr/lib` | `/usr/lib/...` **and** `/usr/lib64/...` (prefix match) |
| `/etc/ssh/sshd_config$` | Exactly that file |
| `/root/\.ssh` | `/root/.ssh` with a literal dot (an unescaped `.` matches any character) |

Paths must start with `/`. Pre-flight rejects entries without a `path` or
`rule`.

## Removing paths

- **For everyone:** override `aide_watch_paths` without the entry.
- **For a group or host:** you cannot remove a default entry from
  `aide_watch_paths_extra`. Add an exclusion instead (`aide_exclude_paths_extra`).

## Rule groups

`aide_rule_groups` maps a name to an AIDE attribute expression:

```yaml
aide_rule_groups:
  CONTENTEX: "sha512+ftype+p+u+g+n+acl+selinux+xattrs"   # content + metadata
  PERMS: "p+u+g+acl+selinux+xattrs"                     # metadata only
  LOG: "p+u+g+n+acl+selinux+ftype"                      # growing log files
```

To add one, override the whole dict (copy the defaults and add yours):

```yaml
aide_rule_groups:
  CONTENTEX: "sha512+ftype+p+u+g+n+acl+selinux+xattrs"
  PERMS: "p+u+g+acl+selinux+xattrs"
  LOG: "p+u+g+n+acl+selinux+ftype"
  BINARY: "sha512+ftype+p+u+g+n+s+i+acl+selinux+xattrs"   # also size and inode
```

Rules:

- **Names: letters and digits only** (`CONTENTEX`, not `CONTENT_EX`). AIDE
  0.19, shipped in RHEL 9.8+ and 10, deprecates any other character.
  Pre-flight enforces this.
- **Hashes: `sha512` (or `sha256`) only.** Pre-flight rejects md5, sha1,
  rmd160, tiger, crc32, crc32b, haval, gost and whirlpool (not FIPS-approved).
- Every `rule` used in the watch lists must exist here. Pre-flight lists any
  that are missing.

Common attributes:

| Attribute | Meaning |
|---|---|
| `p` `u` `g` | permissions, user, group |
| `n` | number of links |
| `s` | size |
| `i` | inode |
| `m` `c` `a` | mtime, ctime, atime (avoid `a`: reading a file changes it) |
| `ftype` | file type (file, directory, symlink, ...) |
| `acl` `selinux` `xattrs` | POSIX ACLs, SELinux context, extended attributes |
| `sha512` | content hash |

## Exclusions

`aide_exclude_paths` (global) and `aide_exclude_paths_extra` (group/host) are
rendered as `!<path>` lines. They use the same regular-expression syntax as
watch paths. In AIDE, negative selection lines win over positive ones.

Defaults and why:

| Exclusion | Reason |
|---|---|
| `/etc/mtab` | Symlink to `/proc/self/mounts`; its target changes constantly. |
| `/etc/.*~` | Editor backup files (`file~`); noise, not configuration. |
| `/var/log/journal` | Binary systemd journal; rotated and rewritten continuously. |
| `/var/lib/aide` | AIDE's own databases; they change on every init or update. |
| `/var/log/aide` | AIDE's own reports; written on every check. |

Other common exclusions to consider (add them to `aide_exclude_paths_extra`
on the hosts where they apply):

| Exclusion | Reason |
|---|---|
| `/etc/adjtime` | Updated by the clock subsystem. |
| `/etc/lvm/archive`, `/etc/lvm/backup` | Rewritten on every LVM metadata change. |
| `/etc/pki/ca-trust/extracted` | Regenerated by `update-ca-trust`; watch `/etc/pki/ca-trust/source` instead. |
| `/etc/sysconfig/.*\.rpmnew` | Package upgrade artefacts. |
| `/var/cache/httpd` | Apache runtime cache (see the `webservers` example). |
| `/etc/resolv.conf` | Rewritten by NetworkManager/DHCP on many hosts. |
| `/etc/tuned/.*\.conf` | Updated by `tuned` profile switches. |

Exclude as little as possible. Every exclusion is a place an attacker can
hide. Prefer a looser rule (for example `PERMS`) over excluding a path entirely.
