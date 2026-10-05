from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import aiohttp


PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = PROJECT_ROOT / "config" / "tracker_url_list.txt"
OUTPUT_DIRECTORY = PROJECT_ROOT / "output"
REQUEST_TIMEOUT_SECONDS = 20
MAX_ATTEMPTS = 3
OUTPUT_FILES = {
    "comma": OUTPUT_DIRECTORY / "trackers_list_comma.txt",
    "newline": OUTPUT_DIRECTORY / "trackers_list_newline.txt",
    "blankline": OUTPUT_DIRECTORY / "trackers_list_blankline.txt",
}


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def is_valid_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def write_github_output(name: str, value: str) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    try:
        with Path(output_path).open("a", encoding="utf-8", newline="") as file:
            file.write(f"{name}={value}\n")
    except OSError as error:
        logging.warning("写入 GitHub Actions 输出失败：%s", error)


def emit_github_warning(url: str) -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    escaped_url = url.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"::warning title=Tracker 源获取失败::{escaped_url}")


def load_tracker_urls(config_path: Path) -> list[str]:
    if not config_path.is_file():
        raise FileNotFoundError(f"未找到 URL 配置文件：{config_path}")

    urls: list[str] = []
    for line_number, raw_line in enumerate(
        config_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        url = raw_line.strip()
        if not url or url.startswith("#"):
            continue
        if not is_valid_url(url):
            logging.warning(
                "忽略无效 URL（%s:%d）：%s", config_path, line_number, url
            )
            continue
        urls.append(url)

    if not urls:
        raise ValueError(f"配置文件中没有有效 URL：{config_path}")
    return list(dict.fromkeys(urls))


async def fetch_tracker_list(
    session: aiohttp.ClientSession, url: str
) -> tuple[str, str | None]:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            async with session.get(url, allow_redirects=True) as response:
                response.raise_for_status()
                logging.info("获取 Tracker 源成功：%s", url)
                return url, await response.text()
        except (aiohttp.ClientError, asyncio.TimeoutError) as error:
            if attempt == MAX_ATTEMPTS:
                logging.error(
                    "获取 Tracker 源失败，已重试 %d 次：%s；原因：%s",
                    MAX_ATTEMPTS,
                    url,
                    error,
                )
                emit_github_warning(url)
                return url, None
            delay_seconds = 2 ** (attempt - 1)
            logging.warning(
                "第 %d/%d 次获取失败：%s；原因：%s；%d 秒后重试。",
                attempt,
                MAX_ATTEMPTS,
                url,
                error,
                delay_seconds,
            )
            await asyncio.sleep(delay_seconds)
    return url, None


def deduplicate_trackers(contents: list[str]) -> list[str]:
    seen: set[str] = set()
    trackers: list[str] = []
    for content in contents:
        for raw_line in content.splitlines():
            tracker = raw_line.strip()
            if tracker and tracker not in seen:
                seen.add(tracker)
                trackers.append(tracker)
    return trackers


def write_text_atomically(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", text=True
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as file:
            file.write(content)
        temporary_path.replace(path)
    except OSError:
        temporary_path.unlink(missing_ok=True)
        raise


def write_outputs(trackers: list[str]) -> None:
    formats = {
        "comma": ",".join(trackers),
        "newline": "\n".join(trackers),
        "blankline": "\n\n".join(trackers),
    }
    for format_name, content in formats.items():
        output_path = OUTPUT_FILES[format_name]
        write_text_atomically(output_path, content)
        logging.info("已写入 %d 条 Tracker：%s", len(trackers), output_path)


async def update_tracker_lists() -> int:
    try:
        tracker_urls = load_tracker_urls(CONFIG_PATH)
    except (OSError, ValueError) as error:
        logging.error("读取 Tracker 配置失败：%s", error)
        return 2

    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
    headers = {"User-Agent": "tracker-list-updater/1.0"}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        results = await asyncio.gather(
            *(fetch_tracker_list(session, url) for url in tracker_urls)
        )

    failed_urls = [url for url, content in results if content is None]
    write_github_output("failed_count", str(len(failed_urls)))
    trackers = deduplicate_trackers(
        [content for _, content in results if content is not None]
    )
    if not trackers:
        logging.error("未获取到任何 Tracker 数据，已保留原有输出文件。")
        return 1

    try:
        write_outputs(trackers)
    except OSError as error:
        logging.error("写入 Tracker 输出文件失败：%s", error)
        return 1

    if failed_urls:
        logging.warning("任务完成，但有 %d 个源获取失败。", len(failed_urls))
    else:
        logging.info("任务完成，共生成 %d 条去重后的 Tracker。", len(trackers))
    return 0


def main() -> int:
    configure_logging()
    return asyncio.run(update_tracker_lists())


if __name__ == "__main__":
    raise SystemExit(main())
