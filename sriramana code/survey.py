#!/usr/bin/env python
"""
Real-world MCP server survey harness.

Runs the assurance suite against a curated list of public MCP servers and
produces aggregate research findings:

  RQ2 - what conformance issues actually occur in real-world MCP servers?
  RQ3 - how does automated assurance testing surface reliability problems?

All servers are tested over STDIO without API keys. Credential-gated servers
are skipped unless the relevant environment variable is set.

Usage:
    python survey.py
"""
import argparse
import csv
import json
import os
import shutil
import site
import statistics
import subprocess
import sys
import sysconfig
import tempfile
import threading
from pathlib import Path

from core.client import HttpMCPClient, StdioMCPClient
from core.suite import perform_initialize, run_suite


PROTOCOL_VERSION = "2025-11-25"

# Phase 1 (liveness / cache warm-up): a generous window for first contact, so
# that npx/uvx can finish a first-run package download before the handshake.
PROBE_TIMEOUT_SECONDS = int(os.getenv("SURVEY_PROBE_TIMEOUT", "90"))
# Phase 2 split timeout: a long budget for the server's first response absorbs
# process cold-start, while a short per-request timeout lets negative tests a
# server ignores fail fast - cutting most of the survey's wall-clock time.
SUITE_STARTUP_TIMEOUT_SECONDS = int(os.getenv("SURVEY_STARTUP_TIMEOUT", "30"))
SUITE_REQUEST_TIMEOUT_SECONDS = int(os.getenv("SURVEY_REQUEST_TIMEOUT", "5"))
# Hard wall-clock cap for the whole measured suite per server.
SUITE_TIMEOUT_SECONDS = int(os.getenv("SURVEY_SUITE_TIMEOUT", "150"))

OUTPUT_DIR = Path("reports/survey")


