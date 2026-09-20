"""Refuse to print node output that does not look like numbers and status words.

The repository is public and the vault is not. The scripts on the node are
written to print counts, SHAs, status words and image tags, and the gate and
the smoke test check their own summaries with private_keys_found before
printing them. This is the second reading, on the way out: send_command.py
runs it over everything a script printed, and prints nothing at all when a
line trips it. A workflow log cannot be un-published, so the check has to
come before the print, not after it.

It is deliberately narrow, because a false positive hides the output of a
deploy that may itself be failing. A line is refused when it is not plain
ASCII, when it names a note file, when it is far longer than anything these
scripts print, or when it is a JSON object carrying a string value: the two
summaries are numbers, so a string in one means something else got in.
"""
import json
import string

# Note paths end here. Nothing the pipeline prints legitimately does.
NOTE_SUFFIX = ".md"
# kubectl's widest line here is a three-column pod table, about 110 characters.
MAX_LINE = 300
PRINTABLE = set(string.printable) - set("\x0b\x0c")


def suspicious(line):
    """Why this line may not be printed, or None when it may."""
    if not set(line) <= PRINTABLE:
        return "not plain ASCII"
    if NOTE_SUFFIX in line.lower():
        return f"names a {NOTE_SUFFIX} file"
    if len(line) > MAX_LINE:
        return f"longer than {MAX_LINE} characters"
    stripped = line.strip()
    if stripped.startswith("{"):
        try:
            value = json.loads(stripped)
        except ValueError:
            return "an unparseable JSON line"
        if isinstance(value, dict):
            strings = sorted(k for k, v in value.items() if isinstance(v, str))
            if strings:
                return f"a JSON value that is not a number: {', '.join(strings)}"
    return None


def offenders(text):
    """[(line number, reason)] for every line that may not be printed."""
    return [(number, reason)
            for number, line in enumerate(text.splitlines(), start=1)
            for reason in [suspicious(line)] if reason]


def refusal(found):
    """What to print instead of the output: where it tripped, not what it said."""
    lines = [f"REFUSING to print {len(found)} line(s) of node output:"]
    lines += [f"  line {number}: {reason}" for number, reason in found]
    lines.append("The output is in the command's SSM invocation, which is not public.")
    return "\n".join(lines)
