#!/usr/bin/env python3
"""
BM2X.py: Chrome ブックマークフォルダを自動巡回 → URL取得 → HTML取得 → Markdown変換 → ローカル保存
"""
import os
import json
import time
import argparse
import logging
import re
import platform
import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as md
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

def get_chrome_bookmarks_path():
    """OSに応じてChromeのBookmarksファイルのパスを自動推測"""
    system = platform.system()
    if system == "Windows":
        base = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Google', 'Chrome', 'User Data')
    elif system == "Darwin":  # macOS
        base = os.path.expanduser('~/Library/Application Support/Google/Chrome')
    else:  # Linux
        base = os.path.expanduser('~/.config/google-chrome')
    return os.path.join(base, 'Default', 'Bookmarks')

def extract_urls_from_folder(bookmarks_data, target_folder):
    """指定フォルダ配下のURLを再帰的に取得 [(url, title, subfolder_path), ...]"""
    results = []
    roots = bookmarks_data.get('roots', {})

    def find_and_dump(node, current_path=""):
        if node.get('type') == 'folder':
            folder_name = node.get('name', '')
            new_path = f"{current_path}/{folder_name}" if current_path else folder_name

            if folder_name == target_folder:
                # 対象フォルダ発見 → 配下の全URLを収集
                def collect(n, path):
                    for child in n.get('children', []):
                        if child.get('type') == 'url':
                            results.append((child['url'], child.get('name', 'no_title'), path))
                        elif child.get('type') == 'folder':
                            collect(child, f"{path}/{child.get('name', '')}")
                collect(node, current_path)
                return True

            # 未発見なら子フォルダを探索
            for child in node.get('children', []):
                if find_and_dump(child, new_path):
                    return True
        return False

    find_and_dump(roots, "")
    return results

def html_to_markdown(html_content, url):
    """HTML → Markdown 変換（スクリプト/ナビ除去付き）"""
    soup = BeautifulSoup(html_content, 'html.parser')
    for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'iframe']):
        tag.decompose()
    try:
        return md(str(soup.body or soup), heading_style="ATX", bullets="-", strip=["img"])
    except Exception as e:
        logger.error(f"MD変換失敗 {url}: {e}")
        return f"[変換失敗]({url})"

def fetch_and_save(url, title, sub_path, output_dir, delay=1.5):
    """URL取得 → MD変換 → YAML Front Matter 付加 → 保存"""
    safe_name = re.sub(r'[<>:"/\\|?*]', '_', title)[:100]
    file_path = Path(output_dir) / sub_path / f"{safe_name}.md"
    file_path.parent.mkdir(parents=True, exist_ok=True)

    if file_path.exists():
        logger.info(f"⏭️ スキップ (既出): {url}")
        return True

    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) BM2X/1.0'}
    try:
        res = requests.get(url, headers=headers, timeout=15)
        res.raise_for_status()
        time.sleep(delay)  # サーバー負荷・BAN防止
    except Exception as e:
        logger.error(f"❌ 取得失敗 {url}: {e}")
        return False

    md_body = html_to_markdown(res.text, url)
    front_matter = f"---\ntitle: '{title}'\nurl: {url}\nsaved: {time.strftime('%Y-%m-%d %H:%M:%S')}\n---\n\n"
    
    try:
        file_path.write_text(front_matter + md_body, encoding='utf-8')
        logger.info(f"✅ 保存完了: {file_path}")
        return True
    except Exception as e:
        logger.error(f"❌ 保存失敗 {file_path}: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="BM2X: Chrome Bookmarks → Markdown 自動変換スクリプト")
    parser.add_argument('--folder', required=True, help='処理対象のブックマークフォルダ名')
    parser.add_argument('--output', default='./saved_pages', help='保存先ディレクトリ')
    parser.add_argument('--bookmarks', default=None, help='Bookmarksファイルのパス（省略時は自動検出）')
    parser.add_argument('--delay', type=float, default=1.5, help='リクエスト間隔(秒)')
    parser.add_argument('--limit', type=int, default=0, help='処理上限数（0=無制限）')
    args = parser.parse_args()

    bm_path = args.bookmarks or get_chrome_bookmarks_path()
    if not os.path.exists(bm_path):
        logger.error(f"Bookmarksファイルが見つかりません: {bm_path}\n💡 Chromeを完全に終了してから実行するか、--bookmarks でパスを指定してください。")
        return

    try:
        with open(bm_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"Bookmarksの解析に失敗: {e}")
        return

    urls = extract_urls_from_folder(data, args.folder)
    if not urls:
        logger.warning(f"📂 フォルダ '{args.folder}' が見つからないかURLがありません。")
        return

    logger.info(f"📦 対象URL数: {len(urls)} | 保存先: {args.output}")
    success, fail = 0, 0
    for i, (url, title, sub_path) in enumerate(urls):
        if args.limit > 0 and i >= args.limit:
            logger.info(f"🛑 上限数 {args.limit} に達しました。")
            break
        if fetch_and_save(url, title, sub_path, args.output, args.delay):
            success += 1
        else:
            fail += 1

    logger.info(f"🏁 完了 | 成功: {success} | 失敗/スキップ: {fail}")

if __name__ == '__main__':
    main()