# --------------------------------------------------------------------------- #
# PART A - curated server list
# --------------------------------------------------------------------------- #
SURVEY_SERVERS = [
    # --- TypeScript official ------------------------------------------------ #
    {
        "name": "server-everything",
        "sdk": "typescript",
        "source": "official",
        "transport": "stdio",
        "command": "npx -y @modelcontextprotocol/server-everything",
        "requires_credentials": False,
        "notes": "Reference MCP server with all primitive types",
    },
    {
        "name": "server-filesystem",
        "sdk": "typescript",
        "source": "official",
        "transport": "stdio",
        "command": "npx -y @modelcontextprotocol/server-filesystem .",
        "requires_credentials": False,
        "notes": "File system access MCP server",
    },
    {
        "name": "server-memory",
        "sdk": "typescript",
        "source": "official",
        "transport": "stdio",
        "command": "npx -y @modelcontextprotocol/server-memory",
        "requires_credentials": False,
        "notes": "In-memory knowledge graph server",
    },
    {
        "name": "server-sequentialthinking",
        "sdk": "typescript",
        "source": "official",
        "transport": "stdio",
        "command": "npx -y @modelcontextprotocol/server-sequential-thinking",
        "requires_credentials": False,
        "notes": "Sequential thinking and reasoning tools",
    },
    # --- TypeScript community ----------------------------------------------- #
    {
        "name": "playwright-mcp",
        "sdk": "typescript",
        "source": "official",
        "transport": "stdio",
        "command": "npx -y @playwright/mcp",
        "requires_credentials": False,
        "notes": "Browser automation (Playwright) server (replaces unreachable mcp-server-commands)",
    },
    {
        "name": "mcp-hn",
        "sdk": "typescript",
        "source": "community",
        "transport": "stdio",
        "command": "npx -y @devabdultech/hn-mcp-server",
        "requires_credentials": False,
        "notes": "Hacker News community MCP server",
    },
    # --- Python official ---------------------------------------------------- #
    {
        "name": "mcp-server-time",
        "sdk": "python",
        "source": "official",
        "transport": "stdio",
        "command": "uvx mcp-server-time",
        "requires_credentials": False,
        "notes": "Current time and timezone tools",
    },
    {
        "name": "mcp-server-git",
        "sdk": "python",
        "source": "official",
        "transport": "stdio",
        "command": "uvx mcp-server-git --repository .",
        "requires_credentials": False,
        "notes": "Git repository operations",
    },
    {
        "name": "mcp-server-fetch",
        "sdk": "python",
        "source": "official",
        "transport": "stdio",
        "command": "uvx mcp-server-fetch",
        "requires_credentials": False,
        "notes": "Python fetch server",
    },
    # --- Python community --------------------------------------------------- #
    {
        "name": "mcp-server-calculator",
        "sdk": "python",
        "source": "community",
        "transport": "stdio",
        "command": "uvx mcp-server-calculator",
        "requires_credentials": False,
        "notes": "Basic calculator operations",
    },
    {
        "name": "mcp-datetime",
        "sdk": "python",
        "source": "community",
        "transport": "stdio",
        "command": "uvx mcp-datetime",
        "requires_credentials": False,
        "notes": "Date and time utilities",
    },
    # --- Expanded TypeScript official -------------------------------------- #
    {
        "name": "mcp-server-airbnb",
        "sdk": "typescript",
        "source": "community",
        "transport": "stdio",
        "command": "npx -y @openbnb/mcp-server-airbnb",
        "requires_credentials": False,
        "notes": "Airbnb listings search server (replaces unreachable mcp-server-puppeteer)",
    },
    # --- Expanded Python official ------------------------------------------ #
    {
        "name": "mcp-server-sqlite",
        "sdk": "python",
        "source": "official",
        "transport": "stdio",
        "command": "uvx mcp-server-sqlite --db-path /tmp/test.db",
        "requires_credentials": False,
        "notes": "SQLite database server",
    },
    # --- Expanded Python community ----------------------------------------- #
    {
        "name": "mcp-server-duckduckgo",
        "sdk": "python",
        "source": "community",
        "transport": "stdio",
        "command": "uvx duckduckgo-mcp-server",
        "requires_credentials": False,
        "notes": "DuckDuckGo search server",
    },
    {
        "name": "arxiv-mcp-server",
        "sdk": "python",
        "source": "community",
        "transport": "stdio",
        "command": "uvx arxiv-mcp-server",
        "requires_credentials": False,
        "notes": "ArXiv paper search server (replaces not-found mcp-server-httpx)",
    },
    {
        "name": "wikipedia-mcp",
        "sdk": "python",
        "source": "community",
        "transport": "stdio",
        "command": "uvx wikipedia-mcp",
        "requires_credentials": False,
        "notes": "Wikipedia content/search server (replaces not-found mcp-server-filesystem)",
    },
    # --- Registry-verified additions (handshake-confirmed, no credentials) - #
    {
        "name": "notion-mcp",
        "sdk": "typescript",
        "source": "official",
        "transport": "stdio",
        "command": "npx -y @notionhq/notion-mcp-server",
        "requires_credentials": False,
        "notes": "Notion API MCP server (vendor-official)",
    },
    {
        "name": "adeu-mcp",
        "sdk": "typescript",
        "source": "community",
        "transport": "stdio",
        "command": "npx -y @adeu/mcp-server",
        "requires_credentials": False,
        "notes": "Registry-listed MCP server (handshake-verified)",
    },
    {
        "name": "computeback-mcp",
        "sdk": "typescript",
        "source": "community",
        "transport": "stdio",
        "command": "npx -y @autonomad1/computeback-mcp",
        "requires_credentials": False,
        "notes": "Registry-listed MCP server (handshake-verified)",
    },
    {
        "name": "autonomad-travel",
        "sdk": "typescript",
        "source": "community",
        "transport": "stdio",
        "command": "npx -y autonomad-travel",
        "requires_credentials": False,
        "notes": "Registry-listed travel MCP server (handshake-verified)",
    },
    {
        "name": "optibot-mcp",
        "sdk": "typescript",
        "source": "community",
        "transport": "stdio",
        "command": "npx -y @optimalai/optibot-mcp",
        "requires_credentials": False,
        "notes": "Registry-listed MCP server (handshake-verified)",
    },
    {
        "name": "ai-dossier-mcp",
        "sdk": "typescript",
        "source": "community",
        "transport": "stdio",
        "command": "npx -y @ai-dossier/mcp-server",
        "requires_credentials": False,
        "notes": "Registry-listed MCP server (handshake-verified)",
    },
    {
        "name": "kawacode-mcp",
        "sdk": "typescript",
        "source": "community",
        "transport": "stdio",
        "command": "npx -y @kawacode/mcp",
        "requires_credentials": False,
        "notes": "Registry-listed MCP server (handshake-verified)",
    },
    {
        "name": "meetlark-mcp",
        "sdk": "typescript",
        "source": "community",
        "transport": "stdio",
        "command": "npx -y @meetlark/mcp-server",
        "requires_credentials": False,
        "notes": "Registry-listed MCP server (handshake-verified)",
    },
    {
        "name": "nocturnusai-mcp",
        "sdk": "typescript",
        "source": "community",
        "transport": "stdio",
        "command": "npx -y nocturnusai-mcp",
        "requires_credentials": False,
        "notes": "Registry-listed MCP server (handshake-verified)",
    },
    {
        "name": "rapay-mcp",
        "sdk": "typescript",
        "source": "community",
        "transport": "stdio",
        "command": "npx -y @rapay/mcp-server",
        "requires_credentials": False,
        "notes": "Registry-listed MCP server (handshake-verified)",
    },
    {
        "name": "raven-mcp",
        "sdk": "typescript",
        "source": "community",
        "transport": "stdio",
        "command": "npx -y raven-mcp",
        "requires_credentials": False,
        "notes": "Registry-listed MCP server (handshake-verified)",
    },
    {
        "name": "mcpcap",
        "sdk": "python",
        "source": "community",
        "transport": "stdio",
        "command": "uvx mcpcap",
        "requires_credentials": False,
        "notes": "Registry-listed PCAP analysis MCP server (handshake-verified)",
    },
    {
        "name": "nudg3-mcp",
        "sdk": "python",
        "source": "community",
        "transport": "stdio",
        "command": "uvx nudg3-mcp",
        "requires_credentials": False,
        "notes": "Registry-listed MCP server (handshake-verified)",
    },
    {
        "name": "mcp-server-perplexity",
        "sdk": "python",
        "source": "community",
        "transport": "stdio",
        "command": "uvx mcp-server-perplexity",
        "requires_credentials": False,
        "notes": "Perplexity search MCP server (handshake-verified)",
    },
    {
        "name": "mcp-server-jupyter",
        "sdk": "python",
        "source": "community",
        "transport": "stdio",
        "command": "uvx mcp-server-jupyter",
        "requires_credentials": False,
        "notes": "Jupyter notebook MCP server (handshake-verified)",
    },
    # --- HTTP-transport servers (registry remotes, no credentials) --------- #
    # Hosted MCP endpoints reached over HTTP rather than spawned over STDIO.
    # These exercise the HTTP-only Authorization Conformance cases (version
    # header, OAuth discovery, unauthenticated handling) that always SKIP on
    # STDIO targets. SDK is "unknown" — registry *remotes* carry no package
    # identifier to infer it from. Being public network endpoints, any one may
    # be down at survey time; several are listed so at least one yields data.
    {
        "name": "boolsai-scan",
        "sdk": "unknown",
        "source": "community",
        "transport": "http",
        "url": "https://boolsai.ai/mcp",
        "requires_credentials": False,
        "notes": "Registry HTTP remote ai.boolsai/scan (handshake-verified)",
    },
    {
        "name": "boolsai-signals",
        "sdk": "unknown",
        "source": "community",
        "transport": "http",
        "url": "https://signals.boolsai.ai/mcp",
        "requires_credentials": False,
        "notes": "Registry HTTP remote ai.boolsai/signals (handshake-verified)",
    },
    {
        "name": "auteng-mcp",
        "sdk": "unknown",
        "source": "community",
        "transport": "http",
        "url": "https://auteng.ai/mcp",
        "requires_credentials": False,
        "notes": "Registry HTTP remote ai.auteng/mcp (handshake-verified)",
    },
    {
        "name": "abmeter-mcp",
        "sdk": "unknown",
        "source": "community",
        "transport": "http",
        "url": "https://mcp.abmeter.ai",
        "requires_credentials": False,
        "notes": "Registry HTTP remote ai.abmeter/abmeter (handshake-verified)",
    },
    {
        "name": "agenticshelf-mcp",
        "sdk": "unknown",
        "source": "community",
        "transport": "http",
        "url": "https://api.agenticshelf.ai/mcp",
        "requires_credentials": False,
        "notes": "Registry HTTP remote ai.agenticshelf/mcp (handshake-verified)",
    },
    # --- Credential-gated (skipped unless env var set) ---------------------- #
    {
        "name": "server-github",
        "sdk": "typescript",
        "source": "official",
        "transport": "stdio",
        "command": "npx -y @modelcontextprotocol/server-github",
        "requires_credentials": True,
        "notes": "GitHub API - needs GITHUB_PERSONAL_ACCESS_TOKEN",
    },
    {
        "name": "server-brave-search",
        "sdk": "typescript",
        "source": "official",
        "transport": "stdio",
        "command": "npx -y @modelcontextprotocol/server-brave-search",
        "requires_credentials": True,
        "notes": "Brave Search API - needs BRAVE_API_KEY",
    },
    {
        "name": "server-slack",
        "sdk": "typescript",
        "source": "official",
        "transport": "stdio",
        "command": "npx -y @modelcontextprotocol/server-slack",
        "requires_credentials": True,
        "notes": "Slack API - needs SLACK_BOT_TOKEN",
    },
    {
        "name": "server-google-maps",
        "sdk": "typescript",
        "source": "official",
        "transport": "stdio",
        "command": "npx -y @modelcontextprotocol/server-google-maps",
        "requires_credentials": True,
        "notes": "Google Maps - needs GOOGLE_MAPS_API_KEY",
    },
    {
        "name": "mcp-server-gitlab",
        "sdk": "typescript",
        "source": "community",
        "transport": "stdio",
        "command": "npx -y @modelcontextprotocol/server-gitlab",
        "requires_credentials": True,
        "notes": "GitLab API - needs GITLAB_PERSONAL_ACCESS_TOKEN",
    },
    {
        "name": "mcp-server-aws-kb",
        "sdk": "typescript",
        "source": "official",
        "transport": "stdio",
        "command": "npx -y @modelcontextprotocol/server-aws-kb-retrieval",
        "requires_credentials": True,
        "notes": "AWS KB retrieval - needs AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY",
    },
]

