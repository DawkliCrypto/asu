from urllib.parse import urlparse

from asu.config import settings
from asu.util import client_get


def is_repo_allowed(repo_url: str, allow_list: list[str]) -> bool:
    """Check if a repository URL is allowed by the allow list.

    Uses proper URL parsing to prevent subdomain and userinfo bypasses
    that affect naive prefix matching.
    """
    if not allow_list:
        return False
    parsed = urlparse(repo_url)
    for allowed in allow_list:
        allowed_parsed = urlparse(allowed)
        if (
            parsed.scheme == allowed_parsed.scheme
            and parsed.hostname == allowed_parsed.hostname
            and parsed.path.startswith(allowed_parsed.path.rstrip("/") + "/")
        ):
            return True
    return False


def merge_repositories(
    base_content: str, extra_repos: dict[str, str], apk_mode: bool
) -> str:
    """Append extra repositories to existing content.

    For opkg (repositories.conf): entries are `src/gz <name> <url>`.
    For apk (repositories): entries are plain URLs, one per line.
    """
    lines = [line for line in base_content.splitlines() if line.strip()]

    for name, url in sorted(extra_repos.items()):
        if apk_mode:
            lines.append(url)
        else:
            lines.append(f"src/gz {name} {url}")

    if not apk_mode:
        if not any("src imagebuilder file:packages" in line for line in lines):
            lines.append("src imagebuilder file:packages")
        if not any("option check_signature" in line for line in lines):
            lines.append("option check_signature")

    return "\n".join(lines) + "\n"


def validate_repos(repositories: dict[str, str]) -> dict[str, str]:
    """Filter repositories against the allow list.

    Repositories are already validated at the API level, but this
    provides defense-in-depth for the build worker.
    """
    return {
        name: url
        for name, url in repositories.items()
        if is_repo_allowed(url, settings.repository_allow_list)
    }


def get_customfeed_keys(customfeeds: str | None) -> list[str]:
    """Fetch public APK keys published beside custom feed indexes."""
    if not customfeeds:
        return []

    keys = []
    for feed in customfeeds.splitlines():
        feed = feed.strip()
        if not feed or feed.startswith("#"):
            continue
        parsed = urlparse(feed)
        parts = parsed.path.rstrip("/").split("/")
        if len(parts) < 4 or parts[-3:] != ["packages", "apk", "packages.adb"]:
            continue

        repository = parts[-4]
        base_path = "/".join(parts[:-3])
        names = [repository]
        if repository.startswith("luci-app-"):
            names.append(repository.removeprefix("luci-app-"))

        for name in names:
            key_url = f"{parsed.scheme}://{parsed.netloc}{base_path}/keys/{name}-apk.pem"
            response = client_get(key_url)
            if response.status_code == 200 and response.text.startswith(
                "-----BEGIN PUBLIC KEY-----"
            ):
                keys.append(response.text)
                break

    return keys
