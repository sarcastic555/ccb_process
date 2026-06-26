#!/usr/bin/env python3
import argparse
import os
import re
import sys
import urllib.parse
import urllib.request


def build_export_url(url, fmt):
    parsed = urllib.parse.urlparse(url)
    if "docs.google.com" not in parsed.netloc:
        raise ValueError("Google Sheets の URL ではありません。")

    if "/export" in parsed.path:
        qs = urllib.parse.parse_qs(parsed.query)
        if "format" not in qs:
            qs["format"] = [fmt]
            parsed = parsed._replace(query=urllib.parse.urlencode(qs, doseq=True))
        return urllib.parse.urlunparse(parsed)

    match = re.search(r"/d/([^/]+)", parsed.path)
    if not match:
        raise ValueError("Google Sheets のIDを URL から取得できません。")

    sheet_id = match.group(1)
    query = urllib.parse.parse_qs(parsed.query)
    gid = query.get("gid", [None])[0]
    query_params = {"format": fmt}
    if gid:
        query_params["gid"] = gid

    export_path = f"/spreadsheets/d/{sheet_id}/export"
    return urllib.parse.urlunparse(parsed._replace(path=export_path, query=urllib.parse.urlencode(query_params)))


def guess_format(output_path):
    ext = os.path.splitext(output_path)[1].lower()
    if ext in {".xlsx", ".xls"}:
        return "xlsx"
    if ext == ".csv":
        return "csv"
    if ext == ".tsv":
        return "tsv"
    return None


def download(url, output_path):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request) as response:
        data = response.read()

    with open(output_path, "wb") as fp:
        fp.write(data)
    return len(data)


def main():
    parser = argparse.ArgumentParser(description="Google Sheets をダウンロードします。")
    parser.add_argument("sheet_url", help="Google Sheets の共有 URL またはエクスポート URL")
    parser.add_argument("output", nargs="?", help="出力ファイルパス（省略時は sheet.xlsx）")
    parser.add_argument("--format", choices=["xlsx", "csv", "tsv"], help="ダウンロード形式")
    args = parser.parse_args()

    output = args.output or "sheet.xlsx"
    fmt = args.format or guess_format(output) or "xlsx"

    if not output.lower().endswith((".xlsx", ".xls", ".csv", ".tsv")):
        output = f"{output}.{fmt}"

    export_url = build_export_url(args.sheet_url, fmt)

    try:
        size = download(export_url, output)
        print(f"Downloaded {size} bytes to {output}")
    except urllib.error.HTTPError as e:
        print(f"ダウンロードに失敗しました: HTTP {e.code} {e.reason}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