# Maps a credential-gated server name to the environment variable that must be
# present for it to be tested. Keeps SURVEY_SERVERS entries to the documented
# field set while still letting PART B decide what to skip.
CREDENTIAL_ENV = {
    "server-github": "GITHUB_PERSONAL_ACCESS_TOKEN",
    "server-brave-search": "BRAVE_API_KEY",
    "server-slack": "SLACK_BOT_TOKEN",
    "server-google-maps": "GOOGLE_MAPS_API_KEY",
    "mcp-server-gitlab": "GITLAB_PERSONAL_ACCESS_TOKEN",
    "mcp-server-aws-kb": "AWS_ACCESS_KEY_ID",
}

# Fields written, in order, to survey_results.json per server.
JSON_FIELDS = [
    "name", "sdk", "source", "transport", "status", "score",
    "passed", "failed", "warned", "skipped",
    "must_violations", "should_advisories",
    "failed_tests", "warned_tests", "notes",
]

# Columns written, in order, to survey_summary.csv per server.
CSV_FIELDS = [
    "name", "sdk", "source", "status", "score",
    "passed", "failed", "warned", "skipped",
    "must_violations", "should_advisories", "top_failures",
]


# --------------------------------------------------------------------------- #
# PART B - execution engine
# --------------------------------------------------------------------------- #
def _blank_result(server):
    """A result record pre-populated with the server's static metadata and
    zeroed counters (the unreachable/skipped default)."""
    return {
        "name": server["name"],
        "sdk": server["sdk"],
        "source": server["source"],
        "transport": server["transport"],
        "status": "unreachable",
        "score": 0.0,
        "passed": 0,
        "failed": 0,
        "warned": 0,
        "skipped": 0,
        "must_violations": 0,
        "should_advisories": 0,
        "failed_tests": [],
        "warned_tests": [],
        # internal: maps a failed test name -> its spec clause, used to build
        # the "most violated spec clauses" ranking. Not written to JSON/CSV.
        "_failed_clauses": {},
        "notes": server["notes"],
    }


