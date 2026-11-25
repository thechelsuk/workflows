# workflows

thechelsuk's shared, reusable GitHub Actions workflows. Default issue forms and
community files are in [thechelsuk/.github](https://github.com/thechelsuk/.github).
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

`.github/workflows/release.yml` tags a semver release with a `v` prefix (`v1.2.3`, like the App Store releases) and
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

Its notes come from the release notes action below. To leave a repo's own
automated commits out of them, pass a regular expression as `skip`:

```yaml
jobs:
  release:
    uses: thechelsuk/workflows/.github/workflows/release.yml@main
    with:
      skip: "^Update data "
```

## Release notes

`.github/actions/release-notes` writes release notes in the thechels.uk style:
an **About** section with the repository's description, then **What's
Changed**, a bullet list of the changes since the previous release.

It cleans each commit subject: conventional commit prefixes (`feat:`,
`build(deps):` and so on), pull request and Dependabot links, `(#12)` and
commit hash references, and trailing full stops are removed, and the first
letter is capitalised. Dependabot's bump text is kept ("Bump jest from 30.5.1
to 30.5.2"). Merges, duplicates, `[skip ci]` commits and automated commits
(New Feed, webmention cache refreshes, daily rundowns, lint auto-fixes, outgoing
mentions) are left out. A commit whose subject is only a version number, such as
`chore: Release 1.2.4`, uses the first paragraph of its message instead, without
`Co-Authored-By` or `Signed-off-by` lines.

The release workflow above uses it. Repos that release from `package.json`
call it in their own workflow, after checking out with `fetch-depth: 0`:

```yaml
- name: Build release notes
  id: notes
  uses: thechelsuk/workflows/.github/actions/release-notes@main
  with:
    previous: ${{ steps.previous.outputs.tag }}
    description: ${{ steps.pkg.outputs.description }}

- uses: softprops/action-gh-release@v3
  with:
    body_path: ${{ steps.notes.outputs.notes_file }}
```

| Input | Default | What it does |
|---|---|---|
| `previous` | (all history) | The previous release tag. |
| `description` | The repo's GitHub description | Text for the About section. |
| `skip` | (none) | A regular expression: commit subjects that match are left out. |

Run its tests with `pytest tests`.

## Chrome Web Store

`.github/actions/chrome-web-store` uploads an extension's zip to the Chrome
Web Store with the API v2, then publishes it. It signs in with a Google Cloud
service account's JSON key (a signed JWT exchanged for an access token), waits
while the store is still processing the upload, and fails with the store's
own message if the upload or publish reports an error. Publish warnings show
as warnings on the run. The API only updates items that exist, so an
extension's first version is submitted by hand in the Developer Dashboard.

Call it after the step that builds the zip, and skip it until the repo has an
item ID:

```yaml
- name: Publish to the Chrome Web Store
  if: vars.CWS_ITEM_ID != ''
  uses: thechelsuk/workflows/.github/actions/chrome-web-store@main
  with:
    publisher_id: ${{ vars.CWS_PUBLISHER_ID }}
    item_id: ${{ vars.CWS_ITEM_ID }}
    zip: distribution.zip
    service_account_key: ${{ secrets.CWS_SERVICE_ACCOUNT_KEY }}
```

| Input | Default | What it does |
|---|---|---|
| `publisher_id` | (required) | The publisher ID. |
| `item_id` | (required) | The item ID, the same as the extension ID. |
| `zip` | `distribution.zip` | The zip to upload. |
| `publish_type` | `default` | `default` publishes once the review passes; `staged` waits for you to publish it from the dashboard. |
| `service_account_key` | (required) | The service account's JSON key, from a secret. |

The store rejects a version it already has, so run it only when the
manifest's version is new.

### Set-up

Once per publisher:

1. In the [Google Cloud console](https://console.cloud.google.com/), pick or
   create a project, search for "Chrome Web Store API" and enable it.
2. In IAM & Admin > Service Accounts, create a service account. It needs no
   roles or permissions.
3. In the [Developer Dashboard](https://chrome.google.com/webstore/devconsole),
   open Account and add the service account's email. A publisher can have one
   service account.
4. Back on the service account, open Keys > Add key > Create new key > JSON,
   and keep the downloaded file safe. It's a password: never commit it.
5. Note the publisher ID from the Developer Dashboard's Publisher > Settings.

In each extension repo, under Settings > Secrets and variables > Actions:

- Secret `CWS_SERVICE_ACCOUNT_KEY`: the whole JSON key file.
- Variable `CWS_PUBLISHER_ID`: the publisher ID.
- Variable `CWS_ITEM_ID`: the item ID, from the item's Package tab in the
  Developer Dashboard. Leave it unset until the first version is in the store;
  the store step is skipped until then.

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
label and a type. Issues from the default forms in
[thechelsuk/.github](https://github.com/thechelsuk/.github) are known by their
headings (`bug`, `enhancement`, `question` or `feedback`), and their "Which
part?" answer adds `app` or `website`. Other issues with no labels get a guess
from their wording; an issue that already has a label (from a repo's own form,
such as `correction`) keeps it and gets no guess. It assigns the issue to thechelsuk and thanks the author,
saying an Action triaged and tagged it and it awaits human review (plus a line
when they've ticked the sponsored Feature request bump), unless they're a bot
or the assignee. Labels it needs are created if the repo doesn't have them.

A second step adds a `sponsor` label when the author is a public sponsor of thechelsuk (private sponsors aren't
visible to the check). It uses the workflow's own token, so no secret is needed, skips bots and the sponsored account
itself, creates the label if missing, and never fails the job: if the GitHub query errors, it logs a warning and
carries on. Callers that trigger only on `issues: opened`, as all of Mat's do, label issues; pull requests aren't
covered.

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
| `sponsorable` | `thechelsuk` | The user or organisation whose public sponsors get the sponsor label. |
| `sponsor_label` | `sponsor` | The label added to a sponsor's issue. |

## Pages

`.github/workflows/pages.yml` builds a site and deploys it to GitHub Pages. It
builds on every push and pull request, so a pull request shows whether the
site still builds, and deploys only from `main` (never from a template repo),
one deploy at a time without cancelling one that's running.

- `build: static` publishes the repo as it is, without `.github`, dotfiles
  (`.well-known` is kept) and repo housekeeping files (README, LICENSE,
  CONTRIBUTING, CHANGELOG, package and Gemfile files). No list of files to keep
  up to date: a new file is published as soon as it's committed.
- `build: jekyll` builds with the repo's `.ruby-version`, `JEKYLL_ENV=production`
  and Pages' base path.
- Either way, a repo with a `package.json` gets `npm ci` first, then
  `pre_build` runs if it's set.

Requires Settings → Pages → Source: "GitHub Actions".

```yaml
name: Pages

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

jobs:
  pages:
    uses: thechelsuk/workflows/.github/workflows/pages.yml@main
    with:
      build: static
```

| Input | Default | What it does |
|---|---|---|
| `build` | `static` | `static` publishes the repo's files; `jekyll` builds the site. |
| `pre_build` | | A command run before the build, such as `npm run vendor && npm test`. |
| `exclude` | | Extra paths to leave out of a static site, space-separated. |
| `node_version` | `24` | Node.js version, when the repo has a `package.json`. |
| `fetch_depth` | `1` | Commits of history to check out; `0` for all, for "last updated" dates from git. |
