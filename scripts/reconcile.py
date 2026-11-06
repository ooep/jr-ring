#!/usr/bin/env python3
"""
jr-ring 旋律对账/回填脚本

前置: 已从 ssmn93 两仓库下载并解包到 EXTRACT_DIR/<repo>/ 下(保留目录结构)。
本脚本:
  1. 扫描两个仓库解包目录里的全部 *.mp3, 建立 归一化基名 -> 相对路径 索引
  2. 对 mapping.json 中每个 unique 旋律名, 按 精确 -> 归一化 -> 子串 多级匹配
  3. 把命中的 mp3 复制到 songs/<repo>/<相对路径> (去重)
  4. 回填 mapping.json 的 song_files 字段
  5. 输出未命中报告 unmatched.json

用法:
  python3 reconcile.py                      # 全量对账 + 复制 + 回填
  python3 reconcile.py --no-copy            # 只分析命中率, 不复制文件
  python3 reconcile.py --report-only        # 只打印统计
"""
import json, os, sys, re, shutil, argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAPPING = os.path.join(ROOT, "mapping.json")
SONGS = os.path.join(ROOT, "songs")
EXTRACT = os.path.join("/root/.codebuddy/artifact", "extracted")
REPOS = ["dokobell_melody", "depart-melody"]

# 这些"旋律名"实为占位/无曲, 直接跳过
SKIP_PATTERNS = ["曲名不明", "【未収録", "未収録", "不明", "―", "‐", "/*", "*/", "→", "（なし）", "なし"]
SKIP_EXACT = {"", "曲名不明", "不明", "ー", "-", "×", "✕", "－"}

def normalize(s):
    """归一化: 去空白, 统一全/半角, 去常见版本标记以外的噪声"""
    if not s:
        return ""
    s = s.strip()
    # 全角转半角
    s = s.translate(str.maketrans(
        "ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ０１２３４５６７８９　",
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 "))
    s = s.replace(" ", "").replace("　", "")
    return s

def build_index():
    idx = {}  # norm_basename -> list of (repo, relpath)
    for repo in REPOS:
        base = os.path.join(EXTRACT, repo)
        if not os.path.isdir(base):
            print(f"[warn] 解包目录不存在: {base}", flush=True)
            continue
        for dirpath, _, files in os.walk(base):
            for f in files:
                if f.lower().endswith(".mp3"):
                    rel = os.path.relpath(os.path.join(dirpath, f), base)
                    base_noext = f[:-4]
                    key = normalize(base_noext)
                    idx.setdefault(key, []).append((repo, rel))
    return idx

def is_skip(name):
    if name in SKIP_EXACT:
        return True
    for p in SKIP_PATTERNS:
        if p in name:
            return True
    return False

def match(name, idx):
    """返回 (repo, relpath) 或 None"""
    if is_skip(name):
        return None
    n = normalize(name)
    if not n:
        return None
    # 1. 精确
    if n in idx:
        return idx[n][0]
    # 2. 子串: 基名包含旋律, 或旋律包含基名 (取最长基名优先)
    cand = []
    for key, vals in idx.items():
        if not key:
            continue
        if n in key or key in n:
            cand.append((len(key), vals[0]))
    if cand:
        cand.sort(reverse=True)
        return cand[0][1]
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-copy", action="store_true")
    ap.add_argument("--report-only", action="store_true")
    args = ap.parse_args()

    print("建立索引...", flush=True)
    idx = build_index()
    total_files = sum(len(v) for v in idx.values())
    print(f"索引到 {total_files} 个 mp3 文件 ({len(idx)} 个归一化基名)", flush=True)

    mp = json.load(open(MAPPING, encoding="utf-8"))
    seen = {}  # name -> station name
    for st in mp["stations"]:
        for m in st.get("melodies", []):
            nm = m.get("melody")
            if nm and nm not in seen:
                seen[nm] = st["name"]
    melodies = list(seen.keys())
    print(f"mapping 中 unique 旋律: {len(melodies)} (来自 {len(mp['stations'])} 站)", flush=True)

    matched = {}
    unmatched = []
    for nm in melodies:
        res = match(nm, idx)
        if res:
            matched[nm] = res  # (repo, relpath)
        else:
            if not is_skip(nm):
                unmatched.append({"melody": nm, "station": seen[nm]})

    ok = len(matched)
    print(f"命中: {ok}/{len(melodies)} (跳过占位 {len(melodies)-ok-len(unmatched)} 个)", flush=True)
    print(f"未命中(待补): {len(unmatched)}", flush=True)

    if args.report_only:
        json.dump(unmatched, open(os.path.join(ROOT, "unmatched.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("未命中清单 -> unmatched.json")
        return

    # 复制命中文件
    if not args.no_copy:
        copied = 0
        for nm, (repo, rel) in matched.items():
            src = os.path.join(EXTRACT, repo, rel)
            dst = os.path.join(SONGS, repo, rel)
            if not os.path.exists(src):
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if not os.path.exists(dst) or os.path.getsize(dst) != os.path.getsize(src):
                shutil.copy2(src, dst)
                copied += 1
        print(f"复制 {copied} 个 mp3 到 songs/ (总计 {sum(1 for _ in iter_mp3(SONGS))} 个)", flush=True)

    # 回填 mapping
    name_to_path = {}
    for nm, (repo, rel) in matched.items():
        name_to_path[nm] = f"songs/{repo}/{rel}"
    for st in mp["stations"]:
        files = []
        for m in st.get("melodies", []):
            p = name_to_path.get(m.get("melody"))
            if p and p not in files:
                files.append(p)
        st["song_files"] = files
    json.dump(mp, open(MAPPING, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"mapping.json 已回填. 有歌曲的车站: {sum(1 for s in mp['stations'] if s['song_files'])}")

    json.dump(unmatched, open(os.path.join(ROOT, "unmatched.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("未命中清单 -> unmatched.json")

def iter_mp3(folder):
    for dp, _, fs in os.walk(folder):
        for f in fs:
            if f.lower().endswith(".mp3"):
                yield os.path.join(dp, f)

if __name__ == "__main__":
    main()
