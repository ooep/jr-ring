#!/usr/bin/env python3
"""组装 jr-music Worker assets：songs/ 音频 + mapping.json + CORS _headers。

产物 static-worker/assets/ 由 deploy-music.yml 上传 Cloudflare Workers Static Assets，
不入库（.gitignore 已排除）。可重入：重复运行直接覆盖。
"""
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # jr-ring 根
SRC_SONGS = os.path.join(ROOT, "songs")
SRC_MAP = os.path.join(ROOT, "mapping.json")
OUT = os.path.join(ROOT, "static-worker", "assets")

# CORS：主站页面跨域 fetch mapping.json 与音频都需要
HEADERS = """\
/mapping.json
  Access-Control-Allow-Origin: *
  Cache-Control: public, max-age=3600

/songs/*
  Access-Control-Allow-Origin: *
  Cache-Control: public, max-age=604800

"""


def main() -> int:
    songs_out = os.path.join(OUT, "songs")
    os.makedirs(songs_out, exist_ok=True)

    n = 0
    for fn in sorted(os.listdir(SRC_SONGS)):
        if fn.lower().endswith(".mp3"):
            shutil.copy2(os.path.join(SRC_SONGS, fn), os.path.join(songs_out, fn))
            n += 1

    shutil.copy2(SRC_MAP, os.path.join(OUT, "mapping.json"))
    with open(os.path.join(OUT, "_headers"), "w", encoding="utf-8") as f:
        f.write(HEADERS)

    total = sum(
        os.path.getsize(os.path.join(dp, fn))
        for dp, _, fns in os.walk(OUT)
        for fn in fns
    )
    print(f"assets 组装完成: {n} 个 mp3 + mapping.json + _headers, 总大小 {total / 1048576:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