def _create_client(server, *, timeout, startup_timeout=None):
    """Build the right MCP client for a server's transport.

    HTTP servers connect to a live URL via HttpMCPClient (no process to spawn);
    STDIO servers spawn their command via StdioMCPClient with a split startup/
    per-request timeout. Centralising this lets the survey treat both transports
    uniformly so the HTTP-only Authorization Conformance cases produce real
    data instead of always SKIPping."""
    if server.get("transport") == "http":
        return HttpMCPClient(
            server["url"],
            timeout=timeout,
            protocol_version=PROTOCOL_VERSION,
        )
    return StdioMCPClient(
        server["command"],
        timeout=timeout,
        startup_timeout=startup_timeout if startup_timeout is not None else timeout,
        protocol_version=PROTOCOL_VERSION,
    )


def _run_suite_with_timeout(client, protocol_version, timeout):
    """Run run_suite in a worker thread and enforce a hard wall-clock budget.

    If the suite has not finished within ``timeout`` seconds we raise
    TimeoutError; the caller then closes the client, which terminates the
    server subprocess and unblocks the (daemon) worker thread."""
    holder = {}

    def target():
        try:
            holder["results"] = run_suite(client, protocol_version)
        except Exception as exc:  # noqa: BLE001 - re-raised on the main thread
            holder["error"] = exc

    worker = threading.Thread(target=target, daemon=True)
    worker.start()
    worker.join(timeout)

    if worker.is_alive():
        raise TimeoutError(f"suite exceeded {timeout}s budget")
    if "error" in holder:
        raise holder["error"]
    return holder["results"]


