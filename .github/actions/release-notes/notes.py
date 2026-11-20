import argparse
import re
import subprocess
import sys
from pathlib import Path

PREFIX = re.compile(
    r"^(?:feat|fix|chore|docs|ci|build|refactor|perf|test|tests|style|new|release)(?:\([^)]*\))?!?:\s*", re.I)
PR_LINK = re.compile(r"\s+by @\S+ in https?://\S+$")
TRAILING_REFS = re.compile(r"(?:\s*\((?:#\d+|[0-9a-f]{7,40})\))+\s*$")
TRAILERS = re.compile(r"^(?:Co-Authored-By|Signed-off-by|Reviewed-by|Change-Id):", re.I)
VERSION_ONLY = re.compile(r"^(?:(?:release|bump version|version bump|bump)(?: to)?\s+)?v?\d+(?:\.\d+)+\S*$", re.I)
NOISE = re.compile(
    r"\[skip ci\]|^New Feed$|^sync$|^Merge (?:pull request|branch|remote-tracking branch)\b"
    r"|^(?:Chore: )?(?:Refresh webmention cache|Add New Daily Rundown Post|lint auto-fix|Record outgoing mentions)",
    re.I,
)
SEPARATOR = "\x1e"
FIELD = "\x1f"


def clean_subject(subject):
    text = PR_LINK.sub("", subject.strip()).rstrip(".")
    text = TRAILING_REFS.sub("", text)
    text = PREFIX.sub("", text).strip()
    text = text.rstrip(".").strip()
    return text[:1].upper() + text[1:] if text else ""


def body_text(body):
    lines = [line for line in body.splitlines() if not TRAILERS.match(line.strip())]
    paragraphs = [" ".join(p.split()) for p in "\n".join(lines).split("\n\n") if p.strip()]
    return paragraphs[0].rstrip(".") if paragraphs else ""


def changes(commits, skip=""):
    extra = re.compile(skip, re.I) if skip else None
    items = []
    for commit in commits:
        subject = commit["subject"].strip()
        if not subject or NOISE.search(subject) or (extra and extra.search(subject)):
            continue
        text = clean_subject(subject)
        if not text or VERSION_ONLY.match(text):
            text = body_text(commit.get("body", ""))
        if text and text not in items:
            items.append(text)
    return items


def read_commits(previous, cwd=None):
    has_previous = previous and subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{previous}^{{commit}}"],
        cwd=cwd, capture_output=True).returncode == 0
    revision = f"{previous}..HEAD" if has_previous else "HEAD"
    log = subprocess.run(
        ["git", "log", revision, "--no-merges", f"--pretty=format:%s{FIELD}%b{SEPARATOR}"],
        cwd=cwd, capture_output=True, text=True, check=True).stdout
    commits = []
    for record in log.split(SEPARATOR):
        if FIELD in record:
            subject, body = record.split(FIELD, 1)
            commits.append({"subject": subject.strip(), "body": body.strip()})
    return commits


def build(description, items):
    parts = []
    if description.strip():
        parts.append(f"## About\n\n{description.strip()}\n")
    lines = "\n".join(f"* {i}" for i in items) if items else "* Maintenance release"
    parts.append(f"## What's Changed\n\n{lines}\n")
    return "\n".join(parts)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Write release notes: About, then a cleaned list of changes.")
    parser.add_argument("--previous", default="", help="the previous release tag (all history if empty or missing)")
    parser.add_argument("--description", default="", help="text for the About section")
    parser.add_argument("--skip", default="", help="a regular expression: commit subjects that match are left out")
    parser.add_argument("--output", required=True, help="where to write the Markdown")
    args = parser.parse_args(argv)
    Path(args.output).write_text(build(args.description, changes(read_commits(args.previous), args.skip)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
