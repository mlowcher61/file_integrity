# -*- coding: utf-8 -*-
# MIT License (see LICENSE in the repository root)
"""Filters that turn the "Detailed information about changes" section of an
AIDE report (`aide --check` / `aide --update` with
report_level=changed_attributes) into structured data and readable lines.

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


def aide_change_lines(paths, details, indent=13, hash_width=16):
    """Return display lines: each changed path followed by its attribute changes.

    Hash values are shortened to hash_width characters (0 = full value);
    the full values stay in the structured details.
    """
    details = details or {}
    pad = " " * int(indent)
    lines = []
    for path in paths or []:
        changes = details.get(path, [])
        lines.append("  changed  " + path)
        width = max([len(c["attribute"]) for c in changes] + [0])
        for change in changes:
            limit = int(hash_width) if _HASH_RE.match(change["attribute"]) else 0
            lines.append(
                "%s%s : %s -> %s"
                % (pad, change["attribute"].ljust(width), _short(change["old"], limit), _short(change["new"], limit))
            )
    return lines


class FilterModule(object):
    """AIDE report filters."""

    def filters(self):
        return {
            "aide_change_details": aide_change_details,
            "aide_change_lines": aide_change_lines,
        }