def _handshake_ok(server):
    """Phase 1: confirm the server can actually establish an MCP session.

    A real MCP server must complete an initialize handshake. If it cannot
    (launcher missing, wrong package name, crash on start, or a transport
    mismatch) we treat the server as unreachable rather than scoring it 0% as
    though it were a conformance failure. The generous timeout also lets a
    first-run npx/uvx download complete (and warms the cache for phase 2)."""
    client = None
    try:
        client = _create_client(server, timeout=PROBE_TIMEOUT_SECONDS)
        _, validation = perform_initialize(
            client, PROTOCOL_VERSION, send_initialized=False
        )
        return bool(validation.passed)
    except Exception:  # noqa: BLE001 - any failure => not reachable
        return False
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:  # noqa: BLE001 - best-effort cleanup
                pass


def survey_one(server):
    """Run the assurance suite against a single server and return its record."""
    record = _blank_result(server)
    name = server["name"]

    # Step 1 - skip credential-gated servers when the env var is absent.
    if server["requires_credentials"]:
        env_var = CREDENTIAL_ENV.get(name)
        if not env_var or not os.getenv(env_var):
            record["status"] = "skipped_credentials"
            return record

    # Phase 1 - liveness gate: a server that cannot even handshake is
    # unreachable, NOT a 0% conformance result.
    if not _handshake_ok(server):
        record["status"] = "unreachable"
        return record

    # Phase 2 - measured run against the now-warm, known-live server.
    client = None
    try:
        client = _create_client(
            server,
            timeout=SUITE_REQUEST_TIMEOUT_SECONDS,
            startup_timeout=SUITE_STARTUP_TIMEOUT_SECONDS,
        )
        results = _run_suite_with_timeout(
            client, PROTOCOL_VERSION, SUITE_TIMEOUT_SECONDS
        )
    except Exception as exc:  # noqa: BLE001 - any failure => unreachable
        record["status"] = "unreachable"
        record["error"] = str(exc)
        return record
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:  # noqa: BLE001 - best-effort cleanup
                pass

    # Step 6 - summarise a successful run.
    passed = sum(1 for r in results if r.status == "PASS")
    failed = sum(1 for r in results if r.status == "FAIL")
    warned = sum(1 for r in results if r.status == "WARN")
    skipped = sum(1 for r in results if r.status == "SKIP")
    # MUST-compliance score: WARN (silent drops / SHOULD advisories) and SKIP
    # (not-applicable capabilities) are excluded from the denominator entirely.
    # Only PASS vs FAIL (a MUST-level wrong response) counts.
    denominator = passed + failed

    record.update({
        "status": "tested",
        "score": round((passed / denominator * 100) if denominator else 0.0, 2),
        "passed": passed,
        "failed": failed,
        "warned": warned,
        "skipped": skipped,
        "must_violations": sum(
            1 for r in results
            if r.status == "FAIL" and r.conformance_level == "MUST"
        ),
        "should_advisories": sum(
            1 for r in results
            if r.status == "WARN" and r.conformance_level == "SHOULD"
        ),
        "failed_tests": [r.test for r in results if r.status == "FAIL"],
        "warned_tests": [r.test for r in results if r.status == "WARN"],
        "_failed_clauses": {
            r.test: r.spec_clause for r in results if r.status == "FAIL"
        },
    })
    return record


def _candidate_script_dirs():
    """Directories where pip/uv console scripts (uvx.exe, etc.) may live but
    which are not always on PATH - especially for Microsoft Store Python."""
    dirs = []
    try:
        dirs.append(sysconfig.get_path("scripts"))
    except Exception:  # noqa: BLE001
        pass
    try:
        user_site = site.getusersitepackages()
        if user_site:
            base = os.path.dirname(user_site)
            dirs.append(os.path.join(base, "Scripts"))
            dirs.append(os.path.join(base, "bin"))
    except Exception:  # noqa: BLE001
        pass
    exe_dir = os.path.dirname(sys.executable)
    dirs.append(os.path.join(exe_dir, "Scripts"))
    dirs.append(exe_dir)

    resolved = []
    for d in dirs:
        if d and d not in resolved and os.path.isdir(d):
            resolved.append(d)
    return resolved


