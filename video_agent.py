#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VideoAgent — a universal video downloader agent built on yt-dlp with automatic website search.

Requirements:
    pip install yt-dlp
    (recommended: install ffmpeg and deno)

Usage examples:
    # Search by movie/series title and download directly:
    python video_agent.py --quality 1080p "The Paradise 2026"
    python video_agent.py "Kantara Chapter 1"
    python video_agent.py --search "Inception" --quality 1080p

    # Inspect metadata without downloading:
    python video_agent.py --quality 1080p --info "The Paradise 2026"

    # Download via direct page or locker URL:
    python video_agent.py --quality 1080p "https://new10.hdhub4u.cl/the-paradise-2026-hindi-webrip-full-movie/"

    # Interactive search selection (choose from multiple results):
    python video_agent.py --select "Deadpool"

    # Audio extraction:
    python video_agent.py --audio-only --audio-format mp3 "The Paradise"
"""

import argparse
import base64
import json
import os
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode
from urllib.request import Request, urlopen

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(line_buffering=True)

try:
    import yt_dlp
except ImportError:
    print("yt-dlp not found. Install it with:  pip install yt-dlp", file=sys.stderr)
    sys.exit(1)


USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
CANDIDATE_MIRRORS = [
    'https://new10.hdhub4u.cl',
    'https://new11.hdhub4u.cl',
    'https://hdhub4u.eco',
    'https://hdhub4u.ms',
]
SEARCH_API_ENDPOINT = "https://search.pingora.fyi/collections/post/documents/search"
_cached_active_domain = None


def check_ffmpeg() -> bool:
    """Return True if ffmpeg is available on PATH."""
    return shutil.which("ffmpeg") is not None


def check_deno() -> str:
    """Return path to deno if installed, else None."""
    return shutil.which("deno") if shutil.which("deno") else None


def get_active_domain(preferred_site=None) -> str:
    """Detect and return an active, responsive domain mirror for HDHub4u."""
    global _cached_active_domain
    if preferred_site:
        return preferred_site.rstrip('/')
    if _cached_active_domain:
        return _cached_active_domain

    for domain in CANDIDATE_MIRRORS:
        try:
            req = Request(domain, headers={'User-Agent': USER_AGENT})
            with urlopen(req, timeout=4) as resp:
                if resp.status == 200:
                    p = urlparse(resp.url)
                    _cached_active_domain = f"{p.scheme}://{p.netloc}"
                    return _cached_active_domain
        except Exception:
            continue

    _cached_active_domain = CANDIDATE_MIRRORS[0]
    return _cached_active_domain


def clean_search_query(query: str) -> str:
    """Clean extra technical terms from title if initial search returns empty."""
    q = query
    # Remove resolution tags
    q = re.sub(r'\b(4k|2160p|1080p|720p|480p|hd|webrip|web-dl|bluray|x264|hevc|x265)\b', '', q, flags=re.IGNORECASE)
    # Remove language/release tags
    q = re.sub(r'\b(full movie|movie|all episodes|series|hindi|dual audio|org|dubbed)\b', '', q, flags=re.IGNORECASE)
    # Remove year inside brackets
    q = re.sub(r'[\(\[\{]\s*\d{4}\s*[\)\]\}]', '', q)
    # Clean non-alphanumeric except spaces
    q = re.sub(r'[^\w\s]', ' ', q)
    return " ".join(q.split()).strip()


def search_titles(query: str, site: str = None, limit: int = 5) -> list:
    """
    Search the target website index for movie/series titles using the search API.
    Returns list of dicts: [{'title': str, 'url': str, 'orig_permalink': str}, ...]
    """
    active_domain = get_active_domain(site)

    def _execute_search(q_term):
        params = {
            'q': q_term,
            'query_by': 'post_title,category,stars,director,imdb_id',
            'query_by_weights': '4,2,2,2,4',
            'sort_by': 'sort_by_date:desc',
            'limit': limit,
            'highlight_fields': 'none',
            'use_cache': 'true',
            'page': 1
        }
        api_url = f"{SEARCH_API_ENDPOINT}?{urlencode(params)}"
        req = Request(api_url, headers={
            'User-Agent': USER_AGENT,
            'Referer': f"{active_domain}/search.html",
            'Origin': active_domain
        })
        results = []
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            for hit in data.get('hits', []):
                doc = hit.get('document', {})
                title = doc.get('post_title', '').strip()
                permalink = doc.get('permalink', '')
                path = urlparse(permalink).path
                results.append({
                    'title': title,
                    'url': f"{active_domain}{path}",
                    'orig_permalink': permalink
                })
        return results

    try:
        results = _execute_search(query)
        if not results:
            cleaned = clean_search_query(query)
            if cleaned and cleaned.lower() != query.lower():
                results = _execute_search(cleaned)
        return results
    except Exception as e:
        print(f"[!] Search query error: {e}", file=sys.stderr)
        return []


def link_priority(link: str) -> int:
    """Prioritize high-speed CDN and direct stream links over secondary rate-limited hosts."""
    l = link.lower()
    if 'r2.cloudflarestorage.com' in l or 'r2.dev' in l:
        return 0
    if any(l.endswith(ext) or ext in l for ext in ['.mkv', '.mp4', '.avi', '.mov']):
        return 1
    if 'pixeldrain' in l:
        return 2
    return 3


def resolve_locker_url(locker_url, depth=0, max_depth=2, visited=None) -> list:
    """
    Recursively introspects intermediate file lockers (hubcloud, hubdrive, gamerxyt, hubcdn, etc.) 
    to extract actual direct download / video links (.mkv, .mp4, r2.cloudflarestorage.com, r2.dev, etc.).
    Optimized with visited caching and early returns for high-speed direct links.
    """
    if depth > max_depth:
        return []
    if visited is None:
        visited = set()
    if locker_url in visited:
        return []
    visited.add(locker_url)

    resolved_links = []
    try:
        req = Request(locker_url, headers={
            'User-Agent': USER_AGENT,
            'Referer': get_active_domain() + '/'
        })
        with urlopen(req, timeout=6) as response:
            html = response.read().decode('utf-8', errors='ignore')
            
            links = re.findall(r'href=["\'](https?://[^"\']+)["\']', html, re.IGNORECASE)
            forms = re.findall(r'action=["\'](https?://[^"\']+)["\']', html, re.IGNORECASE)
            js_urls = re.findall(r'["\'](https?://[^"\']+)["\']', html, re.IGNORECASE)
            
            b64_matches = re.findall(r'[?&](?:r|link|data|url)=([A-Za-z0-9+/=]+)', html)
            quoted_b64 = re.findall(r'["\']([A-Za-z0-9+/=]{20,})["\']', html)
            
            decoded_urls = []
            for b64 in (b64_matches + quoted_b64):
                try:
                    padding = 4 - (len(b64) % 4)
                    if padding < 4:
                        b64 += '=' * padding
                    decoded = base64.b64decode(b64).decode('utf-8', errors='ignore')
                    if 'http://' in decoded or 'https://' in decoded:
                        decoded_urls.append(decoded)
                except Exception:
                    pass

            all_found = list(set(forms + links + js_urls + decoded_urls))
            
            direct_links = []
            intermediate_links = []
            
            for l in all_found:
                if any(x in l.lower() for x in ['telegram.me', 't.me', 'whatsapp.com', 'facebook.com', 'twitter.com', 'instagram.com']):
                    continue
                try:
                    parsed_p = urlparse(l)
                    q_params = parse_qs(parsed_p.query)
                    for qk in ['link', 'url', 'file', 'data', 'r']:
                        if qk in q_params:
                            for qv in q_params[qk]:
                                if qv.startswith('http://') or qv.startswith('https://'):
                                    direct_links.append(qv)
                except Exception:
                    pass

                if any(ext in l.lower() for ext in ['.mp4', '.mkv', '.avi', '.mov', 'r2.cloudflarestorage.com', 'r2.dev', 'pixeldrain']):
                    direct_links.append(l)
                elif any(domain in l.lower() for domain in ['hubcloud', 'hubdrive', 'hubcdn', 'gamerxyt', 'greenmotors', 'hdstream4u', 'inventoryidea']):
                    if l not in visited:
                        intermediate_links.append(l)
            
            for dl in direct_links:
                if dl not in resolved_links:
                    resolved_links.append(dl)
            
            # If direct download / CDN links are obtained, prioritize and return early!
            if resolved_links:
                return sorted(resolved_links, key=link_priority)

            # Otherwise, traverse intermediate lockers
            for il in intermediate_links[:3]:
                sub = resolve_locker_url(il, depth + 1, max_depth, visited)
                for s in sub:
                    if s not in resolved_links:
                        resolved_links.append(s)
                if resolved_links:
                    break
    except Exception:
        pass
    
    if not resolved_links and depth == 0:
        return [locker_url]
    return sorted(resolved_links, key=link_priority)


def extract_links_from_webpage(url, quality=None) -> list:
    """
    Introspects landing/aggregator pages, extracting genuine download lockers 
    and file-hosting links while filtering out CSS, JS, fonts, and WP assets.
    """
    try:
        req = Request(url, headers={
            'User-Agent': USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Referer': url
        })
        with urlopen(req, timeout=15) as response:
            content_type = response.headers.get('Content-Type', '')
            if 'text/html' not in content_type:
                return [url]
            
            html = response.read().decode('utf-8', errors='ignore')
            anchor_pattern = r'<a\s+(?:[^>]*?\s+)?href=["\'](https?://[^"\']+)["\'][^>]*>(.*?)</a>'
            matches = re.findall(anchor_pattern, html, re.IGNORECASE | re.DOTALL)
            
            valid_candidates = []
            priority_domains = [
                'hubcloud', 'hubcdn', 'hubdrive', 'pixeldrain', 'filepress', 
                'drive.google', 'mega.nz', 'gdflix', 'katfile', 'terabox', 
                'greenmotors', 'hdstream4u', 'vidsrc', 'embed', 'player'
            ]
            
            ignored_extensions = ['.css', '.js', '.png', '.jpg', '.jpeg', '.gif', '.ico', '.svg', '.woff', '.ttf', '.xml']
            ignored_keywords = [
                'xmlrpc', 'gmpg.org', 'fonts.', 'cdnfonts', 'wordpress.org', 
                'wp-content', 'wp-includes', 'wp-json', 'facebook.com', 'twitter.com', 
                'instagram.com', 'telegram.org', 't.me', 'whatsapp.com', 'gravatar.com', 'cdnjs.cloudflare'
            ]

            for link, inner_text in matches:
                if any(link.endswith(ext) or ext in link for ext in ignored_extensions):
                    continue
                if any(kw in link.lower() for kw in ignored_keywords):
                    continue
                
                clean_text = re.sub(r'<[^>]+>', '', inner_text).strip().lower()
                is_priority = any(domain in link.lower() for domain in priority_domains)
                is_download_btn = any(kw in clean_text for kw in ['download', 'watch', 'server', 'click', '1080p', '720p', '480p', '4k'])
                
                if quality:
                    if quality.lower() in clean_text:
                        if link not in valid_candidates:
                            valid_candidates.append(link)
                else:
                    if (is_priority or is_download_btn) and link not in valid_candidates:
                        valid_candidates.append(link)

            return valid_candidates if valid_candidates else [url]
    except Exception:
        return [url]


def resolve_input_target(target: str, args) -> str:
    """
    Accepts either a direct URL or a movie title.
    If it's a title, searches the website, selects the matching item, and returns its URL.
    """
    target = target.strip()
    if target.startswith(('http://', 'https://')):
        return target

    # Target is a movie title / query
    print(f"[*] Searching website for: '{target}'...")
    results = search_titles(target, site=args.site, limit=args.search_limit)

    if not results:
        print(f"[!] No matching titles found for '{target}'.", file=sys.stderr)
        return None

    print(f"[*] Found {len(results)} match(es):")
    for idx, r in enumerate(results, 1):
        print(f"    [{idx}] {r['title']}")

    selected_idx = 0
    if args.select and sys.stdin.isatty() and len(results) > 1:
        while True:
            try:
                choice = input(f"Select movie [1-{len(results)}] (default 1): ").strip()
                if not choice:
                    selected_idx = 0
                    break
                choice_num = int(choice)
                if 1 <= choice_num <= len(results):
                    selected_idx = choice_num - 1
                    break
                print(f"Please enter a number between 1 and {len(results)}.")
            except (ValueError, EOFError, KeyboardInterrupt):
                selected_idx = 0
                break
    else:
        # Use --search-index or default to 1st result
        idx_arg = getattr(args, 'search_index', 1)
        if 1 <= idx_arg <= len(results):
            selected_idx = idx_arg - 1
        else:
            selected_idx = 0

    chosen = results[selected_idx]
    print(f"[*] Selected: {chosen['title']}")
    print(f"[*] Movie Page: {chosen['url']}")
    return chosen['url']


def list_formats(url, quiet=True) -> list:
    ydl_opts = {
        'quiet': quiet,
        'skip_download': True,
        'list_formats': True,
        'extract_flat': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            if 'formats' in info:
                return info['formats']
            elif 'entries' in info and len(info['entries']) > 0 and 'formats' in info['entries'][0]:
                return info['entries'][0]['formats']
        except Exception:
            pass
        return []


def resolve_options(args, format_override=None) -> dict:
    opts = {
        "outtmpl": str(Path(args.output_dir) / "%(title)s.%(ext)s"),
        "noplaylist": not args.playlist,
        "continuedl": True,
        "retries": 10,
        "fragment_retries": 10,
        "restrictfilenames": True,
        "progress_hooks": [progress_hook],
        "quiet": args.quiet,
        "no_warnings": args.quiet,
        "encoding": "utf-8",
    }

    if args.cookies:
        opts["cookiefile"] = args.cookies
    if args.proxy:
        opts["proxy"] = args.proxy

    if args.js_runtimes:
        runtime_name = args.js_runtimes.lower()
        if runtime_name == "deno":
            deno_path = check_deno()
            if deno_path:
                opts["js_runtimes"] = {"deno": {"path": deno_path}}
            else:
                print("[!] deno not found. Please install deno or remove --js-runtimes.", file=sys.stderr)
                sys.exit(1)
        else:
            opts["js_runtimes"] = {runtime_name: {}}

    if args.audio_only:
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [
            {"key": "FFmpegExtractAudio", "preferredcodec": args.audio_format}
        ]
    elif format_override:
        opts["format"] = format_override
    elif args.format:
        opts["format"] = args.format
    else:
        if check_ffmpeg():
            opts["format"] = "bestvideo+bestaudio/best"
        else:
            opts["format"] = "best"

    if args.subs:
        opts["writesubtitles"] = True
        opts["writeautomaticsubtitles"] = True
        opts["subtitleslangs"] = args.subs_langs.split(",")
        opts["subtitlesformat"] = "vtt"

    return opts


def progress_hook(d):
    if d.get('_status') == 'downloading':
        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        done = d.get("downloaded_bytes") or 0
        pct = (done / total * 100) if total else 0
        speed = d.get("speed") or 0
        eta = d.get("eta") or 0
        line = f"  {pct:5.1f}%  {done/1e6:7.1f}/{total/1e6:7.1f} MB"
        if speed:
            line += f"  @ {speed/1e6:.1f} MB/s"
        if eta:
            line += f"  ETA {eta}s"
        print(line, end="\r", flush=True)
    elif d.get('_status') in ("finished", "error"):
        print()


def fetch_info(url, quiet=False, js_runtimes=None) -> dict:
    ydl_opts = {
        "quiet": quiet,
        "skip_download": True,
    }
    if js_runtimes:
        ydl_opts["js_runtimes"] = js_runtimes
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)


def print_info_for_url(target, args):
    """Inspect and display metadata for a URL or title without downloading."""
    try:
        url = resolve_input_target(target, args)
        if not url:
            return

        print(f"[*] Inspecting landing page for source links (quality: {args.quality or 'auto'})...")
        discovered_urls = extract_links_from_webpage(url, quality=args.quality)
        
        target_url = None
        for cand in discovered_urls:
            if "youtube.com/embed" in cand or "telegram.me" in cand:
                continue
            if any(locker in cand for locker in ['hubcdn', 'hubdrive', 'hubcloud', 'greenmotors', 'hdstream4u']):
                resolved = resolve_locker_url(cand)
                if resolved:
                    target_url = resolved[0]
                    break
            else:
                target_url = cand
                break

        if not target_url:
            target_url = url
        
        js_r = {"deno": {"path": check_deno()}} if args.js_runtimes and check_deno() else None
        info = fetch_info(target_url, quiet=args.quiet, js_runtimes=js_r)
        print(f"\n{'='*40}")
        print(f"Target URL: {target_url}")
        print(f"Title:     {info.get('title', target_url)}")
        print(f"Site:      {info.get('extractor_key', 'unknown')}")
        duration = info.get('duration', 'n/a')
        print(f"Duration:  {duration} seconds ({info.get('duration_string', 'n/a')})")
        print(f"Uploader:  {info.get('uploader', 'n/a')}")
        if 'formats' in info:
            video_formats = [f for f in info['formats'] if f.get('height') is not None]
            if video_formats:
                best_video = max(video_formats, key=lambda f: (f.get("height", 0), f.get("tbr", 0)))
                res = best_video.get('resolution', f"{best_video.get('height','?')}p")
                print(f"Best video: {res}")
            else:
                print("No video format found")
        print(f"{'='*40}\n")
    except Exception as e:
        print(f"[!] {target}: {e}", file=sys.stderr)


def download_one(target, args) -> tuple:
    """Download a single target (URL or title) with smart searching, locker page resolution, and filtering."""
    try:
        url = resolve_input_target(target, args)
        if not url:
            return target, False, f"Could not find or resolve title on website: {target}"

        print(f"[*] Inspecting landing page for source links (quality: {args.quality or 'auto'}): {url}")
        candidates = extract_links_from_webpage(url, quality=args.quality)
        print(f"[*] Found {len(candidates)} candidate locker links matching quality.")
        
        last_error = "No supported media download links could be resolved."
        
        for cand in candidates:
            if "youtube.com/embed" in cand or "telegram.me" in cand:
                continue
            
            if any(locker in cand for locker in ['hubcdn', 'hubdrive', 'hubcloud', 'greenmotors', 'hdstream4u']):
                print(f"[*] Resolving locker page: {cand}")
                resolved = resolve_locker_url(cand)
            else:
                resolved = [cand]

            for target_url in resolved:
                if "telegram.me" in target_url:
                    continue
                try:
                    print(f"[*] Attempting download from: {target_url[:90]}...")
                    js_r = {"deno": {"path": check_deno()}} if args.js_runtimes and check_deno() else None
                    info = fetch_info(target_url, quiet=True, js_runtimes=js_r)
                    
                    format_to_use = args.format
                    if not format_to_use and 'formats' in info and len(info['formats']) == 1:
                        format_to_use = info['formats'][0].get('format_id')

                    opts = resolve_options(args, format_override=format_to_use)
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        info2 = ydl.extract_info(target_url, download=True)
                        title = info2.get("title", target_url)
                        return target, True, f"Successfully downloaded: {title}"
                except Exception as e:
                    last_error = str(e)
                    continue

        return target, False, last_error

    except Exception as e:
        return target, False, f"Unexpected error: {e}"


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="video_agent",
        description="Universal video downloader agent with automatic title search and strict locker asset filtering.",
    )
    parser.add_argument("targets", nargs="*", help="Video URLs or movie/series titles to search and download")
    parser.add_argument("--search", "--title", dest="explicit_searches", action="append", default=[], help="Movie/series title to search on website")
    parser.add_argument("--select", action="store_true", help="Interactively select from multiple search results")
    parser.add_argument("--search-index", type=int, default=1, help="Which search result to pick (1-based, default: 1)")
    parser.add_argument("--search-limit", type=int, default=5, help="Maximum number of search results to retrieve (default: 5)")
    parser.add_argument("--site", default=None, help="Base website URL (default: auto-detected HDHub4u active mirror)")
    parser.add_argument("--batch", help="File with one URL or movie title per line")
    parser.add_argument("-o", "--output-dir", default="downloads", help="Where to save files")
    parser.add_argument("-f", "--format", help="yt-dlp format selector")
    parser.add_argument("--quality", default=None, help="Preferred video quality (e.g. 1080p, 720p, 4k)")
    parser.add_argument("--audio-only", action="store_true", help="Extract audio only")
    parser.add_argument("--audio-format", default="mp3", help="Audio codec")
    parser.add_argument("-p", "--playlist", action="store_true", help="Download playlist")
    parser.add_argument("-s", "--subs", action="store_true", help="Download subtitles")
    parser.add_argument("--subs-langs", default="en", help="Subtitle languages")
    parser.add_argument("--cookies", help="Path to cookies.txt")
    parser.add_argument("--proxy", help="Proxy URL")
    parser.add_argument("--jobs", type=int, default=4, help="Max concurrent downloads")
    parser.add_argument("--info", action="store_true", help="Only print metadata")
    parser.add_argument("-q", "--quiet", action="store_true", help="Quiet output")
    parser.add_argument("--js-runtimes", default=None, help="Specify JS runtime")

    args = parser.parse_args()
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)

    all_targets = list(args.targets) + list(args.explicit_searches)

    if args.batch:
        with open(args.batch, encoding="utf-8") as fh:
            for ln in fh:
                t = ln.strip()
                if t and not t.startswith("#"):
                    all_targets.append(t)

    if not all_targets:
        parser.print_help()
        return 2

    if args.info:
        for t in all_targets:
            print_info_for_url(t, args)
        return 0

    ok = fail = 0
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(download_one, t, args): t for t in all_targets}
        for fut in as_completed(futures):
            t = futures[fut]
            try:
                success, msg = fut.result()[1:]
            except Exception as e:
                success, msg = False, f"Execution failed: {e}"
            if success:
                ok += 1
                print(f"✔ {t}\n   → {msg}")
            else:
                fail += 1
                print(f"✘ {t}\n   {msg}", file=sys.stderr)

    print(f"\n[*] Done: {ok} succeeded, {fail} failed.")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
