"""Weekly report of activity in the IntelliCenter integration's fork network.

Run by .github/workflows/fork-watch.yaml. It compares the current state of every
fork of jlvaillant/intellicenter (dwradcliffe, joyfulhouse and their forks), the
pull requests, issues and releases of the main repositories, and the pull
requests this repository's owner opened upstream with the state saved by the
previous run, and writes what changed to report.md. The report is published on
the fork-watch branch, where it is reviewed for changes worth taking.

Standard library only. Needs GH_TOKEN; usage: fork_watch.py STATE_JSON OUT_DIR
"""

from datetime import datetime, timezone
import json
import os
import re
import sys
import urllib.error
import urllib.request

API = "https://api.github.com"
ROOT = "jlvaillant/intellicenter"
# repositories whose pull requests, issues and releases are worth following
MAIN_REPOS = ["dwradcliffe/intellicenter", "jlvaillant/intellicenter", "joyfulhouse/intellicenter"]
MAX_COMMITS = 30


def api(path, params=""):
    """Return the JSON for an API path, following pagination."""
    url = f"{API}{path}{'&' if '?' in path else '?'}per_page=100{params}"
    results = None
    while url:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
                "User-Agent": "intellicenter-fork-watch",
            },
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.load(response)
            links = response.headers.get("Link", "")
        if isinstance(data, list):
            results = (results or []) + data
            match = re.search(r'<([^>]+)>;\s*rel="next"', links)
            url = match.group(1) if match else None
        else:
            return data
    return results or []


def try_api(path, params=""):
    try:
        return api(path, params)
    except urllib.error.HTTPError as err:
        return {"error": f"{err.code} {err.reason}"}


def first_line(message):
    """Return the first meaningful line of a message (skipping HTML comments)."""
    for line in message.splitlines():
        line = line.strip().lstrip("#").strip()
        if line and not line.startswith("<!--"):
            return line[:120]
    return ""


def discover_network(own):
    """Return {repo: parent} for the root and every fork below it."""
    network = {ROOT: None}
    queue = [ROOT]
    while queue:
        repo = queue.pop(0)
        for fork in try_api(f"/repos/{repo}/forks") or []:
            if not isinstance(fork, dict):
                continue
            name = fork["full_name"]
            if name in network:
                continue
            network[name] = repo
            if fork.get("forks_count"):
                queue.append(name)
    network.pop(own, None)
    return network


def default_branch(repo, cache={}):
    if repo not in cache:
        info = try_api(f"/repos/{repo}")
        cache[repo] = info.get("default_branch", "main") if isinstance(info, dict) else "main"
    return cache[repo]


def commits_between(repo, base, head):
    """Commits in head that aren't in base, newest last (base/head: refs or owner:repo:branch)."""
    compare = try_api(f"/repos/{repo}/compare/{base}...{head}")
    if not isinstance(compare, dict) or "error" in compare:
        return None
    return [
        {
            "sha": c["sha"][:7],
            "date": c["commit"]["author"]["date"][:10],
            "author": (c.get("author") or {}).get("login") or c["commit"]["author"]["name"],
            "message": first_line(c["commit"]["message"]),
        }
        for c in compare.get("commits", [])
    ][-MAX_COMMITS:]


