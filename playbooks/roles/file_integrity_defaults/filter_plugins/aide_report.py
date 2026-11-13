# -*- coding: utf-8 -*-
# MIT License (see LICENSE in the repository root)
"""Filters for the file_integrity Check / Rebaseline report:

* aide_change_details  - parse AIDE's "Detailed information about changes"
                         section (report_level=changed_attributes)
* aide_package_checks  - rpm ownership / `rpm -V` verdicts per path
* aide_package_summary - one-line count of those verdicts
* aide_content_diffs   - unified diffs against baseline content snapshots
* aide_report_lines    - readable per-path lines for the job output

Loaded automatically because every playbook uses the file_integrity_defaults
role. Supports the AIDE 0.16 and 0.19 report layouts, for example (0.19):

    ---------------------------------------------------
    Detailed information about changes:
    ---------------------------------------------------

    File: /etc/hosts
     Perm      : -rw-r--r--                       | -rw-rw-rw-
     SHA512    : IGtQPh5xQpisR8jUufBeWmebQBZd7nxZ | Uo+VC5nvqkrSrGOoyiCEhFYGZnoXy8is
                 NGE31OXynOfGeh1wbmn9s4LKDaiSFmrF | LJpjP1YcHiegDL7XwSGGh06eWNz6Z5pd
                 ndAVjBem3VKnJQyLT9C1kQ==         | xILkavi7mzcurZkaoJcfjw==
"""

from __future__ import absolute_import, division, print_function

import base64
import datetime
import difflib
import hashlib
import re

__metaclass__ = type

_SECTION_TITLE = "Detailed information about changes:"
_RULE_RE = re.compile(r"^-{5,}\s*$")
# "File: /etc/hosts", "Directory: /etc/cron.d", "Link: /etc/localtime", ...
_ENTRY_RE = re.compile(r"^([A-Za-z][A-Za-z ]*):\s+(/.*?)\s*$")
# Attribute lines are indented 1-4 spaces; continuation lines are indented
# further (aligned with the value column).
_ATTR_RE = re.compile(r"^ {1,4}(\S[^:]*?)\s*:\s?(.*)$")
_CONT_RE = re.compile(r"^ {5,}(\S.*)$")
_SPLIT_RE = re.compile(r"(?:^|\s)\|(?:\s|$)")
# AIDE prints each side of a change in a 32-character column and wraps longer
# values onto continuation lines.
_COLUMN_WIDTH = 32
# Long hash values wrap across lines and must be re-joined without a separator.
_HASH_RE = re.compile(r"^(MD5|SHA|RMD|TIGER|CRC|HAVAL|GOST|WHIRLPOOL|STRIBOG)", re.IGNORECASE)


def _split(value):
    parts = _SPLIT_RE.split(value, maxsplit=1)
    if len(parts) == 1:
        parts.append("")
    return parts[0].strip(), parts[1].strip()


def aide_change_details(output):
    """Return {path: [{attribute, old, new}, ...]} for every changed entry."""
    details = {}
    if not output:
        return details
    lines = str(output).splitlines()
    try:
        start = [line.strip() for line in lines].index(_SECTION_TITLE) + 1
    except ValueError:
        return details

    path = None
    current = None
    seen_rule = False
    for line in lines[start:]:
        if _RULE_RE.match(line):
            if seen_rule:
                break  # start of the next section
            seen_rule = True  # the rule directly under the section title
            continue
        if not line.strip():
            current = None
            continue
        entry = _ENTRY_RE.match(line)
        if entry:
            path = entry.group(2)
            details[path] = []
            current = None
            continue
        if path is None:
            continue
        if _CONT_RE.match(line) and current is not None:
            # Split the whole line: the old side may be empty ("      | value").
            for side, chunk in zip(("old", "new"), _split(line)):
                if chunk:
                    _append(current, side, chunk)
            continue
        attr = _ATTR_RE.match(line)
        if attr:
            old, new = _split(attr.group(2))
            current = {"attribute": attr.group(1).strip(), "old": old, "new": new}
            current["_wrapped"] = {"old": len(old) >= _COLUMN_WIDTH, "new": len(new) >= _COLUMN_WIDTH}
            details[path].append(current)
    for changes in details.values():
        for change in changes:
            change.pop("_wrapped", None)
    return details


def _append(change, side, chunk):
    """Add a continuation chunk to one side of an attribute change.

    AIDE wraps any value longer than the column width onto the next line, so
    a chunk that follows a full-width chunk (or any hash chunk) continues the
    same value. Otherwise it is another entry of a multi-line value (ACL,
    xattrs) and is joined with ", ".
    """
    wrapped = change["_wrapped"][side] or _HASH_RE.match(change["attribute"])
    if not change[side]:
        change[side] = chunk
    else:
        change[side] += ("" if wrapped else ", ") + chunk
    change["_wrapped"][side] = len(chunk) >= _COLUMN_WIDTH


