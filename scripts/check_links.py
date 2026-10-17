"""Check every link in README.md (and docs/*.md with --all): relative files exist, #anchors match a heading,
external URLs do not return 404/410. Exit 1 on any broken link.  Run: python scripts/check_links.py [--all]"""
import glob, os, re, sys, urllib.error, urllib.request

def slug(h):
    h = re.sub(r"[^\w\- ]", "", h.strip().lower())
    return h.replace(" ", "-")

def links(text):
    for m in re.finditer(r"\[[^\]]*\]\(([^)\s]+)\)|<img[^>]+src=\"([^\"]+)\"", text):
        yield m.group(1) or m.group(2)

files = ["README.md"] + (sorted(glob.glob("docs/*.md")) if "--all" in sys.argv else [])
bad, checked, cache = [], 0, {}
for f in files:
    text = open(f).read(); base = os.path.dirname(f)
    text_no_code = re.sub(r"```.*?```", "", text, flags=re.S)
    anchors = {slug(h) for h in re.findall(r"^#+\s+(.*)$", text_no_code, re.M)}
    for url in links(text_no_code):
        checked += 1
        if url.startswith(("http://", "https://")):
            if url not in cache:
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 link-check"}, method="GET")
                    cache[url] = urllib.request.urlopen(req, timeout=20).status
                except urllib.error.HTTPError as e:
                    cache[url] = e.code
                except Exception as e:
                    cache[url] = f"error: {type(e).__name__}"
            st = cache[url]
            if st in (404, 410) or isinstance(st, str):
                bad.append(f"{f}: {url} -> {st}")
        elif url.startswith("#"):
            if url[1:] not in anchors:
                bad.append(f"{f}: anchor {url} has no matching heading")
        elif not url.startswith("mailto:"):
            path = os.path.normpath(os.path.join(base, url.split("#")[0]))
            if not os.path.exists(path):
                bad.append(f"{f}: {url} -> missing file {path}")
print("\n".join(bad) or f"OK: {checked} links checked in {len(files)} file(s), none broken")
sys.exit(1 if bad else 0)
