"""Reading the list of people an admin pastes or uploads for a sitting.

Each line is one person: a name and an email, in either order, separated by a comma, a semicolon
or a tab, or written `Name <email>`. A first line that only names the columns is skipped. Nothing
is stored here; admin.generate_invites does that once the list has no problems, so a list with one
bad line creates nothing at all.
"""

import csv
import re
from dataclasses import dataclass

EMAIL = re.compile(r"^[^@\s,;<>()\"]+@[^@\s,;<>()\"]+\.[^@\s,;<>()\"]{2,}$")
BRACKETED = re.compile(r"^(?P<name>.*?)<(?P<email>[^<>]*)>\s*$")
NAME_MAX = 200
EMAIL_MAX = 254


@dataclass(frozen=True)
class Person:
    line: int  # 1-based line of the pasted text, so a problem can be pointed at
    name: str
    email: str  # lower case


@dataclass(frozen=True)
class Problem:
    line: int
    reason: str  # bad_email | name_missing | name_too_long | repeated | already_invited
    text: str  # the line as typed, for the admin who typed it


def _split(line: str) -> tuple[str, str]:
    """(name, email-ish) from one line. The email-ish part may be empty or not an email."""
    bracketed = BRACKETED.match(line)
    if bracketed:
        return bracketed["name"], bracketed["email"]
    delimiter = next((d for d in ("\t", ",", ";") if d in line), ",")
    # csv reads quotes, so "Hamilton, Margaret" stays one field
    fields = [f.strip() for f in next(csv.reader([line], delimiter=delimiter))]
    fields = [f for f in fields if f]
    email = next((f for f in fields if "@" in f), "")
    name = " ".join(f for f in fields if f != email)
    return name, email


def parse(
    raw: str, already_invited: frozenset[str] = frozenset()
) -> tuple[list[Person], list[Problem]]:
    """The people on the list, and everything wrong with it. `already_invited` is the lower-case
    emails this sitting has a candidate for."""
    people: list[Person] = []
    problems: list[Problem] = []
    seen: set[str] = set()
    first = True
    for number, text in enumerate(raw.splitlines(), start=1):
        line = text.strip().strip("﻿")
        if not line:
            continue
        if first:
            first = False
            if "@" not in line and "email" in line.lower():  # a header row
                continue
        name, email = _split(line)
        name = " ".join(name.split())
        email = email.strip().lower()
        if not EMAIL.match(email) or len(email) > EMAIL_MAX:
            problems.append(Problem(number, "bad_email", line))
        elif not name:
            problems.append(Problem(number, "name_missing", line))
        elif len(name) > NAME_MAX:
            problems.append(Problem(number, "name_too_long", line))
        elif email in seen:
            problems.append(Problem(number, "repeated", line))
        elif email in already_invited:
            problems.append(Problem(number, "already_invited", line))
        else:
            seen.add(email)
            people.append(Person(number, name, email))
    return people, problems
