from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import deque
from pathlib import Path
from typing import Any
from urllib.parse import urldefrag, urljoin, urlparse

from playwright.sync_api import BrowserContext, Page, sync_playwright

HTTP_SCHEMES = {"http", "https"}


def safe_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in HTTP_SCHEMES or not parsed.hostname:
        raise ValueError("URL must use http or https and contain a hostname")
    if parsed.username or parsed.password:
        raise ValueError("Credentials must not be embedded in the URL")
    return urldefrag(value)[0]


def same_origin(left: str, right: str) -> bool:
    a = urlparse(left)
    b = urlparse(right)
    return (a.scheme, a.hostname, a.port) == (b.scheme, b.hostname, b.port)


def slug(value: str) -> str:
    parsed = urlparse(value)
    path = parsed.path.strip("/") or "root"
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", path)[:80]
    digest = hashlib.sha256(value.encode()).hexdigest()[:10]
    return f"{cleaned}-{digest}"


def new_context(playwright, timeout_ms: int) -> tuple[Any, BrowserContext]:
    executable = os.getenv("SECPLOIT_CHROMIUM_PATH", "/usr/bin/chromium")
    browser = playwright.chromium.launch(
        executable_path=executable,
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-background-networking",
        ],
    )
    context = browser.new_context(
        ignore_https_errors=True,
        accept_downloads=False,
        service_workers="block",
        viewport={"width": 1440, "height": 1000},
    )
    context.set_default_timeout(timeout_ms)
    context.set_default_navigation_timeout(timeout_ms)
    return browser, context


def page_evidence(page: Page, requested_url: str, network: list[dict[str, Any]]) -> dict[str, Any]:
    links = page.eval_on_selector_all(
        "a[href]",
        "elements => elements.map(e => ({href: e.href, text: (e.innerText || '').trim()}))",
    )
    forms = page.eval_on_selector_all(
        "form",
        """elements => elements.map(form => ({
            action: form.action,
            method: (form.method || 'get').toUpperCase(),
            inputs: Array.from(form.elements).map(element => ({
                name: element.name || '',
                type: element.type || element.tagName.toLowerCase()
            }))
        }))""",
    )
    scripts = page.eval_on_selector_all(
        "script[src]",
        "elements => elements.map(e => e.src)",
    )
    return {
        "requested_url": requested_url,
        "final_url": page.url,
        "title": page.title(),
        "links": links[:1000],
        "forms": forms[:200],
        "scripts": scripts[:500],
        "network": network[-2000:],
    }


def attach_network_capture(page: Page, network: list[dict[str, Any]]) -> None:
    def on_response(response) -> None:
        try:
            network.append(
                {
                    "url": response.url,
                    "status": response.status,
                    "content_type": response.headers.get("content-type", ""),
                    "server": response.headers.get("server", ""),
                }
            )
        except Exception:
            return

    page.on("response", on_response)


def snapshot(url: str, output: Path, timeout_ms: int) -> dict[str, Any]:
    url = safe_url(url)
    output.mkdir(parents=True, exist_ok=True)
    network: list[dict[str, Any]] = []

    with sync_playwright() as playwright:
        browser, context = new_context(playwright, timeout_ms)
        try:
            page = context.new_page()
            attach_network_capture(page, network)
            response = page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(750)
            evidence = page_evidence(page, url, network)
            evidence["navigation_status"] = response.status if response else None
            evidence["response_headers"] = response.headers if response else {}

            html_path = output / "page.html"
            screenshot_path = output / "page.png"
            metadata_path = output / "evidence.json"
            html_path.write_text(page.content(), encoding="utf-8")
            page.screenshot(path=str(screenshot_path), full_page=True)
            metadata_path.write_text(
                json.dumps(evidence, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            evidence["artifacts"] = [
                str(html_path),
                str(screenshot_path),
                str(metadata_path),
            ]
            return evidence
        finally:
            context.close()
            browser.close()


def crawl(
    url: str,
    output: Path,
    timeout_ms: int,
    max_pages: int,
    max_depth: int,
    screenshots: bool,
) -> dict[str, Any]:
    start_url = safe_url(url)
    output.mkdir(parents=True, exist_ok=True)
    queue: deque[tuple[str, int]] = deque([(start_url, 0)])
    visited: set[str] = set()
    pages: list[dict[str, Any]] = []

    with sync_playwright() as playwright:
        browser, context = new_context(playwright, timeout_ms)
        try:
            while queue and len(visited) < max_pages:
                current, depth = queue.popleft()
                current = urldefrag(current)[0]
                if current in visited or not same_origin(start_url, current):
                    continue
                visited.add(current)
                network: list[dict[str, Any]] = []
                page = context.new_page()
                attach_network_capture(page, network)

                record: dict[str, Any] = {"requested_url": current, "depth": depth}
                try:
                    response = page.goto(current, wait_until="domcontentloaded")
                    page.wait_for_timeout(400)
                    record.update(page_evidence(page, current, network))
                    record["navigation_status"] = response.status if response else None
                    record["response_headers"] = response.headers if response else {}
                    page_name = slug(current)
                    html_path = output / f"{page_name}.html"
                    html_path.write_text(page.content(), encoding="utf-8")
                    record["html_artifact"] = str(html_path)
                    if screenshots:
                        image_path = output / f"{page_name}.png"
                        page.screenshot(path=str(image_path), full_page=True)
                        record["screenshot_artifact"] = str(image_path)

                    if depth < max_depth:
                        for link in record.get("links", []):
                            href = link.get("href", "")
                            candidate = urldefrag(urljoin(page.url, href))[0]
                            if candidate and same_origin(start_url, candidate):
                                queue.append((candidate, depth + 1))
                except Exception as exc:
                    record["error"] = f"{type(exc).__name__}: {exc}"
                finally:
                    page.close()
                pages.append(record)

            result = {
                "start_url": start_url,
                "pages_visited": len(visited),
                "max_pages": max_pages,
                "max_depth": max_depth,
                "pages": pages,
            }
            index_path = output / "crawl.json"
            index_path.write_text(
                json.dumps(result, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            result["index_artifact"] = str(index_path)
            return result
        finally:
            context.close()
            browser.close()


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="secploit-browser",
        description="Bounded browser evidence collection for an isolated SecPloit range.",
    )
    subcommands = root.add_subparsers(dest="action", required=True)

    snapshot_parser = subcommands.add_parser("snapshot")
    snapshot_parser.add_argument("url")
    snapshot_parser.add_argument("--out", default="/workspace/browser/snapshot")
    snapshot_parser.add_argument("--timeout-ms", type=int, default=20000)

    crawl_parser = subcommands.add_parser("crawl")
    crawl_parser.add_argument("url")
    crawl_parser.add_argument("--out", default="/workspace/browser/crawl")
    crawl_parser.add_argument("--timeout-ms", type=int, default=20000)
    crawl_parser.add_argument("--max-pages", type=int, default=20)
    crawl_parser.add_argument("--max-depth", type=int, default=2)
    crawl_parser.add_argument("--screenshots", action="store_true")
    return root


def main() -> None:
    args = parser().parse_args()
    if args.action == "snapshot":
        result = snapshot(
            url=args.url,
            output=Path(args.out),
            timeout_ms=max(1000, min(args.timeout_ms, 120000)),
        )
    else:
        result = crawl(
            url=args.url,
            output=Path(args.out),
            timeout_ms=max(1000, min(args.timeout_ms, 120000)),
            max_pages=max(1, min(args.max_pages, 100)),
            max_depth=max(0, min(args.max_depth, 5)),
            screenshots=args.screenshots,
        )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
