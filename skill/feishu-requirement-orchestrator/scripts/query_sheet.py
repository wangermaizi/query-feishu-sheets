#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["tzdata>=2025.2"]
# ///
"""Inspect, query, and manage reusable profiles for Feishu Sheets and Bitable."""

from __future__ import annotations

import argparse
import calendar
import datetime as dt
import hashlib
import json
import mimetypes
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pathlib import Path
from typing import Any


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


SKILL_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path(
    os.environ.get(
        "FEISHU_ORCHESTRATOR_CONFIG_DIR",
        Path.home() / ".codex" / "feishu-requirement-orchestrator",
    )
).expanduser()
CREDENTIALS_FILE = CONFIG_DIR / "credentials.json"
PROFILES_FILE = CONFIG_DIR / "profiles.json"
API_BASE = "https://open.feishu.cn/open-apis"
DEFAULT_RANGE = "A1:AZ5000"
INSPECT_RANGE = "A1:AZ30"
PROFILE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$|^[a-z0-9]$")
URL_RE = re.compile(r"https?://[^\s\"'<>]+")
URL_KEYS = {"url", "tmp_url", "link", "download_url"}
TOKEN_KEYS = {
    "file_token",
    "filetoken",
    "image_token",
    "imagetoken",
    "image_key",
    "imagekey",
    "float_image_token",
    "floatimagetoken",
}
MEDIA_HEADER_MARKERS = ("截图", "图片", "附件", "image", "photo", "attachment")
OPERATORS = {"equals", "contains", "in", "not_empty", "date_between", "natural_week"}
CHINESE_NUMBERS = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六"}
CARD_ITEMS_PER_MESSAGE = 5
MAX_IMAGE_BYTES = 20 * 1024 * 1024


class FeishuSheetError(RuntimeError):
    pass