def _ensure_launcher(name):
    """Make `name` (e.g. 'uvx'/'npx') resolvable for spawned servers.

    Returns True if the launcher is callable - augmenting this process's PATH
    from known Python script locations when necessary so the survey is
    reproducible without the user having to fix PATH by hand. Child server
    processes inherit the augmented PATH."""
    if shutil.which(name):
        return True
    for directory in _candidate_script_dirs():
        for candidate in (name, name + ".exe", name + ".cmd", name + ".bat"):
            if os.path.isfile(os.path.join(directory, candidate)):
                os.environ["PATH"] = directory + os.pathsep + os.environ.get("PATH", "")
                if shutil.which(name):
                    return True
    return bool(shutil.which(name))


def _ensure_git_repo():
    """Create a throwaway git repo so mcp-server-git has a valid --repository
    target. The git server exits on start when pointed at a non-repository, so
    without this it reports as unreachable for a config reason, not a real one.
    Returns the repo path, or None if git is unavailable."""
    if not shutil.which("git"):
        return None
    repo = Path(tempfile.gettempdir()) / "mcp_survey_git_repo"
    try:
        repo.mkdir(parents=True, exist_ok=True)
        if not (repo / ".git").is_dir():
            subprocess.run(
                ["git", "init", "-q"],
                cwd=repo, check=True, capture_output=True, timeout=30,
            )
            subprocess.run(
                ["git", "-c", "user.email=survey@local", "-c", "user.name=survey",
                 "commit", "--allow-empty", "-q", "-m", "init"],
                cwd=repo, check=True, capture_output=True, timeout=30,
            )
        return str(repo)
    except Exception:  # noqa: BLE001 - git prep is best-effort
        return None


def run_survey(only_names=None):
    """Run the whole survey, write report files, and print a research summary.

    If ``only_names`` is given, restrict the run to servers whose name is in
    that collection (used by `--servers` to test a subset, e.g. just the HTTP
    targets)."""
    servers = SURVEY_SERVERS
    if only_names:
        wanted = set(only_names)
        servers = [s for s in SURVEY_SERVERS if s["name"] in wanted]
        missing = wanted - {s["name"] for s in servers}
        if missing:
            print(f"[warn] unknown server name(s) ignored: {sorted(missing)}")
        if not servers:
            raise SystemExit("No matching servers to run.")

    print("\n===== MCP REAL-WORLD SERVER SURVEY =====\n")
    print(f"Servers in catalogue: {len(servers)}")
    print(f"Protocol version: {PROTOCOL_VERSION}")
    print(
        f"Probe timeout: {PROBE_TIMEOUT_SECONDS}s | "
        f"Suite startup: {SUITE_STARTUP_TIMEOUT_SECONDS}s | "
        f"Suite request: {SUITE_REQUEST_TIMEOUT_SECONDS}s | "
        f"Suite cap: {SUITE_TIMEOUT_SECONDS}s"
    )

    # Make the server launchers resolvable so `python survey.py` is reproducible
    # without manual PATH surgery (Store Python hides uvx in a non-PATH dir).
    for launcher in ("npx", "uvx"):
        available = _ensure_launcher(launcher)
        state = "available" if available else "NOT FOUND (its servers will be unreachable)"
        print(f"Launcher {launcher}: {state}")

    # mcp-server-git needs a real repository to start; point it at a throwaway
    # one so its result reflects conformance rather than a missing argument.
    git_repo = _ensure_git_repo()
    if git_repo:
        for entry in servers:
            if entry["name"] == "mcp-server-git":
                entry["command"] = f'uvx mcp-server-git --repository "{git_repo}"'
        print(f"Git repo for mcp-server-git: {git_repo}")
    print()

    records = []
    for index, server in enumerate(servers, 1):
        print(f"[{index:2}/{len(servers)}] {server['name']} ... ", end="", flush=True)
        record = survey_one(server)
        if record["status"] == "tested":
            print(
                f"{record['status']} "
                f"({record['score']}% | {record['passed']}P/"
                f"{record['failed']}F/{record['warned']}W/{record['skipped']}S)"
            )
        else:
            print(record["status"])
        records.append(record)
        # Full runs write after each server so a long/interrupted run never
        # loses data. Subset (--servers) runs must NOT clobber the full dataset,
        # so they defer to a single merge-write at the end.
        if not only_names:
            _write_outputs(records, announce=False)

    if only_names:
        merged = _merge_records(records)
        _write_outputs(merged)
        print(f"\nMerged {len(records)} subset result(s) into the existing "
              f"dataset ({len(merged)} servers total).")
    else:
        _write_outputs(records)
    _print_summary(records)
    return records