def _short(value, width):
    value = value if value else "(none)"
    if width and len(value) > width:
        return value[:width] + "..."
    return value


# ----- Package verification ------------------------------------------------

# rpm -V flags that mean a real difference (T = mtime only is ignored).
_RPM_DIFF_FLAGS = set("SM5DLUGP")
_RPM_VERIFY_RE = re.compile(r"^(missing|[.?SM5DLUGTP]{8,9})\s+(?:([cdglra])\s+)?(/.*)$")


# rpm header bits: FILEVERIFYFLAGS digest check, FILEFLAGS %config.
_RPMVERIFY_DIGEST = 1
_RPMFILE_CONFIG = 1


def _flag(parts, index, bit, default):
    try:
        return bool(int(parts[index]) & bit)
    except (IndexError, ValueError):
        return default


def _iso(epoch):
    try:
        moment = datetime.datetime(1970, 1, 1) + datetime.timedelta(seconds=int(epoch))
        return moment.strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return ""


def _epoch(iso):
    try:
        moment = datetime.datetime.strptime(str(iso), "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None
    return (moment - datetime.datetime(1970, 1, 1)).total_seconds()


def aide_package_checks(raw, baseline_timestamp=""):
    """Turn the output of tasks/report_enrich.yml's rpm script into verdicts.

    Input lines (tab separated):
      O <path> <name-version-release.arch> <install epoch> [<verifyflags> <fileflags>]
                                  owned by a package (flags: rpm FILEVERIFYFLAGS
                                  and FILEFLAGS of that file in that package)
      N <path>                    not owned
      V <rpm -V output line>      a file that differs
    Returns {path: {verdict, packages: [{package, installed, after_baseline}],
    rpm_verify_flags, config_file}}. Verdicts:
      matches-package  file is exactly what the package shipped
      config-modified  rpm config file (%config) differs from the package
      differs          NON-config file differs from the package (suspicious)
      unverified       rpm does not verify this file's contents (%verify
                       excludes the digest, e.g. /etc/passwd), so the package
                       can neither explain nor clear a content change
      missing          package expects the file but it is gone
      not-owned        no package owns the path
    """
    base = _epoch(baseline_timestamp)
    owners = {}
    order = []
    verify = {}
    for line in str(raw or "").splitlines():
        parts = line.split("\t")
        kind = parts[0]
        if kind in ("O", "N") and len(parts) >= 2:
            path = parts[1]
            if path not in owners:
                owners[path] = []
                order.append(path)
            if kind == "O" and len(parts) >= 4:
                installed = _iso(parts[3])
                owners[path].append(
                    {
                        "package": parts[2],
                        "installed": installed,
                        "after_baseline": bool(base is not None and installed and _epoch(installed) > base),
                        "digest_verified": _flag(parts, 4, _RPMVERIFY_DIGEST, True),
                        "config_file": _flag(parts, 5, _RPMFILE_CONFIG, False),
                    }
                )
        elif kind == "V" and len(parts) >= 2:
            match = _RPM_VERIFY_RE.match("\t".join(parts[1:]).strip())
            if match:
                verify[match.group(3)] = (match.group(1), match.group(2) == "c")

    checks = {}
    for path in order:
        flags, is_config = verify.get(path, ("", False))
        is_config = is_config or any(o["config_file"] for o in owners[path])
        if not owners[path]:
            verdict = "not-owned"
        elif flags == "missing":
            verdict = "missing"
        elif set(flags) & _RPM_DIFF_FLAGS:
            verdict = "config-modified" if is_config else "differs"
        elif not all(o["digest_verified"] for o in owners[path]):
            verdict = "unverified"
        else:
            verdict = "matches-package"
        checks[path] = {
            "verdict": verdict,
            "packages": owners[path],
            "rpm_verify_flags": flags,
            "config_file": is_config,
        }
    return checks


_VERDICT_TEXT = {
    "matches-package": "file matches the package",
    "config-modified": "config file modified locally (differs from the package default)",
    "differs": "DIFFERS FROM THE PACKAGE - not explained by a package update",
    "unverified": "rpm does not verify this file's contents (%verify), so it cannot explain the change",
    "missing": "package file is missing",
    "not-owned": "not owned by any package",
}


def aide_package_summary(checks):
    """One-line count of verdicts, e.g. 'matches-package 22, not-owned 3'."""
    counts = {}
    for check in (checks or {}).values():
        counts[check["verdict"]] = counts.get(check["verdict"], 0) + 1
    order = ["differs", "missing", "unverified", "config-modified", "matches-package", "not-owned"]
    return ", ".join("%s %d" % (key, counts[key]) for key in order if key in counts)


# ----- Content diffs ---------------------------------------------------------


def _decode(b64):
    data = base64.b64decode(b64 or "")
    if b"\0" in data:
        return None, data
    try:
        return data.decode("utf-8"), data
    except UnicodeDecodeError:
        return None, data


def aide_content_diffs(old_results, new_results, expected_sha256, max_lines=100):
    """Build unified diffs between baseline snapshots and current files.

    old_results / new_results are the `results` of looped slurp tasks
    (item = path). expected_sha256 is metadata.yml's `snapshots` mapping; a
    snapshot whose content does not match it is reported, never diffed.
    Returns {path: [diff lines]}.
    """
    expected_sha256 = expected_sha256 or {}
    new_by_path = dict((r.get("item"), r) for r in (new_results or []))
    diffs = {}
    for old in old_results or []:
        path = old.get("item")
        new = new_by_path.get(path, {})
        if old.get("skipped"):
            continue
        if old.get("failed") or "content" not in old:
            diffs[path] = ["(baseline snapshot could not be read)"]
            continue
        old_text, old_bytes = _decode(old["content"])
        if hashlib.sha256(old_bytes).hexdigest() != expected_sha256.get(path):
            diffs[path] = ["(baseline snapshot does not match metadata.yml; not trusted, no diff shown)"]
            continue
        if new.get("skipped"):
            diffs[path] = [new.get("_aide_reason") or "(current file is larger than aide_content_snapshot_max_bytes; no diff shown)"]
            continue
        if new.get("failed") or "content" not in new:
            diffs[path] = ["(current file could not be read)"]
            continue
        new_text, new_bytes = _decode(new["content"])
        if old_text is None or new_text is None:
            diffs[path] = ["(binary content; no diff shown)"]
            continue
        if old_bytes == new_bytes:
            diffs[path] = ["(content identical to the snapshot; only metadata changed)"]
            continue
        lines = list(
            difflib.unified_diff(
                old_text.splitlines(),
                new_text.splitlines(),
                fromfile="baseline:" + path,
                tofile="current:" + path,
                lineterm="",
                n=2,
            )
        )
        limit = int(max_lines)
        if limit and len(lines) > limit:
            lines = lines[:limit] + ["... diff truncated: showing %d of %d lines" % (limit, len(lines))]
        diffs[path] = lines
    return diffs


# ----- Report display -------------------------------------------------------


def _short(value, width):
    value = value if value else "(none)"
    if width and len(value) > width:
        return value[:width] + "..."
    return value


def _package_line(check):
    if not check:
        return None
    if check["packages"]:
        pkg = check["packages"][0]
        when = ""
        if pkg.get("installed"):
            when = " (installed %s%s)" % (pkg["installed"], ", after the baseline" if pkg.get("after_baseline") else "")
        more = " +%d more" % (len(check["packages"]) - 1) if len(check["packages"]) > 1 else ""
        flags = " [rpm -V: %s]" % check["rpm_verify_flags"] if check["verdict"] in ("differs", "config-modified") else ""
        return "Package : %s%s%s - %s%s" % (pkg["package"], more, when, _VERDICT_TEXT[check["verdict"]], flags)
    return "Package : none - " + _VERDICT_TEXT["not-owned"]


def aide_report_lines(report, hash_width=16, indent=13):
    """Return the per-path lines of a host report.

    Each added/removed/changed path is followed (indented) by its package
    verdict, its attribute changes (old -> new) and its content diff, when
    those are available in the report.
    """
    pad = " " * int(indent)
    details = report.get("changed_details") or {}
    packages = report.get("package_checks") or {}
    diffs = report.get("content_diffs") or {}
    lines = []
    for kind in ("added", "removed", "changed"):
        for path in report.get(kind + "_paths") or []:
            lines.append("  %-8s %s" % (kind, path))
            package = _package_line(packages.get(path))
            if package:
                lines.append(pad + package)
            changes = details.get(path, []) if kind == "changed" else []
            width = max([len(c["attribute"]) for c in changes] + [0])
            for change in changes:
                limit = int(hash_width) if _HASH_RE.match(change["attribute"]) else 0
                lines.append(
                    "%s%s : %s -> %s"
                    % (pad, change["attribute"].ljust(width), _short(change["old"], limit), _short(change["new"], limit))
                )
            if path in diffs:
                lines.append(pad + "Diff (baseline snapshot -> current):")
                lines.extend(pad + "  " + line for line in diffs[path])
    return lines


class FilterModule(object):
    """AIDE report filters."""

    def filters(self):
        return {
            "aide_change_details": aide_change_details,
            "aide_package_checks": aide_package_checks,
            "aide_package_summary": aide_package_summary,
            "aide_content_diffs": aide_content_diffs,
            "aide_report_lines": aide_report_lines,
        }