def main():
    state_path, out_dir = sys.argv[1], sys.argv[2]
    try:
        with open(state_path) as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}
    first_run = not state.get("last_run")
    since = state.get("last_run")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    own = os.environ.get("GITHUB_REPOSITORY", "briansteven/intellicenter")
    owner = own.split("/")[0]

    lines = [f"# Fork watch, {now[:10]}", ""]
    if first_run:
        lines += ["First run: this records the current state; later reports list what changed.", ""]
    else:
        lines += [f"Changes since the previous run ({since}).", ""]

    # --- latest Home Assistant -------------------------------------------------------
    outcome = os.environ.get("LATEST_HA_OUTCOME") or "not run"
    version = os.environ.get("LATEST_HA_VERSION") or "unknown"
    lines += ["## Tests against the latest Home Assistant", ""]
    lines += [f"- Home Assistant {version}: **{outcome}**"]
    summary = (os.environ.get("LATEST_HA_SUMMARY") or "").strip()
    if outcome != "success" and summary:
        lines += ["", "```", summary[-3000:], "```"]
    lines += [""]

    # --- forks --------------------------------------------------------------------------
    network = discover_network(own)
    old_branches = state.get("branches", {})
    new_branches = {}
    fork_lines = []
    for repo in sorted(network):
        branches = try_api(f"/repos/{repo}/branches")
        if not isinstance(branches, list):
            continue
        heads = {b["name"]: b["commit"]["sha"] for b in branches}
        new_branches[repo] = heads
        if first_run:
            continue
        before = old_branches.get(repo)
        parent = network[repo]
        changes = []
        for branch, sha in sorted(heads.items()):
            previous = (before or {}).get(branch)
            if previous == sha:
                continue
            commits = None
            if previous:
                commits = commits_between(repo, previous, sha)  # None if force-pushed
            if commits is None and parent:
                owner_name, repo_name = repo.split("/")
                commits = commits_between(
                    parent, default_branch(parent), f"{owner_name}:{repo_name}:{branch}"
                )
            label = "new branch" if previous is None else "updated"
            if before is None:
                label = "new fork"
            if commits == []:
                continue  # nothing of its own (e.g. a branch synced with its parent)
            changes.append((branch, label, commits or []))
        if changes:
            fork_lines += [f"### [{repo}](https://github.com/{repo}) (fork of {parent or '-'})", ""]
            for branch, label, commits in changes:
                fork_lines += [f"- `{branch}` ({label}), {len(commits)} commit(s) of its own:"]
                fork_lines += [
                    f"  - {c['date']} [`{c['sha']}`](https://github.com/{repo}/commit/{c['sha']})"
                    f" {c['message']} ({c['author']})"
                    for c in commits
                ]
            fork_lines += [""]
    lines += ["## Forks with new commits", ""]
    if first_run:
        lines += [f"{len(new_branches)} repositories recorded.", ""]
    else:
        lines += fork_lines or ["None.", ""]

    # --- pull requests, issues, releases ---------------------------------------------
    pr_lines, our_lines, issue_lines, release_lines = [], [], [], []
    for repo in MAIN_REPOS:
        pulls = try_api(f"/repos/{repo}/pulls", "&state=all&sort=updated&direction=desc")
        for pr in pulls if isinstance(pulls, list) else []:
            if since and pr["updated_at"] <= since:
                continue
            if first_run and pr["state"] != "open":
                continue
            state_label = "merged" if pr.get("merged_at") else pr["state"]
            entry = (
                f"- [{repo}#{pr['number']}]({pr['html_url']}) {pr['title']}"
                f" by {pr['user']['login']} ({state_label}, updated {pr['updated_at'][:10]})"
            )
            if pr["user"]["login"].lower() == owner.lower():
                our_lines.append(entry)
                if not first_run:
                    for kind, path in (
                        ("comment", f"/repos/{repo}/issues/{pr['number']}/comments"),
                        ("review comment", f"/repos/{repo}/pulls/{pr['number']}/comments"),
                        ("review", f"/repos/{repo}/pulls/{pr['number']}/reviews"),
                    ):
                        items = try_api(path)
                        for item in items if isinstance(items, list) else []:
                            when = item.get("created_at") or item.get("submitted_at") or ""
                            who = (item.get("user") or {}).get("login", "")
                            if when > since and who.lower() != owner.lower():
                                body = first_line(item.get("body") or item.get("state") or "")
                                our_lines.append(f"  - {kind} by {who} ({when[:10]}): {body}")
            else:
                pr_lines.append(entry)
        if not first_run:
            issues = try_api(f"/repos/{repo}/issues", f"&state=all&since={since}")
            for issue in issues if isinstance(issues, list) else []:
                if "pull_request" in issue or issue["created_at"] <= since:
                    continue
                issue_lines.append(
                    f"- [{repo}#{issue['number']}]({issue['html_url']}) {issue['title']}"
                    f" by {issue['user']['login']} ({issue['state']})"
                )
            releases = try_api(f"/repos/{repo}/releases")
            for release in releases if isinstance(releases, list) else []:
                if (release.get("published_at") or "") > since:
                    release_lines.append(
                        f"- [{repo} {release['tag_name']}]({release['html_url']})"
                        f" {release.get('name') or ''}".rstrip()
                    )

    lines += ["## Our pull requests upstream", ""] + (our_lines or ["No activity."]) + [""]
    lines += ["## Other pull requests (new or updated)", ""] + (pr_lines or ["None."]) + [""]
    lines += ["## New issues", ""] + (issue_lines or ["None." if not first_run else "(not listed on the first run)"]) + [""]
    lines += ["## New releases", ""] + (release_lines or ["None." if not first_run else "(not listed on the first run)"]) + [""]

    state = {"last_run": now, "branches": new_branches, "network": network}
    with open(os.path.join(out_dir, "state.json"), "w") as f:
        json.dump(state, f, indent=1, sort_keys=True)
    with open(os.path.join(out_dir, "report.md"), "w") as f:
        f.write("\n".join(lines).rstrip() + "\n")


if __name__ == "__main__":
    main()