def _merge_records(new_records):
    """Merge subset results into the existing survey_results.json by name
    (replace matching, append new), preserving the original order. Lets a
    `--servers` run enrich the dataset (e.g. add HTTP auth data) instead of
    overwriting the full survey."""
    json_path = OUTPUT_DIR / "survey_results.json"
    existing = []
    if json_path.exists():
        try:
            existing = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            existing = []
    by_name = {r.get("name"): r for r in existing}
    order = [r.get("name") for r in existing]
    for rec in new_records:
        slim = {field: rec[field] for field in JSON_FIELDS}
        if slim["name"] not in by_name:
            order.append(slim["name"])
        by_name[slim["name"]] = slim
    return [by_name[n] for n in order]


# --------------------------------------------------------------------------- #
# PART C - output files
# --------------------------------------------------------------------------- #
def _write_outputs(records, announce=True):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = OUTPUT_DIR / "survey_results.json"
    json_payload = [
        {field: record[field] for field in JSON_FIELDS}
        for record in records
    ]
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(json_payload, handle, indent=4)

    csv_path = OUTPUT_DIR / "survey_summary.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_FIELDS)
        for record in records:
            top_failures = ", ".join(record["failed_tests"][:3])
            writer.writerow([
                record["name"],
                record["sdk"],
                record["source"],
                record["status"],
                record["score"],
                record["passed"],
                record["failed"],
                record["warned"],
                record["skipped"],
                record["must_violations"],
                record["should_advisories"],
                top_failures,
            ])

    if announce:
        print(f"\nJSON results saved: {json_path}")
        print(f"CSV summary saved:  {csv_path}")


# --------------------------------------------------------------------------- #
# PART D - console research summary
# --------------------------------------------------------------------------- #
def _mean(values):
    return round(statistics.mean(values), 2) if values else 0.0


def _median(values):
    return round(statistics.median(values), 2) if values else 0.0


