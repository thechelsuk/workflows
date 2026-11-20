import importlib.util
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("notes", ROOT / ".github" / "actions" / "release-notes" / "notes.py")
notes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notes)


def c(subject, body=""):
    return {"subject": subject, "body": body}


def test_strips_conventional_prefixes_and_capitalises():
    assert notes.clean_subject("feat: add OPML of all feeds") == "Add OPML of all feeds"
    assert notes.clean_subject("fix(feeds): correct Dark Reading URL") == "Correct Dark Reading URL"
    assert notes.clean_subject("feat!: drop Python 3.10") == "Drop Python 3.10"
    assert notes.clean_subject("Chore(deps): bump actions/configure-pages from 5 to 6") == "Bump actions/configure-pages from 5 to 6"


def test_keeps_dependabot_bump_text_without_links():
    assert notes.clean_subject(
        "Bump jest from 30.4.2 to 30.5.0 by @dependabot[bot] in https://github.com/thechelsuk/ext-chrome-hiyd/pull/6"
    ) == "Bump jest from 30.4.2 to 30.5.0"
    assert notes.clean_subject(
        "build(deps): update requests requirement from >=2.33.0 to >=2.33.1 (#587)"
    ) == "Update requests requirement from >=2.33.0 to >=2.33.1"


def test_strips_hashes_pr_refs_and_trailing_full_stops():
    assert notes.clean_subject("fix: feed titles (2d2e1586)") == "Feed titles"
    assert notes.clean_subject("Add Activity Plan page (#12).") == "Add Activity Plan page"


def test_release_keyword_commits_keep_their_description():
    assert notes.clean_subject("release(major): Bump major version after large refactor") == \
        "Bump major version after large refactor"
    assert notes.clean_subject("release: First release of the template") == "First release of the template"


def test_skips_noise():
    commits = [
        c("New Feed"),
        c("Chore: Refresh webmention cache [skip ci] 2026-11-20 20:38"),
        c("Chore: Add New Daily Rundown Post 2026-04-22T08:47:52Z"),
        c("Chore: lint auto-fix [skip ci] 2026-11-20 22:11"),
        c("Merge pull request #2 from SecOpsNews/dependabot/github_actions/actions/checkout-7"),
        c("Merge branch 'main' of github.com:thechelsuk/x"),
        c("sync"),
        c("Record outgoing mentions 2026-11-18T11:25"),
        c("feat: real change"),
    ]
    assert notes.changes(commits) == ["Real change"]


def test_version_only_subject_uses_the_body_instead():
    body = ("Safer link clicking: data: and vbscript: links are now blocked\n"
            "from navigating, as javascript: links already were. The manifest\n"
            "version now matches the package version.\n\n"
            "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\n"
            "Signed-off-by: thechelsuk <x@example.com>")
    assert notes.changes([c("chore: Release 1.2.4", body)]) == [
        "Safer link clicking: data: and vbscript: links are now blocked from navigating, as javascript: "
        "links already were. The manifest version now matches the package version"
    ]


def test_version_only_subject_without_body_is_dropped():
    assert notes.changes([c("Bump version to 2.0.1"), c("chore: release v1.0.0"), c("1.2.3")]) == []


def test_drops_duplicates_and_keeps_order():
    commits = [c("feat: tidy up main feed"), c("fix: linting"), c("feat: tidy up main feed")]
    assert notes.changes(commits) == ["Tidy up main feed", "Linting"]


def test_build_body():
    body = notes.build("A tool that does things.", ["Add a thing", "Bump jest from 1 to 2"])
    assert body == ("## About\n\nA tool that does things.\n\n## What's Changed\n\n"
                    "* Add a thing\n* Bump jest from 1 to 2\n")


def test_build_body_without_description_or_changes():
    assert notes.build("", []) == "## What's Changed\n\n* Maintenance release\n"


def test_reads_git_history(tmp_path):
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    git("commit", "-q", "--allow-empty", "-m", "feat: first")
    git("tag", "1.0.0")
    git("commit", "-q", "--allow-empty", "-m", "fix: second\n\nCo-Authored-By: Claude <noreply@anthropic.com>")
    git("commit", "-q", "--allow-empty", "-m", "New Feed")
    git("commit", "-q", "--allow-empty", "-m", "release: Third")
    assert notes.changes(notes.read_commits("1.0.0", cwd=tmp_path)) == ["Third", "Second"]
    assert notes.changes(notes.read_commits("", cwd=tmp_path)) == ["Third", "Second", "First"]
    assert notes.changes(notes.read_commits("missing-tag", cwd=tmp_path)) == ["Third", "Second", "First"]


def test_main_writes_file(tmp_path, monkeypatch):
    monkeypatch.setattr(notes, "read_commits", lambda previous, cwd=None: [c("feat: add x")])
    out = tmp_path / "notes.md"
    assert notes.main(["--previous", "1.0.0", "--description", "About text", "--output", str(out)]) == 0
    assert out.read_text() == "## About\n\nAbout text\n\n## What's Changed\n\n* Add x\n"


def test_extra_skip_pattern():
    commits = [c("Update data 2026-11-20"), c("feat: keep me")]
    assert notes.changes(commits, skip=r"^Update data") == ["Keep me"]
