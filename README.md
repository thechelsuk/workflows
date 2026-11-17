# workflows

thechelsuk's shared, reusable GitHub Actions workflows and community files.
Each repo calls a workflow from a short file of its own, so a fix here reaches
every site at once.

## Link checker

`.github/workflows/link-checker.yml` builds a site (Jekyll, or plain HTML as it
is), checks its links with [lychee](https://github.com/lycheeverse/lychee), and
keeps one open `broken-links` issue assigned to thechelsuk: opened or updated
when links are broken, closed once a run finds none. It serves the built site
the way GitHub Pages does (`/page` from `page.html` or `page.xml`), so it
reports only links that are broken on the live site.

```yaml
name: Link Checker

on:
  workflow_dispatch:
  schedule:
    - cron: "0 6 * * 1"

permissions:
  contents: read
  issues: write

jobs:
  links:
    uses: thechelsuk/workflows/.github/workflows/link-checker.yml@main
    with:
      site_host: example\.thechels\.uk
```

| Input | Default | What it does |
|---|---|---|
| `site_host` | (required) | The site's own host, dots escaped; links to it are checked as local files. |
| `build` | `jekyll` | `jekyll` builds the site; `none` checks the HTML in `site_dir` as it is. |
| `site_dir` | `_site` | Where the built HTML is (`.` for a plain HTML site). |
| `ruby_version` | `3.3` | For Jekyll; `.ruby-version` reads the repo's own file. |
| `jekyll_args` | | Extra `jekyll build` arguments, such as a production config. |
| `post_build` | | A command the site's deploy runs after the build. |
| `internal_only` | `false` | Check internal links and anchors only. |
| `extra_args` | | Extra lychee arguments, such as `--exclude` for hosts that block bots. |
| `assignee` | `thechelsuk` | Who the issue is assigned to. |

## Release

`.github/workflows/release.yml` tags a semver release (no `v` prefix) and
writes its notes when the first line of a commit pushed to `main` starts with
`release:` (minor), `release(minor):`, `release(patch):` or `release(major):`.
Other commits are ignored. The commit message is only read from an environment
variable, never pasted into the script, so a crafted message can't run
commands.

```yaml
name: Release

on:
  push:
    branches: [main]

permissions:
  contents: write

jobs:
  release:
    uses: thechelsuk/workflows/.github/workflows/release.yml@main
```

## Dependency review

`.github/workflows/dependency-review.yml` flags dependencies a pull request
adds or changes that have known vulnerabilities. Free on public repos.

```yaml
name: Dependency Review

on:
  pull_request:

permissions:
  contents: read

jobs:
  dependency-review:
    uses: thechelsuk/workflows/.github/workflows/dependency-review.yml@main
```

## New issue

`.github/workflows/new-issue.yml` triages each new issue: it adds a `triage`
label and, when the issue has no type label, guesses one (`bug`,
`enhancement` or `question`) from its wording, assigns it to thechelsuk, and
thanks the author, saying an Action triaged and tagged it and it awaits human review, unless they're a bot or the assignee. Labels
it needs are created if the repo doesn't have them.

```yaml
name: New Issue

on:
  issues:
    types: [opened]

permissions:
  issues: write

jobs:
  triage:
    uses: thechelsuk/workflows/.github/workflows/new-issue.yml@main
```

| Input | Default | What it does |
|---|---|---|
| `assignee` | `thechelsuk` | Who new issues are assigned to (never thanked). |
| `message` | a short thank-you | The comment; `{author}` becomes the author's @handle, `{labels}` the labels added. |