def _print_summary(records):
    tested = [r for r in records if r["status"] == "tested"]
    unreachable = [r for r in records if r["status"] == "unreachable"]
    skipped_creds = [r for r in records if r["status"] == "skipped_credentials"]
    tested_count = len(tested)
    scores = [r["score"] for r in tested]

    # --- Section 1 - Overview ---------------------------------------------- #
    print("\n" + "=" * 70)
    print("SECTION 1 - OVERVIEW")
    print("=" * 70)
    print(f"Servers attempted:          {len(records)}")
    print(f"Tested successfully:        {tested_count}")
    print(f"Unreachable:                {len(unreachable)}")
    print(f"Skipped (credentials):      {len(skipped_creds)}")
    print(f"Mean MUST compliance score:   {_mean(scores)}%  (PASS / (PASS+FAIL); WARN & SKIP excluded)")
    print(f"Median MUST compliance score: {_median(scores)}%")

    # --- Section 2 - By SDK and source ------------------------------------- #
    print("\n" + "=" * 70)
    print("SECTION 2 - BY SDK AND SOURCE (tested servers, MUST compliance score)")
    print("=" * 70)
    ts_scores = [r["score"] for r in tested if r["sdk"] == "typescript"]
    py_scores = [r["score"] for r in tested if r["sdk"] == "python"]
    official_scores = [r["score"] for r in tested if r["source"] == "official"]
    community_scores = [r["score"] for r in tested if r["source"] == "community"]
    print(f"TypeScript mean MUST score: {_mean(ts_scores)}%  (n={len(ts_scores)})")
    print(f"Python mean MUST score:     {_mean(py_scores)}%  (n={len(py_scores)})")
    print(f"Official mean MUST score:   {_mean(official_scores)}%  (n={len(official_scores)})")
    print(f"Community mean MUST score:  {_mean(community_scores)}%  (n={len(community_scores)})")

    # --- Section 3 - Most violated spec clauses ---------------------------- #
    print("\n" + "=" * 70)
    print("SECTION 3 - MOST VIOLATED SPEC CLAUSES (top 10, tested servers)")
    print("=" * 70)
    failure_counts = {}
    clause_for_test = {}
    for record in tested:
        for test_name in record["failed_tests"]:
            failure_counts[test_name] = failure_counts.get(test_name, 0) + 1
            clause_for_test.setdefault(
                test_name, record["_failed_clauses"].get(test_name, "")
            )

    if not failure_counts:
        print("No test failures recorded across tested servers.")
    else:
        ranked = sorted(
            failure_counts.items(), key=lambda item: (-item[1], item[0])
        )[:10]
        for rank, (test_name, count) in enumerate(ranked, 1):
            rate = (count / tested_count * 100) if tested_count else 0.0
            clause = clause_for_test.get(test_name, "") or "(no clause)"
            print(f"{rank:2}. {test_name}")
            print(f"    clause: {clause}")
            print(f"    failed on {count}/{tested_count} servers ({rate:.1f}%)")

    # --- Section 4 - MUST vs SHOULD breakdown ------------------------------ #
    print("\n" + "=" * 70)
    print("SECTION 4 - MUST vs SHOULD BREAKDOWN (tested servers)")
    print("=" * 70)
    total_must = sum(r["must_violations"] for r in tested)
    total_should = sum(r["should_advisories"] for r in tested)
    must_clean = [r for r in tested if r["must_violations"] == 0]
    must_clean_pct = (len(must_clean) / tested_count * 100) if tested_count else 0.0
    mean_must = _mean([r["must_violations"] for r in tested])
    mean_should = _mean([r["should_advisories"] for r in tested])
    print(f"Total MUST violations:          {total_must}")
    print(f"Total SHOULD advisories:        {total_should}")
    print(f"Mean MUST violations/server:    {mean_must}")
    print(f"Mean SHOULD advisories/server:  {mean_should}")
    print(
        f"Fully MUST-compliant servers:   "
        f"{len(must_clean)}/{tested_count} ({must_clean_pct:.1f}%)"
    )
    print("=" * 70 + "\n")


def dry_run():
    """List the catalogue without contacting any server. Lets us confirm the
    server set (and credential gating) before committing to a real survey run."""
    print("\n===== MCP SURVEY DRY RUN (no servers contacted) =====\n")
    print(f"Total servers in catalogue: {len(SURVEY_SERVERS)}\n")

    header = f"{'#':>2}  {'name':<26} {'sdk':<11} {'source':<10} {'creds':<5} command"
    print(header)
    print("-" * len(header))
    for index, srv in enumerate(SURVEY_SERVERS, 1):
        creds = "yes" if srv["requires_credentials"] else "no"
        target = srv.get("command") or srv.get("url", "")
        print(
            f"{index:>2}  {srv['name']:<26} {srv['sdk']:<11} "
            f"{srv['source']:<10} {creds:<5} {target}"
        )

    by_sdk = {}
    by_source = {}
    cred_gated = []
    testable = []
    for srv in SURVEY_SERVERS:
        by_sdk[srv["sdk"]] = by_sdk.get(srv["sdk"], 0) + 1
        by_source[srv["source"]] = by_source.get(srv["source"], 0) + 1
        if srv["requires_credentials"]:
            env_var = CREDENTIAL_ENV.get(srv["name"], "?")
            present = bool(os.getenv(env_var)) if env_var != "?" else False
            cred_gated.append((srv["name"], env_var, present))
        else:
            testable.append(srv["name"])

    print("\n----- Breakdown -----")
    print("By SDK:    " + ", ".join(f"{k}={v}" for k, v in sorted(by_sdk.items())))
    print("By source: " + ", ".join(f"{k}={v}" for k, v in sorted(by_source.items())))
    print(f"Testable without credentials: {len(testable)}")
    print(f"Credential-gated:             {len(cred_gated)}")
    for name, env_var, present in cred_gated:
        state = "SET" if present else "missing -> will skip"
        print(f"  - {name:<24} requires {env_var} ({state})")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Run the real-world MCP server survey.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List the server catalogue and exit without running the survey.",
    )
    parser.add_argument(
        "--servers",
        nargs="+",
        metavar="NAME",
        help="Restrict the run to these server names (e.g. the HTTP targets).",
    )
    args = parser.parse_args()

    if args.dry_run:
        dry_run()
        return
    run_survey(only_names=args.servers)


if __name__ == "__main__":
    main()