def emit(value: Any) -> None:
    json.dump(value, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def load_json(path: Path, root_key: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {root_key: {}}
    except json.JSONDecodeError as exc:
        raise FeishuSheetError(f"配置文件 JSON 无效: {path}: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get(root_key), dict):
        raise FeishuSheetError(f"配置文件缺少对象字段 {root_key}: {path}")
    return payload


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def request_json(
    method: str,
    path: str,
    *,
    access_token: str | None = None,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        f"{API_BASE}{path}", data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise FeishuSheetError(f"飞书接口 HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise FeishuSheetError(f"无法连接飞书接口: {exc.reason}") from exc
    if payload.get("code", 0) != 0:
        raise FeishuSheetError(
            f"飞书接口错误 {payload.get('code')}: {payload.get('msg', 'unknown error')}"
        )
    return payload


def download_media(url: str, access_token: str, requires_authorization: bool) -> tuple[bytes, str]:
    headers = {}
    if requires_authorization:
        headers["Authorization"] = f"Bearer {access_token}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            content_type = response.headers.get_content_type() or "application/octet-stream"
            data = response.read(MAX_IMAGE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise FeishuSheetError(f"下载飞书图片失败 HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise FeishuSheetError(f"下载飞书图片失败: {exc.reason}") from exc
    if len(data) > MAX_IMAGE_BYTES:
        raise FeishuSheetError("图片超过 20 MiB，无法作为群消息图片上传")
    return data, content_type


def upload_message_image(access_token: str, data: bytes, content_type: str) -> str:
    boundary = f"----CodexFeishu{uuid.uuid4().hex}"
    extension = mimetypes.guess_extension(content_type) or ".bin"
    chunks = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"image_type\"\r\n\r\nmessage\r\n".encode(),
        (
            f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"image\"; filename=\"image{extension}\"\r\n"
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode(),
        data,
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    request = urllib.request.Request(
        f"{API_BASE}/im/v1/images",
        data=b"".join(chunks),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise FeishuSheetError(f"上传飞书消息图片失败 HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise FeishuSheetError(f"上传飞书消息图片失败: {exc.reason}") from exc
    if payload.get("code", 0) != 0:
        raise FeishuSheetError(
            f"上传飞书消息图片失败 {payload.get('code')}: {payload.get('msg', 'unknown error')}"
        )
    image_key = payload.get("data", {}).get("image_key")
    if not image_key:
        raise FeishuSheetError("飞书图片上传响应中缺少 image_key")
    return str(image_key)


def get_credential(name: str) -> dict[str, str]:
    credentials = load_json(CREDENTIALS_FILE, "credentials")["credentials"]
    credential = credentials.get(name)
    if not isinstance(credential, dict):
        raise FeishuSheetError(f"找不到机器人凭证配置: {name}")
    app_id = credential.get("app_id")
    app_secret = credential.get("app_secret")
    if not isinstance(app_id, str) or not isinstance(app_secret, str):
        raise FeishuSheetError(f"机器人凭证配置不完整: {name}")
    return {"app_id": app_id, "app_secret": app_secret}


def get_access_token(credential_name: str) -> str:
    credential = get_credential(credential_name)
    payload = request_json(
        "POST",
        "/auth/v3/tenant_access_token/internal",
        body=credential,
    )
    token = payload.get("tenant_access_token")
    if not token:
        raise FeishuSheetError("飞书鉴权响应中缺少 tenant_access_token")
    return str(token)


def list_chats(access_token: str) -> list[dict[str, str]]:
    chats: list[dict[str, str]] = []
    page_token: str | None = None
    while True:
        query = {"page_size": "100"}
        if page_token:
            query["page_token"] = page_token
        payload = request_json(
            "GET",
            f"/im/v1/chats?{urllib.parse.urlencode(query)}",
            access_token=access_token,
        )
        data = payload.get("data", {})
        for item in data.get("items", []):
            chat_id = item.get("chat_id")
            name = item.get("name")
            if chat_id:
                chats.append({"chat_id": str(chat_id), "name": str(name or "")})
        if not data.get("has_more"):
            break
        page_token = data.get("page_token")
        if not page_token:
            break
    return chats


def resolve_chat(
    access_token: str,
    profile: dict[str, Any],
    chat_id: str | None,
    chat_name: str | None,
) -> dict[str, str]:
    delivery = profile.get("delivery", {})
    if delivery is None:
        delivery = {}
    if not isinstance(delivery, dict):
        raise FeishuSheetError("profile.delivery 必须是对象")
    selected_id = chat_id or delivery.get("chat_id")
    selected_name = chat_name or delivery.get("chat_name")
    if selected_id:
        return {"chat_id": str(selected_id), "name": str(selected_name or "")}
    if not selected_name:
        raise FeishuSheetError("未指定目标群，请提供 --chat-id、--chat-name 或配置 delivery")
    matches = [item for item in list_chats(access_token) if item["name"] == selected_name]
    if not matches:
        raise FeishuSheetError(f"机器人所在群中找不到目标群: {selected_name}")
    if len(matches) > 1:
        ids = ", ".join(item["chat_id"] for item in matches)
        raise FeishuSheetError(f"存在多个同名群“{selected_name}”，请改用 --chat-id: {ids}")
    return matches[0]


def document_type(url: str) -> str:
    path = urllib.parse.urlparse(url).path
    if re.search(r"/sheets/[^/?#]+", path):
        return "sheets"
    if re.search(r"/base/[^/?#]+", path):
        return "bitable"
    if re.search(r"/wiki/[^/?#]+", path):
        raise FeishuSheetError("Wiki 链接不能直接判断底层文档类型，请提供 /sheets/ 或 /base/ 直接链接")
    raise FeishuSheetError("无法识别飞书文档类型，仅支持 /sheets/ 电子表格和 /base/ 多维表格链接")


def profile_document_url(profile: dict[str, Any]) -> str:
    url = profile.get("document_url") or profile.get("spreadsheet_url")
    if not isinstance(url, str) or not url:
        raise FeishuSheetError("表格配置缺少 document_url")
    return url


def spreadsheet_parts(url: str) -> tuple[str, str | None]:
    parsed = urllib.parse.urlparse(url)
    match = re.search(r"/sheets/([^/?#]+)", parsed.path)
    if not match:
        raise FeishuSheetError("链接不是飞书电子表格 /sheets/ URL")
    query = urllib.parse.parse_qs(parsed.query)
    return match.group(1), query.get("sheet", [None])[0]


def bitable_parts(url: str) -> tuple[str, str | None, str | None]:
    parsed = urllib.parse.urlparse(url)
    match = re.search(r"/base/([^/?#]+)", parsed.path)
    if not match:
        raise FeishuSheetError("链接不是飞书多维表格 /base/ URL")
    query = urllib.parse.parse_qs(parsed.query)
    return (
        match.group(1),
        query.get("table", [None])[0],
        query.get("view", [None])[0],
    )


def bitable_record_url(url: str, table_id: str, record_id: str) -> str:
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    query["table"] = [table_id]
    query["record"] = [record_id]
    return urllib.parse.urlunparse(
        parsed._replace(query=urllib.parse.urlencode(query, doseq=True))
    )


def list_sheets(access_token: str, spreadsheet_token: str) -> list[dict[str, Any]]:
    payload = request_json(
        "GET",
        f"/sheets/v3/spreadsheets/{urllib.parse.quote(spreadsheet_token)}/sheets/query",
        access_token=access_token,
    )
    sheets = payload.get("data", {}).get("sheets", [])
    if not isinstance(sheets, list) or not sheets:
        raise FeishuSheetError("表格中未返回任何工作表")
    return sheets


def resolve_sheet(
    sheets: list[dict[str, Any]], requested: str | None, url_sheet_id: str | None
) -> tuple[str, str]:
    target = requested or url_sheet_id
    if target:
        for sheet in sheets:
            sheet_id = str(sheet.get("sheet_id", ""))
            title = str(sheet.get("title", ""))
            if target in {sheet_id, title}:
                return sheet_id, title
        available = ", ".join(str(item.get("title", "")) for item in sheets)
        raise FeishuSheetError(f"找不到工作表“{target}”。可用工作表: {available}")
    first = sheets[0]
    return str(first.get("sheet_id", "")), str(first.get("title", ""))


def read_values(
    access_token: str, spreadsheet_token: str, sheet_id: str, cell_range: str
) -> list[list[Any]]:
    qualified_range = f"{sheet_id}!{cell_range}"
    path = (
        f"/sheets/v2/spreadsheets/{urllib.parse.quote(spreadsheet_token)}/values/"
        f"{urllib.parse.quote(qualified_range, safe='!')}"
    )
    payload = request_json("GET", path, access_token=access_token)
    values = payload.get("data", {}).get("valueRange", {}).get("values", [])
    if not isinstance(values, list):
        raise FeishuSheetError("飞书表格响应中的 values 格式异常")
    last_used = 0
    for row in values:
        if not isinstance(row, list):
            continue
        for index, value in enumerate(row):
            if text_value(value):
                last_used = max(last_used, index + 1)
    return [row[:last_used] for row in values]


def bitable_paginated_items(
    access_token: str,
    path: str,
    *,
    page_size: int,
    extra_query: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page_token: str | None = None
    seen_tokens: set[str] = set()
    while True:
        query = {"page_size": str(page_size)}
        if extra_query:
            query.update(extra_query)
        if page_token:
            query["page_token"] = page_token
        payload = request_json(
            "GET",
            f"{path}?{urllib.parse.urlencode(query)}",
            access_token=access_token,
        )
        data = payload.get("data", {})
        page_items = data.get("items", [])
        if not isinstance(page_items, list):
            raise FeishuSheetError("飞书多维表格分页响应中的 items 格式异常")
        items.extend(item for item in page_items if isinstance(item, dict))
        if not data.get("has_more"):
            break
        next_token = data.get("page_token")
        if not next_token:
            raise FeishuSheetError("多维表格分页返回 has_more=true 但缺少 page_token")
        if str(next_token) in seen_tokens:
            raise FeishuSheetError("多维表格分页返回了重复 page_token")
        page_token = str(next_token)
        seen_tokens.add(page_token)
    return items


def get_bitable_app(access_token: str, app_token: str) -> dict[str, Any]:
    payload = request_json(
        "GET",
        f"/bitable/v1/apps/{urllib.parse.quote(app_token)}",
        access_token=access_token,
    )
    app = payload.get("data", {}).get("app", payload.get("data", {}))
    return app if isinstance(app, dict) else {}


def list_bitable_tables(access_token: str, app_token: str) -> list[dict[str, Any]]:
    tables = bitable_paginated_items(
        access_token,
        f"/bitable/v1/apps/{urllib.parse.quote(app_token)}/tables",
        page_size=100,
    )
    if not tables:
        raise FeishuSheetError("多维表格中未返回任何数据表")
    return tables


def resolve_bitable_table(
    tables: list[dict[str, Any]], requested: str | None, url_table_id: str | None
) -> tuple[str, str]:
    target = requested or url_table_id
    if target:
        for table in tables:
            table_id = str(table.get("table_id", ""))
            name = str(table.get("name", ""))
            if target in {table_id, name}:
                return table_id, name
        available = ", ".join(str(item.get("name", "")) for item in tables)
        raise FeishuSheetError(f"找不到数据表“{target}”。可用数据表: {available}")
    first = tables[0]
    return str(first.get("table_id", "")), str(first.get("name", ""))


def list_bitable_fields(
    access_token: str, app_token: str, table_id: str
) -> list[dict[str, Any]]:
    return bitable_paginated_items(
        access_token,
        (
            f"/bitable/v1/apps/{urllib.parse.quote(app_token)}/tables/"
            f"{urllib.parse.quote(table_id)}/fields"
        ),
        page_size=100,
    )


def list_bitable_records(
    access_token: str,
    app_token: str,
    table_id: str,
    view_id: str | None = None,
    field_names: list[str] | None = None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    page_token: str | None = None
    seen_tokens: set[str] = set()
    while True:
        query = {"page_size": "500", "user_id_type": "open_id"}
        if page_token:
            query["page_token"] = page_token
        body: dict[str, Any] = {}
        if view_id:
            body["view_id"] = view_id
        if field_names:
            body["field_names"] = field_names
        payload = request_json(
            "POST",
            (
                f"/bitable/v1/apps/{urllib.parse.quote(app_token)}/tables/"
                f"{urllib.parse.quote(table_id)}/records/search?"
                f"{urllib.parse.urlencode(query)}"
            ),
            access_token=access_token,
            body=body,
        )
        data = payload.get("data", {})
        page_items = data.get("items", [])
        if not isinstance(page_items, list):
            raise FeishuSheetError("飞书多维表格记录响应中的 items 格式异常")
        records.extend(item for item in page_items if isinstance(item, dict))
        if not data.get("has_more"):
            break
        next_token = data.get("page_token")
        if not next_token:
            raise FeishuSheetError("多维表格记录分页返回 has_more=true 但缺少 page_token")
        if str(next_token) in seen_tokens:
            raise FeishuSheetError("多维表格记录分页返回了重复 page_token")
        page_token = str(next_token)
        seen_tokens.add(page_token)
    return records


def text_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, str)):
        return str(value).strip()
    if isinstance(value, list):
        return " ".join(part for item in value if (part := text_value(item))).strip()
    if isinstance(value, dict):
        for key in ("text", "name", "value", "mention_name"):
            if key in value and (part := text_value(value[key])):
                return part
        return " ".join(
            part for item in value.values() if (part := text_value(item))
        ).strip()
    return str(value).strip()


def column_name(index: int) -> str:
    result = ""
    current = index + 1
    while current:
        current, remainder = divmod(current - 1, 26)
        result = chr(65 + remainder) + result
    return result


def headers_from_row(row: list[Any]) -> list[str]:
    bases = [text_value(value) or f"列{column_name(index)}" for index, value in enumerate(row)]
    totals = {base: bases.count(base) for base in set(bases)}
    seen: dict[str, int] = {}
    headers: list[str] = []
    for base in bases:
        count = seen.get(base, 0) + 1
        seen[base] = count
        headers.append(base if count == totals[base] else f"{base}#{count}")
    return headers


def find_header_row(rows: list[list[Any]], explicit: int | None = None) -> int:
    if explicit is not None:
        index = explicit - 1
        if index < 0 or index >= len(rows):
            raise FeishuSheetError(f"表头行超出读取范围: {explicit}")
        return index
    best_index = -1
    best_score = -1
    for index, row in enumerate(rows[:30]):
        values = [text_value(cell) for cell in row]
        nonempty = [value for value in values if value]
        if len(nonempty) < 2:
            continue
        score = len(nonempty) * 2 + len(set(nonempty))
        if score > best_score:
            best_index, best_score = index, score
    if best_index < 0:
        raise FeishuSheetError("无法自动识别表头行，请显式指定 --header-row")
    return best_index


def row_cell(row: list[Any], index: int) -> Any:
    return row[index] if index < len(row) else None


def screenshot_links(value: Any) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(url: str, requires_authorization: bool, token: str | None = None) -> None:
        if url in seen:
            return
        seen.add(url)
        result: dict[str, Any] = {
            "url": url,
            "requires_authorization": requires_authorization,
        }
        if token:
            result["file_token"] = token
        results.append(result)

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            for key, nested in item.items():
                lowered = str(key).lower()
                if lowered in URL_KEYS and isinstance(nested, str) and nested.startswith("http"):
                    add(nested, False)
                elif lowered in TOKEN_KEYS and isinstance(nested, str) and nested:
                    encoded = urllib.parse.quote(nested, safe="")
                    add(f"{API_BASE}/drive/v1/medias/{encoded}/download", True, nested)
                else:
                    walk(nested)
        elif isinstance(item, list):
            for nested in item:
                walk(nested)
        elif isinstance(item, str):
            for match in URL_RE.findall(item):
                add(match.rstrip("),]"), False)

    walk(value)
    return results


def output_value(header: str, value: Any) -> Any:
    lowered = header.lower()
    links = screenshot_links(value)
    if links and (any(marker in lowered for marker in MEDIA_HEADER_MARKERS) or has_token(value)):
        return links
    return text_value(value)


def output_bitable_value(field_name: str, value: Any) -> Any:
    if isinstance(value, list) and any(
        isinstance(item, dict) and item.get("file_token") for item in value
    ):
        attachments: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, dict) or not item.get("file_token"):
                continue
            file_token = str(item["file_token"])
            if file_token in seen:
                continue
            seen.add(file_token)
            url = item.get("url")
            if not isinstance(url, str) or not url:
                continue
            media_type = str(item.get("type") or "")
            attachments.append(
                {
                    "url": url,
                    "requires_authorization": True,
                    "file_token": file_token,
                    "name": str(item.get("name") or field_name),
                    "type": media_type,
                    "size": item.get("size"),
                    "is_image": not media_type or media_type.startswith("image/"),
                }
            )
        if attachments:
            return attachments
    return output_value(field_name, value)


def has_token(value: Any) -> bool:
    if isinstance(value, dict):
        return any(str(key).lower() in TOKEN_KEYS or has_token(item) for key, item in value.items())
    if isinstance(value, list):
        return any(has_token(item) for item in value)
    return False


def natural_week_bounds(day: dt.date) -> tuple[dt.date, dt.date]:
    start = day - dt.timedelta(days=day.weekday())
    return start, start + dt.timedelta(days=6)


def schedule_label(day: dt.date) -> str:
    first_weekday = calendar.monthrange(day.year, day.month)[0]
    week_number = (day.day + first_weekday - 1) // 7 + 1
    number = CHINESE_NUMBERS.get(week_number, str(week_number))
    return f"{day:%Y%m}-第{number}周"


def schedule_labels(start: dt.date, end: dt.date) -> list[str]:
    labels: list[str] = []
    current = start
    while current <= end:
        label = schedule_label(current)
        if label not in labels:
            labels.append(label)
        current += dt.timedelta(days=1)
    return labels


def parse_date(value: str, option: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise FeishuSheetError(f"{option} 必须使用 YYYY-MM-DD 格式") from exc


def parse_cell_date(value: Any, time_zone: str = "Asia/Shanghai") -> dt.date | None:
    try:
        zone = ZoneInfo(time_zone)
    except ZoneInfoNotFoundError:
        zone = dt.timezone.utc
    if isinstance(value, str) and re.fullmatch(r"\d+(?:\.\d+)?", value.strip()):
        value = float(value)
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 100_000_000_000:
            return dt.datetime.fromtimestamp(number / 1000, tz=zone).date()
        if number > 1_000_000_000:
            return dt.datetime.fromtimestamp(number, tz=zone).date()
        if 1 <= number <= 100_000:
            return dt.date(1899, 12, 30) + dt.timedelta(days=number)
    text = text_value(value)
    for candidate in (text, text.replace("/", "-"), text[:10].replace("/", "-")):
        try:
            return dt.date.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def resolve_date_range(start_text: str | None, end_text: str | None) -> tuple[dt.date, dt.date]:
    today = dt.date.today()
    if not start_text and not end_text:
        return natural_week_bounds(today)
    start = parse_date(start_text or end_text or "", "--start-date")
    end = parse_date(end_text or start_text or "", "--end-date")
    if start > end:
        raise FeishuSheetError("开始日期不能晚于结束日期")
    return start, end


def split_assignment(value: str, option: str) -> tuple[str, str]:
    if "=" not in value:
        raise FeishuSheetError(f"{option} 必须使用 列名=值 格式")
    column, assigned = value.split("=", 1)
    if not column.strip():
        raise FeishuSheetError(f"{option} 的列名不能为空")
    return column.strip(), assigned.strip()


def validate_filter(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise FeishuSheetError("filters 中的每一项必须是对象")
    column = item.get("column")
    operator = item.get("operator")
    if not isinstance(column, str) or not column:
        raise FeishuSheetError("筛选条件缺少 column")
    if operator not in OPERATORS:
        raise FeishuSheetError(f"不支持的筛选操作符: {operator}")
    return dict(item)


def get_profile(name: str) -> dict[str, Any]:
    profiles = load_json(PROFILES_FILE, "profiles")["profiles"]
    profile = profiles.get(name)
    if not isinstance(profile, dict):
        raise FeishuSheetError(f"找不到表格配置: {name}")
    return dict(profile)


def load_spec(path: str) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FeishuSheetError(f"找不到配置草稿文件: {path}") from exc
    except json.JSONDecodeError as exc:
        raise FeishuSheetError(f"配置草稿 JSON 无效: {exc}") from exc
    if not isinstance(payload, dict):
        raise FeishuSheetError("配置草稿必须是 JSON 对象")
    return payload


def validate_profile(profile: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(profile.get("credential"), str) or not profile["credential"]:
        raise FeishuSheetError("表格配置缺少字段: credential")
    document_type(profile_document_url(profile))
    validated = dict(profile)
    aliases = profile.get("aliases", [])
    if not isinstance(aliases, list) or not all(
        isinstance(item, str) and item.strip() for item in aliases
    ):
        raise FeishuSheetError("aliases 必须为非空字符串数组")
    validated["aliases"] = list(dict.fromkeys(item.strip() for item in aliases))
    description = profile.get("description")
    if description is not None and (not isinstance(description, str) or not description.strip()):
        raise FeishuSheetError("description 必须为非空字符串")
    filters = profile.get("filters", [])
    if not isinstance(filters, list):
        raise FeishuSheetError("filters 必须是数组")
    validated["filters"] = [validate_filter(item) for item in filters]
    allow_unfiltered = profile.get("allow_unfiltered", False)
    if not isinstance(allow_unfiltered, bool):
        raise FeishuSheetError("allow_unfiltered 必须为布尔值")
    validated["allow_unfiltered"] = allow_unfiltered
    output_columns = profile.get("output_columns", [])
    if not isinstance(output_columns, list) or not all(isinstance(item, str) for item in output_columns):
        raise FeishuSheetError("output_columns 必须是字符串数组")
    delivery = profile.get("delivery")
    if delivery is not None and not isinstance(delivery, dict):
        raise FeishuSheetError("delivery 必须是对象")
    return validated


def validate_filter_policy(profile: dict[str, Any]) -> None:
    if not profile.get("filters") and profile.get("allow_unfiltered") is not True:
        raise FeishuSheetError(
            "查询缺少筛选条件；请先询问用户如何过滤，或在用户明确确认整表查询后设置 allow_unfiltered=true"
        )


def query_spec(args: argparse.Namespace) -> tuple[str | None, dict[str, Any]]:
    if args.profile:
        return args.profile, validate_profile(get_profile(args.profile))
    if args.spec:
        draft = load_spec(args.spec)
        draft.pop("profile_id", None)
        return None, validate_profile(draft)
    if not args.url or not args.credential:
        raise FeishuSheetError("临时查询必须同时提供 --url 和 --credential")
    return None, validate_profile(
        {
            "credential": args.credential,
            "document_url": args.url,
            "default_sheet": args.sheet,
            "default_table": args.table,
            "range": args.cell_range or DEFAULT_RANGE,
            "filters": [],
            "output_columns": [],
        }
    )


def apply_cli_overrides(profile: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    result = dict(profile)
    if args.url:
        result["document_url"] = args.url
        result.pop("spreadsheet_url", None)
    if args.credential:
        result["credential"] = args.credential
    if args.sheet:
        result["default_sheet"] = args.sheet
    if args.table:
        result["default_table"] = args.table
    if args.view:
        result["view_id"] = args.view
    if args.cell_range:
        result["range"] = args.cell_range
    if args.header_row:
        result["header_row"] = args.header_row
    if args.select:
        result["output_columns"] = [item.strip() for item in args.select.split(",") if item.strip()]

    filters = [dict(item) for item in result.get("filters", [])]
    for assignment in args.set_values:
        column, value = split_assignment(assignment, "--set")
        matches = [item for item in filters if item.get("column") == column]
        if not matches:
            raise FeishuSheetError(f"--set 找不到配置中的筛选列: {column}")
        for item in matches:
            item["value"] = value
    for option_values, operator, option in (
        (args.contains, "contains", "--contains"),
        (args.equals, "equals", "--equals"),
    ):
        for assignment in option_values:
            column, value = split_assignment(assignment, option)
            filters = [item for item in filters if item.get("column") != column]
            filters.append({"column": column, "operator": operator, "value": value})
    result["filters"] = filters
    return validate_profile(result)


def resolve_filters(
    filters: list[dict[str, Any]], start_text: str | None, end_text: str | None
) -> list[dict[str, Any]]:
    has_date_filter = any(item["operator"] in {"natural_week", "date_between"} for item in filters)
    if (start_text or end_text) and not has_date_filter:
        raise FeishuSheetError("指定了日期范围，但配置中没有 natural_week 或 date_between 筛选")
    resolved: list[dict[str, Any]] = []
    for item in filters:
        current = dict(item)
        if item["operator"] in {"natural_week", "date_between"}:
            start, end = resolve_date_range(start_text, end_text)
            current["start_date"] = start.isoformat()
            current["end_date"] = end.isoformat()
            if item["operator"] == "natural_week":
                current["labels"] = schedule_labels(start, end)
        resolved.append(current)
    return resolved


def candidate_texts(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (bool, int, float, str)):
        text = text_value(value)
        return [text] if text else []
    if isinstance(value, list):
        return list(dict.fromkeys(text for item in value for text in candidate_texts(item)))
    if isinstance(value, dict):
        candidates = []
        for key in ("text", "name", "value", "mention_name", "id", "email", "en_name"):
            if key in value:
                candidates.extend(candidate_texts(value[key]))
        if candidates:
            return list(dict.fromkeys(candidates))
        return list(
            dict.fromkeys(text for item in value.values() for text in candidate_texts(item))
        )
    return [str(value)]


def filter_matches(
    value: Any, condition: dict[str, Any], time_zone: str = "Asia/Shanghai"
) -> bool:
    text = text_value(value)
    candidates = candidate_texts(value)
    operator = condition["operator"]
    expected = condition.get("value", "")
    if operator == "equals":
        return str(expected) in candidates or text == str(expected)
    if operator == "contains":
        return str(expected) in text or any(str(expected) in item for item in candidates)
    if operator == "in":
        values = expected if isinstance(expected, list) else str(expected).split(",")
        expected_values = {str(item).strip() for item in values}
        return bool(expected_values.intersection(candidates)) or text in expected_values
    if operator == "not_empty":
        return bool(text)
    if operator == "natural_week":
        return any(label in text for label in condition.get("labels", []))
    if operator == "date_between":
        parsed = parse_cell_date(value, time_zone)
        if parsed is None:
            return False
        start = dt.date.fromisoformat(condition["start_date"])
        end = dt.date.fromisoformat(condition["end_date"])
        return start <= parsed <= end
    raise FeishuSheetError(f"不支持的筛选操作符: {operator}")


def execute_sheets_query(
    profile_name: str | None,
    profile: dict[str, Any],
    filters: list[dict[str, Any]],
    access_token: str,
    document_url: str,
) -> dict[str, Any]:
    spreadsheet_token, url_sheet_id = spreadsheet_parts(document_url)
    sheets = list_sheets(access_token, spreadsheet_token)
    sheet_id, sheet_title = resolve_sheet(sheets, profile.get("default_sheet"), url_sheet_id)
    rows = read_values(
        access_token,
        spreadsheet_token,
        sheet_id,
        profile.get("range", DEFAULT_RANGE),
    )
    header_row = find_header_row(rows, profile.get("header_row"))
    headers = headers_from_row(rows[header_row])
    column_indexes = {header: index for index, header in enumerate(headers)}

    referenced_columns = [item["column"] for item in filters]
    selected_columns = profile.get("output_columns") or headers
    missing = [name for name in referenced_columns + selected_columns if name not in column_indexes]
    if missing:
        raise FeishuSheetError(f"工作表缺少配置列: {', '.join(dict.fromkeys(missing))}")

    items: list[dict[str, Any]] = []
    for row_number, row in enumerate(rows[header_row + 1 :], start=header_row + 2):
        if not any(text_value(cell) for cell in row):
            continue
        if not all(filter_matches(row_cell(row, column_indexes[item["column"]]), item) for item in filters):
            continue
        result: dict[str, Any] = {"row_number": row_number}
        for header in selected_columns:
            result[header] = output_value(header, row_cell(row, column_indexes[header]))
        items.append(result)

    return {
        "query": {
            "profile": profile_name,
            "source_type": "sheets",
            "document_url": document_url,
            "sheet": sheet_title,
            "sheet_id": sheet_id,
            "filters": filters,
            "output_columns": selected_columns,
        },
        "count": len(items),
        "items": items,
    }


def execute_bitable_query(
    profile_name: str | None,
    profile: dict[str, Any],
    filters: list[dict[str, Any]],
    access_token: str,
    document_url: str,
) -> dict[str, Any]:
    app_token, url_table_id, url_view_id = bitable_parts(document_url)
    app = get_bitable_app(access_token, app_token)
    time_zone = str(app.get("time_zone") or "Asia/Shanghai")
    tables = list_bitable_tables(access_token, app_token)
    table_id, table_name = resolve_bitable_table(
        tables, profile.get("default_table"), url_table_id
    )
    fields = list_bitable_fields(access_token, app_token, table_id)
    field_names = [str(item.get("field_name", "")) for item in fields if item.get("field_name")]
    referenced_columns = [item["column"] for item in filters]
    selected_columns = profile.get("output_columns") or field_names
    missing = [name for name in referenced_columns + selected_columns if name not in field_names]
    if missing:
        raise FeishuSheetError(f"数据表缺少配置字段: {', '.join(dict.fromkeys(missing))}")

    records = list_bitable_records(
        access_token,
        app_token,
        table_id,
        profile.get("view_id") or profile.get("default_view") or url_view_id,
        list(dict.fromkeys(referenced_columns + selected_columns)),
    )
    items: list[dict[str, Any]] = []
    for record in records:
        record_fields = record.get("fields", {})
        if not isinstance(record_fields, dict):
            continue
        if not all(
            filter_matches(record_fields.get(item["column"]), item, time_zone)
            for item in filters
        ):
            continue
        record_id = str(record.get("record_id", ""))
        result: dict[str, Any] = {
            "record_id": record_id,
            "record_url": bitable_record_url(document_url, table_id, record_id),
        }
        for field_name in selected_columns:
            result[field_name] = output_bitable_value(
                field_name, record_fields.get(field_name)
            )
        items.append(result)

    return {
        "query": {
            "profile": profile_name,
            "source_type": "bitable",
            "document_url": document_url,
            "table": table_name,
            "table_id": table_id,
            "view_id": profile.get("view_id") or profile.get("default_view") or url_view_id,
            "time_zone": time_zone,
            "filters": filters,
            "output_columns": selected_columns,
        },
        "count": len(items),
        "items": items,
    }


def execute_query(profile_name: str | None, profile: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    profile = apply_cli_overrides(profile, args)
    validate_filter_policy(profile)
    filters = resolve_filters(profile.get("filters", []), args.start_date, args.end_date)
    access_token = get_access_token(profile["credential"])
    document_url = profile_document_url(profile)
    source_type = document_type(document_url)
    if source_type == "sheets":
        return execute_sheets_query(profile_name, profile, filters, access_token, document_url)
    return execute_bitable_query(profile_name, profile, filters, access_token, document_url)


def query_result_hash(result: dict[str, Any]) -> str:
    def stable(value: Any) -> Any:
        if is_media_value(value):
            token_items = [item for item in value if item.get("file_token")]
            if token_items:
                return [{"file_token": str(item["file_token"])} for item in token_items]
            return [{"url": str(item["url"])} for item in value]
        if isinstance(value, dict):
            return {key: stable(item) for key, item in value.items()}
        if isinstance(value, list):
            return [stable(item) for item in value]
        return value

    encoded = json.dumps(
        stable(result), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def is_media_value(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, dict) and isinstance(item.get("url"), str) for item in value)
    )


def display_text(value: Any, limit: int = 2000) -> str:
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False)
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def item_markdown(item: dict[str, Any]) -> str:
    if item.get("record_id"):
        lines = [f"**记录 ID**：{item['record_id']}"]
    else:
        lines = [f"**表格行号**：{item.get('row_number', '')}"]
    for key, value in item.items():
        if key in {"row_number", "record_id"} or is_media_value(value):
            continue
        shown = display_text(value)
        lines.append(f"**{key}**：{shown if shown else '（空）'}")
    media_count = sum(len(selected_media(value)) for value in item.values() if is_media_value(value))
    if media_count:
        lines.append(f"**图片**：{media_count} 张（发送时上传）")
    attachment_names = [
        str(media.get("name") or "附件")
        for value in item.values()
        if is_media_value(value)
        for media in value
        if media.get("is_image") is False
    ]
    if attachment_names:
        lines.append(f"**其他附件**：{'、'.join(attachment_names)}（请在原表查看）")
    return "\n".join(lines)


def selected_media(value: Any) -> list[dict[str, Any]]:
    if not is_media_value(value):
        return []
    image_items = [item for item in value if item.get("is_image") is not False]
    with_tokens = [item for item in image_items if item.get("file_token")]
    candidates = with_tokens or image_items
    seen: set[str] = set()
    selected: list[dict[str, Any]] = []
    for item in candidates:
        identity = str(item.get("file_token") or item.get("url"))
        if identity in seen:
            continue
        seen.add(identity)
        selected.append(item)
    return selected


def card_title(profile: dict[str, Any], result: dict[str, Any]) -> str:
    delivery = profile.get("delivery") or {}
    if isinstance(delivery, dict) and delivery.get("title"):
        return str(delivery["title"])[:80]
    base = str(profile.get("display_name") or result.get("query", {}).get("sheet") or "飞书表格查询")
    parts = [base]
    for condition in result.get("query", {}).get("filters", []):
        column = condition.get("column")
        operator = condition.get("operator")
        if not column:
            continue
        if operator in {"equals", "contains", "in"} and condition.get("value") not in (None, ""):
            value = condition["value"]
            if isinstance(value, list):
                value = "、".join(str(item) for item in value)
            parts.append(f"{column}：{value}")
        elif operator == "natural_week" and condition.get("labels"):
            parts.append(f"{column}：{'、'.join(condition['labels'])}")
        elif operator == "date_between" and condition.get("start_date"):
            parts.append(f"{column}：{condition['start_date']} 至 {condition['end_date']}")
    return "｜".join(parts)[:80]


def fallback_media_url(value: Any) -> str | None:
    if not is_media_value(value):
        return None
    for item in value:
        if not item.get("requires_authorization") and item.get("url"):
            return str(item["url"])
    return None


def preview_cards(profile: dict[str, Any], result: dict[str, Any]) -> list[dict[str, Any]]:
    items = result.get("items", [])
    if not items:
        return [{"title": card_title(profile, result), "items": ["未查询到符合条件的记录"]}]
    cards = []
    for offset in range(0, len(items), CARD_ITEMS_PER_MESSAGE):
        chunk = items[offset : offset + CARD_ITEMS_PER_MESSAGE]
        cards.append(
            {
                "title": card_title(profile, result),
                "items": [item_markdown(item) for item in chunk],
            }
        )
    return cards


def build_message_cards(
    access_token: str, profile: dict[str, Any], result: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[str]]:
    items = result.get("items", [])
    warnings: list[str] = []
    title = card_title(profile, result)
    chunks = [items[index : index + CARD_ITEMS_PER_MESSAGE] for index in range(0, len(items), CARD_ITEMS_PER_MESSAGE)]
    if not chunks:
        chunks = [[]]
    cards: list[dict[str, Any]] = []
    for page, chunk in enumerate(chunks, start=1):
        elements: list[dict[str, Any]] = [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"共 **{len(items)}** 条记录",
                },
            }
        ]
        if not chunk:
            elements.append(
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": "未查询到符合条件的记录"},
                }
            )
        for item_index, item in enumerate(chunk):
            if item_index:
                elements.append({"tag": "hr"})
            elements.append(
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": item_markdown(item)},
                }
            )
            for field, value in item.items():
                for media in selected_media(value):
                    try:
                        data, content_type = download_media(
                            str(media["url"]),
                            access_token,
                            bool(media.get("requires_authorization")),
                        )
                        image_key = upload_message_image(access_token, data, content_type)
                        elements.append(
                            {
                                "tag": "img",
                                "img_key": image_key,
                                "alt": {"tag": "plain_text", "content": str(field)},
                            }
                        )
                    except FeishuSheetError as exc:
                        warnings.append(f"第 {item.get('row_number')} 行 {field}: {exc}")
                        fallback_url = fallback_media_url(value)
                        fallback_content = (
                            f"[{field}：查看图片]({fallback_url})"
                            if fallback_url
                            else f"{field}：图片上传失败，请为应用开通 im:resource:upload 权限"
                        )
                        elements.append(
                            {
                                "tag": "div",
                                "text": {"tag": "lark_md", "content": fallback_content},
                            }
                        )
        page_title = title if len(chunks) == 1 else f"{title}（{page}/{len(chunks)}）"
        cards.append(
            {
                "config": {"wide_screen_mode": True},
                "header": {
                    "template": "blue",
                    "title": {"tag": "plain_text", "content": page_title},
                },
                "elements": elements,
            }
        )
    return cards, warnings


def send_card(access_token: str, chat_id: str, card: dict[str, Any]) -> str:
    payload = request_json(
        "POST",
        f"/im/v1/messages?{urllib.parse.urlencode({'receive_id_type': 'chat_id'})}",
        access_token=access_token,
        body={
            "receive_id": chat_id,
            "msg_type": "interactive",
            "content": json.dumps(card, ensure_ascii=False),
        },
    )
    message_id = payload.get("data", {}).get("message_id")
    if not message_id:
        raise FeishuSheetError("飞书发送消息响应中缺少 message_id")
    return str(message_id)


def delivery_context(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], str, dict[str, str]]:
    profile_name, profile = query_spec(args)
    result = execute_query(profile_name, profile, args)
    effective_profile = apply_cli_overrides(profile, args)
    access_token = get_access_token(effective_profile["credential"])
    chat = resolve_chat(access_token, effective_profile, args.chat_id, args.chat_name)
    return effective_profile, result, access_token, chat


def command_delivery(args: argparse.Namespace) -> dict[str, Any]:
    profile, result, access_token, chat = delivery_context(args)
    result_hash = query_result_hash(result)
    if args.delivery_command == "preview":
        cards = preview_cards(profile, result)
        return {
            "delivery_preview": {
                "target_chat": chat,
                "result_hash": result_hash,
                "message_count": len(cards),
                "cards": cards,
            },
            "query_result": result,
        }
    if args.delivery_command == "publish":
        if not args.confirm:
            raise FeishuSheetError("发布群消息必须显式提供 --confirm")
        if args.expected_hash != result_hash:
            row_numbers = [item.get("row_number") for item in result.get("items", [])]
            raise FeishuSheetError(
                f"查询结果已变化或哈希不匹配；当前哈希为 {result_hash}，"
                f"当前记录数为 {result.get('count', 0)}，行号为 {row_numbers}；"
                "请重新执行完整预览、向用户展示变化并再次确认"
            )
        cards, warnings = build_message_cards(access_token, profile, result)
        message_ids: list[str] = []
        try:
            for card in cards:
                message_ids.append(send_card(access_token, chat["chat_id"], card))
        except FeishuSheetError as exc:
            if message_ids:
                raise FeishuSheetError(
                    f"群消息仅部分发送，已发送 message_id: {', '.join(message_ids)}；后续失败: {exc}"
                ) from exc
            raise
        return {
            "published": True,
            "target_chat": chat,
            "result_hash": result_hash,
            "record_count": result.get("count", 0),
            "message_ids": message_ids,
            "warnings": warnings,
        }
    raise FeishuSheetError("未知 delivery 命令")


def inspect_sheets(args: argparse.Namespace, access_token: str) -> dict[str, Any]:
    spreadsheet_token, url_sheet_id = spreadsheet_parts(args.url)
    sheets = list_sheets(access_token, spreadsheet_token)
    sheet_list = [
        {"sheet_id": str(item.get("sheet_id", "")), "title": str(item.get("title", ""))}
        for item in sheets
    ]
    sheet_id, sheet_title = resolve_sheet(sheets, args.sheet, url_sheet_id)
    rows = read_values(access_token, spreadsheet_token, sheet_id, args.cell_range)
    header_row = find_header_row(rows, args.header_row)
    headers = headers_from_row(rows[header_row])
    samples = []
    for row_number, row in enumerate(rows[header_row + 1 :], start=header_row + 2):
        if not any(text_value(cell) for cell in row):
            continue
        samples.append(
            {
                "row_number": row_number,
                "values": {
                    header: output_value(header, row_cell(row, index))
                    for index, header in enumerate(headers)
                },
            }
        )
        if len(samples) >= args.sample_rows:
            break
    return {
        "source_type": "sheets",
        "document_url": args.url,
        "sheets": sheet_list,
        "selected_sheet": {"sheet_id": sheet_id, "title": sheet_title},
        "header_row": header_row + 1,
        "headers": headers,
        "sample_rows": samples,
    }


def inspect_bitable(args: argparse.Namespace, access_token: str) -> dict[str, Any]:
    app_token, url_table_id, url_view_id = bitable_parts(args.url)
    app = get_bitable_app(access_token, app_token)
    tables = list_bitable_tables(access_token, app_token)
    table_list = [
        {"table_id": str(item.get("table_id", "")), "name": str(item.get("name", ""))}
        for item in tables
    ]
    table_id, table_name = resolve_bitable_table(tables, args.table, url_table_id)
    fields = list_bitable_fields(access_token, app_token, table_id)
    field_list = [
        {
            "field_id": str(item.get("field_id", "")),
            "field_name": str(item.get("field_name", "")),
            "type": item.get("type"),
            "is_primary": bool(item.get("is_primary")),
        }
        for item in fields
    ]
    selected_view_id = args.view or url_view_id
    records = list_bitable_records(access_token, app_token, table_id, selected_view_id)
    samples = []
    for record in records[: args.sample_rows]:
        record_fields = record.get("fields", {})
        if not isinstance(record_fields, dict):
            record_fields = {}
        samples.append(
            {
                "record_id": str(record.get("record_id", "")),
                "fields": {
                    field["field_name"]: output_bitable_value(
                        field["field_name"], record_fields.get(field["field_name"])
                    )
                    for field in field_list
                    if field["field_name"]
                },
            }
        )
    return {
        "source_type": "bitable",
        "document_url": args.url,
        "app": {
            "app_token": app_token,
            "name": app.get("name"),
            "time_zone": app.get("time_zone"),
            "is_advanced": app.get("is_advanced"),
        },
        "tables": table_list,
        "selected_table": {"table_id": table_id, "name": table_name},
        "view_id": selected_view_id,
        "fields": field_list,
        "sample_records": samples,
    }


def command_inspect(args: argparse.Namespace) -> dict[str, Any]:
    access_token = get_access_token(args.credential)
    source_type = document_type(args.url)
    if source_type == "sheets":
        return inspect_sheets(args, access_token)
    return inspect_bitable(args, access_token)


def command_chat(args: argparse.Namespace) -> dict[str, Any]:
    access_token = get_access_token(args.credential)
    return {"credential": args.credential, "chats": list_chats(access_token)}


def command_profile(args: argparse.Namespace) -> dict[str, Any]:
    payload = load_json(PROFILES_FILE, "profiles")
    profiles = payload["profiles"]
    if args.profile_command == "list":
        return {
            "profiles": [
                {
                    "profile_id": name,
                    "display_name": value.get("display_name", name),
                    "aliases": value.get("aliases", []),
                    "description": value.get("description", ""),
                    "filter_count": len(value.get("filters", [])),
                    "allow_unfiltered": value.get("allow_unfiltered", False),
                    "source_type": document_type(profile_document_url(value)),
                    "default_sheet": value.get("default_sheet"),
                    "default_table": value.get("default_table"),
                    "default_view": value.get("default_view") or value.get("view_id"),
                    "credential": value.get("credential"),
                    "document_url": profile_document_url(value),
                }
                for name, value in sorted(profiles.items())
            ]
        }
    if args.profile_command == "show":
        return {"profile_id": args.name, "profile": get_profile(args.name)}
    if args.profile_command == "save":
        draft = load_spec(args.spec)
        profile_id = draft.pop("profile_id", None)
        if not isinstance(profile_id, str) or not PROFILE_ID_RE.fullmatch(profile_id):
            raise FeishuSheetError("profile_id 必须是 1-64 位小写字母、数字或连字符")
        profile = validate_profile(draft)
        validate_filter_policy(profile)
        get_credential(profile["credential"])
        if profile_id in profiles and not args.replace:
            raise FeishuSheetError(f"配置已存在: {profile_id}；确认覆盖后使用 --replace")
        profiles[profile_id] = profile
        atomic_write_json(PROFILES_FILE, payload)
        return {"saved": True, "profile_id": profile_id, "profile": profile}
    if args.profile_command == "delete":
        if not args.yes:
            raise FeishuSheetError("删除配置必须显式提供 --yes")
        if args.name not in profiles:
            raise FeishuSheetError(f"找不到表格配置: {args.name}")
        del profiles[args.name]
        atomic_write_json(PROFILES_FILE, payload)
        return {"deleted": True, "profile_id": args.name}
    raise FeishuSheetError("未知 profile 命令")


def validate_credential_draft(draft: dict[str, Any]) -> tuple[str, dict[str, str]]:
    credential_id = draft.get("credential_id")
    app_id = draft.get("app_id")
    app_secret = draft.get("app_secret")
    if not isinstance(credential_id, str) or not PROFILE_ID_RE.fullmatch(credential_id):
        raise FeishuSheetError("credential_id 必须是 1-64 位小写字母、数字或连字符")
    if not isinstance(app_id, str) or not app_id.startswith("cli_"):
        raise FeishuSheetError("凭证草稿缺少有效 app_id")
    if not isinstance(app_secret, str) or not app_secret:
        raise FeishuSheetError("凭证草稿缺少 app_secret")
    return credential_id, {"app_id": app_id, "app_secret": app_secret}


def test_inline_credential(credential: dict[str, str]) -> dict[str, Any]:
    payload = request_json(
        "POST", "/auth/v3/tenant_access_token/internal", body=credential
    )
    token = payload.get("tenant_access_token")
    if not token:
        raise FeishuSheetError("飞书鉴权响应中缺少 tenant_access_token")
    return {
        "valid": True,
        "app_id": credential["app_id"],
    }


def command_credential(args: argparse.Namespace) -> dict[str, Any]:
    payload = load_json(CREDENTIALS_FILE, "credentials")
    credentials = payload["credentials"]
    if args.credential_command == "list":
        return {
            "credentials": [
                {"credential_id": name, "app_id": value.get("app_id")}
                for name, value in sorted(credentials.items())
            ]
        }
    if args.credential_command == "test":
        _, credential = validate_credential_draft(load_spec(args.spec))
        return test_inline_credential(credential)
    if args.credential_command == "save":
        credential_id, credential = validate_credential_draft(load_spec(args.spec))
        if credential_id in credentials and not args.replace:
            raise FeishuSheetError(f"凭证已存在: {credential_id}；确认覆盖后使用 --replace")
        credentials[credential_id] = credential
        atomic_write_json(CREDENTIALS_FILE, payload)
        return {"saved": True, "credential_id": credential_id, "app_id": credential["app_id"]}
    if args.credential_command == "delete":
        if not args.yes:
            raise FeishuSheetError("删除凭证必须显式提供 --yes")
        profiles = load_json(PROFILES_FILE, "profiles")["profiles"]
        used_by = [name for name, value in profiles.items() if value.get("credential") == args.name]
        if used_by:
            raise FeishuSheetError(f"凭证仍被配置使用: {', '.join(used_by)}")
        if args.name not in credentials:
            raise FeishuSheetError(f"找不到机器人凭证配置: {args.name}")
        del credentials[args.name]
        atomic_write_json(CREDENTIALS_FILE, payload)
        return {"deleted": True, "credential_id": args.name}
    raise FeishuSheetError("未知 credential 命令")


def add_query_options(parser: argparse.ArgumentParser) -> None:
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--profile", help="已保存的 profile_id")
    source.add_argument("--spec", help="未保存的 profile JSON 草稿路径")
    parser.add_argument("--url", help="临时查询或覆盖配置中的飞书文档链接")
    parser.add_argument("--credential", help="临时查询或覆盖配置中的应用凭证名称")
    parser.add_argument("--sheet", help="工作表标题或 sheet ID")
    parser.add_argument("--table", help="多维表格的数据表名称或 table ID")
    parser.add_argument("--view", help="多维表格 view ID")
    parser.add_argument("--range", dest="cell_range", help="读取范围，例如 A1:N5000")
    parser.add_argument("--header-row", type=int, help="1-based 表头行")
    parser.add_argument("--select", help="逗号分隔的输出列")
    parser.add_argument("--set", dest="set_values", action="append", default=[], help="覆盖已有筛选值，列名=值")
    parser.add_argument("--contains", action="append", default=[], help="包含筛选，列名=值")
    parser.add_argument("--equals", action="append", default=[], help="相等筛选，列名=值")
    parser.add_argument("--start-date", help="YYYY-MM-DD，包含当天")
    parser.add_argument("--end-date", help="YYYY-MM-DD，包含当天")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    inspect_parser = commands.add_parser("inspect", help="自动检查电子表格或多维表格结构")
    inspect_parser.add_argument("--url", required=True)
    inspect_parser.add_argument("--credential", required=True)
    inspect_parser.add_argument("--sheet")
    inspect_parser.add_argument("--table")
    inspect_parser.add_argument("--view")
    inspect_parser.add_argument("--range", dest="cell_range", default=INSPECT_RANGE)
    inspect_parser.add_argument("--header-row", type=int)
    inspect_parser.add_argument("--sample-rows", type=int, default=3)

    query_parser = commands.add_parser("query", help="查询飞书电子表格或多维表格")
    add_query_options(query_parser)

    chat_parser = commands.add_parser("chat", help="列出机器人所在群")
    chat_commands = chat_parser.add_subparsers(dest="chat_command", required=True)
    list_chat = chat_commands.add_parser("list")
    list_chat.add_argument("--credential", required=True)

    delivery_parser = commands.add_parser("delivery", help="预览或发布查询结果到飞书群")
    delivery_commands = delivery_parser.add_subparsers(dest="delivery_command", required=True)
    preview_delivery = delivery_commands.add_parser("preview")
    add_query_options(preview_delivery)
    preview_delivery.add_argument("--chat-id")
    preview_delivery.add_argument("--chat-name")
    publish_delivery = delivery_commands.add_parser("publish")
    add_query_options(publish_delivery)
    publish_delivery.add_argument("--chat-id")
    publish_delivery.add_argument("--chat-name")
    publish_delivery.add_argument("--expected-hash", required=True)
    publish_delivery.add_argument("--confirm", action="store_true")

    profile_parser = commands.add_parser("profile", help="管理表格配置")
    profile_commands = profile_parser.add_subparsers(dest="profile_command", required=True)
    profile_commands.add_parser("list")
    show_profile = profile_commands.add_parser("show")
    show_profile.add_argument("--name", required=True)
    save_profile = profile_commands.add_parser("save")
    save_profile.add_argument("--spec", required=True)
    save_profile.add_argument("--replace", action="store_true")
    delete_profile = profile_commands.add_parser("delete")
    delete_profile.add_argument("--name", required=True)
    delete_profile.add_argument("--yes", action="store_true")

    credential_parser = commands.add_parser("credential", help="管理飞书应用凭证")
    credential_commands = credential_parser.add_subparsers(dest="credential_command", required=True)
    credential_commands.add_parser("list")
    test_credential = credential_commands.add_parser("test")
    test_credential.add_argument("--spec", required=True)
    save_credential = credential_commands.add_parser("save")
    save_credential.add_argument("--spec", required=True)
    save_credential.add_argument("--replace", action="store_true")
    delete_credential = credential_commands.add_parser("delete")
    delete_credential.add_argument("--name", required=True)
    delete_credential.add_argument("--yes", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "inspect":
            result = command_inspect(args)
        elif args.command == "query":
            profile_name, profile = query_spec(args)
            result = execute_query(profile_name, profile, args)
        elif args.command == "chat":
            result = command_chat(args)
        elif args.command == "delivery":
            result = command_delivery(args)
        elif args.command == "profile":
            result = command_profile(args)
        elif args.command == "credential":
            result = command_credential(args)
        else:
            raise FeishuSheetError(f"未知命令: {args.command}")
        emit(result)
        return 0
    except (FeishuSheetError, OSError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
