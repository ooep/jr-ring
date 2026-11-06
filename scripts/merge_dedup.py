#!/usr/bin/env python3
"""
jr-ring 两源合并 + 去重脚本 (v3, 修正 dokobell 旋律名->音频 匹配)
================================
核心修正: dokobell 的 melodies[].melody 显示名 与 实际音频文件名 往往不同
(如 "JRE-IKST-013-02(首都圏12番)" -> "首都圏12番.mp3"), 因此必须复用 download2
的归一化+多级匹配, 把每个旋律名正确映射到本地 songs/dokobell_melody 里的文件,
才能准确判断「该站×台×旋律两源是否都有音频」(即去重对象)。

输入:
  mapping.json          (dkst / dokobell_melody 源: platform 级元数据 + song_files)
  ekimero_mapping.json  (ekimero.github.io 源: line 级元数据 + audio, 部分 null)

输出:
  mapping.json          (合并权威映射, 按 车站×站台×旋律 去重)
  dedup_report.json     (统计 + 跨源重叠 + 字节级重复明细)
"""
import json, os, re, hashlib, datetime
from collections import defaultdict

ROOT = "/workspace/jr-ring"
M_DOC = os.path.join(ROOT, "dokobell_mapping.json")   # 原始 dokobell/dkst 源(含 song_files)
M_EKI = os.path.join(ROOT, "ekimero_mapping.json")
M_OUT = os.path.join(ROOT, "mapping.json")            # 合并后权威映射(覆盖)
REPORT = os.path.join(ROOT, "dedup_report.json")

# ---------- 归一化 / 匹配 (移植 download2 逻辑) ----------
def normalize(s):
    if not s:
        return ""
    s = s.strip()
    s = s.translate(str.maketrans(
        "ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ０１２３４５６７８９　",
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 "))
    return s.replace(" ", "").replace("　", "")

def strip_annotations(s):
    s = re.sub(r"[〈《]?[（\(].*?[）\)][〉》]?", "", s)
    s = re.sub(r"[〈《][^〈》]*[〉》]", "", s)
    return s.strip()

SKIP_EXACT = {"", "曲名不明", "不明", "ー", "-", "×", "✕", "－", "―", "‐", "（なし）", "なし", "音声なし"}
SKIP_PATTERNS = ["曲名不明", "未収録", "不明", "/*", "*/", "→", "音声なし"]

def is_skip(name):
    if name in SKIP_EXACT:
        return True
    for p in SKIP_PATTERNS:
        if p in name:
            return True
    return False

def build_station_index(song_files):
    """本站 song_files (本地相对路径) -> 归一化基名 -> 路径"""
    idx = {}
    for rel in song_files:
        if not os.path.exists(os.path.join(ROOT, rel)):
            continue
        key = normalize(os.path.splitext(os.path.basename(rel))[0])
        idx.setdefault(key, rel)
    return idx

def resolve_dokobell_audio(name, idx):
    """把旋律显示名解析为本站 dokobell 音频路径 (或 None) —— 仅在本站文件内匹配"""
    if is_skip(name):
        return None
    n = normalize(name)
    if not n:
        return None
    if n in idx:
        return idx[n]
    n_up = n.upper()
    up = getattr(resolve_dokobell_audio, "_up", None)
    if up is None:
        up = {k.upper(): v for k, v in idx.items()}
        resolve_dokobell_audio._up = up
    if n_up in up:
        return up[n_up]
    c = normalize(strip_annotations(name))
    if c and c in idx:
        return idx[c]
    cand = [(len(k), v) for k, v in idx.items() if k and (n in k or k in n)]
    if cand:
        cand.sort(reverse=True)
        return cand[0][1]
    return None

def join_key(s):
    k = normalize(s)
    k = k.replace("～", "~").replace("〜", "~")
    return k.casefold()

def md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()

# ---------- 加载 ----------
doc = json.load(open(M_DOC, encoding="utf-8"))
eki = json.load(open(M_EKI, encoding="utf-8"))
doc_stations = {s["name"]: s for s in doc["stations"]}
eki_stations = {s["name"]: s for s in eki["stations"]}

# ekimero 音频索引 (station -> {join_key(melody): path})
eki_audio = {}
for name, s in eki_stations.items():
    d = eki_audio.setdefault(name, {})
    for r in s.get("ekimero", []):
        mel = r.get("melody", "")
        if mel:
            d.setdefault(join_key(mel), r.get("audio"))

# ---------- 合并 ----------
all_names = list(doc_stations.keys())
merged = []
stats = defaultdict(int)

for name in all_names:
    ds = doc_stations.get(name, {})
    es = eki_stations.get(name, {})
    operators = sorted(set(ds.get("operators", []) + es.get("operators", [])))
    lines = sorted(set(ds.get("lines", []) + es.get("lines", [])))
    coord = ds.get("coord") or es.get("coord")

    recs = {}
    doc_melkey_to_recs = defaultdict(list)
    doc_path_to_recs = defaultdict(list)
    doc_songkey_to_path = {}  # 已解析的 dokobell 音频: 文件名键 -> 路径

    # 本站 dokobell 音频索引 (仅在本站实际下载的 song_files 内匹配, 防跨站误配)
    sidx = build_station_index(ds.get("song_files", []))

    # 1) 铺 dokobell 侧 (platform 级), 正确解析每个旋律的音频文件
    for m in ds.get("melodies", []):
        plat = m.get("platform", "")
        mel = m.get("melody", "")
        if not mel:
            continue
        key = (plat, join_key(mel))
        rec = recs.get(key)
        if rec is None:
            rec = {
                "platform": plat, "melody": mel, "line": "",
                "sources": {"dokobell": None, "ekimero": None},
                "audio": None, "deduped": False, "filled_by_ekimero": False,
            }
            recs[key] = rec
            doc_melkey_to_recs[join_key(mel)].append(rec)
        da = resolve_dokobell_audio(mel, sidx)
        if da and rec["sources"]["dokobell"] is None:
            rec["sources"]["dokobell"] = da
            doc_path_to_recs[da].append(rec)
            doc_songkey_to_path[join_key(os.path.splitext(os.path.basename(da))[0])] = da
            if rec["audio"] is None:
                rec["audio"] = da

    # 2) 挂 ekimero 侧
    for r in es.get("ekimero", []):
        mel = r.get("melody", "")
        if not mel:
            continue
        jk = join_key(mel)
        ea = r.get("audio")
        targets = doc_melkey_to_recs.get(jk)
        if not targets and ea:
            # 次级: ekimero 音频文件名 == dokobell 音频文件名
            ajk = join_key(os.path.splitext(os.path.basename(ea))[0])
            dp = doc_songkey_to_path.get(ajk)
            if dp:
                targets = doc_path_to_recs.get(dp)
        if targets:
            for rec in targets:
                rec["sources"]["ekimero"] = ea
                if ea and rec["audio"] is None:
                    rec["audio"] = ea
                    rec["filled_by_ekimero"] = True
                if rec["sources"]["dokobell"] and ea:
                    rec["audio"] = ea
                    rec["deduped"] = True
                if not rec["line"]:
                    rec["line"] = r.get("line", "")
        else:
            recs[("", jk)] = {
                "platform": "", "melody": mel, "line": r.get("line", ""),
                "sources": {"dokobell": None, "ekimero": ea},
                "audio": ea, "deduped": False, "filled_by_ekimero": False,
            }

    melodies = list(recs.values())
    if melodies:
        stats["stations_with_melody"] += 1
        stats["melody_records"] += len(melodies)
        for rec in melodies:
            if rec["deduped"]:
                stats["deduped_records"] += 1
            if rec["filled_by_ekimero"]:
                stats["filled_by_ekimero"] += 1
            if rec["sources"]["dokobell"] and not rec["sources"]["ekimero"]:
                stats["doc_only"] += 1
            if rec["sources"]["ekimero"] and not rec["sources"]["dokobell"]:
                stats["eki_only"] += 1
            if rec["audio"]:
                stats["with_audio"] += 1
            else:
                stats["without_audio"] += 1

    merged.append({"name": name, "operators": operators, "lines": lines,
                   "coord": coord, "melodies": melodies})

merged.sort(key=lambda x: x["name"])

# ---------- 字节级物理重复审计 ----------
hashmap = defaultdict(list)
for dp, _, fs in os.walk(os.path.join(ROOT, "songs")):
    for f in fs:
        if f.lower().endswith((".mp3", ".wav")):
            p = os.path.join(dp, f)
            hashmap[md5(p)].append(p)
byte_dups = {h: ps for h, ps in hashmap.items() if len(ps) > 1}
byte_cross = {h: ps for h, ps in byte_dups.items()
              if len(set(os.path.dirname(p) for p in ps)) > 1}

# ---------- meta ----------
meta = {
    "project": "jr-ring",
    "description": "合并 ekimero(dkst.net dokobell_melody) 与 ekimero.github.io 两源, 按 车站×站台×旋律 去重后的权威映射",
    "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
    "station_source": "https://github.com/ooep/floral-salad-8734 (data/stations.geojson)",
    "sources": {
        "dokobell": {"origin": "https://www.dkst.net/ (ssmn93/dokobell_melody)",
                     "audio_dir": "songs/dokobell_melody", "platform_granularity": True},
        "ekimero": {"origin": "https://ekimero.com + Naramsim/ekimero.github.io",
                    "audio_dir": "songs/ekimero", "platform_granularity": False,
                    "note": "线路级, 无站台号; 部分 audio 为 null(悬空引用)"},
    },
    "total_stations": len(merged),
    "stations_with_melody": stats["stations_with_melody"],
    "stations_without_melody": len(merged) - stats["stations_with_melody"],
    "melody_records": stats["melody_records"],
    "records_with_audio": stats["with_audio"],
    "records_without_audio": stats["without_audio"],
    "dedup": {
        "overlap_stations_both_sources": sum(1 for s in merged if any(r["deduped"] for r in s["melodies"])),
        "deduped_records": stats["deduped_records"],
        "dokobell_only_records": stats["doc_only"],
        "ekimero_only_records": stats["eki_only"],
        "ekimero_filled_dokobell_gaps": stats["filled_by_ekimero"],
        "byte_identical_groups_total": len(byte_dups),
        "byte_identical_files_total": sum(len(v) for v in byte_dups.values()),
        "byte_identical_cross_source_groups": len(byte_cross),
    },
    "note": "同一车站×站台×旋律两源均有音频时合并为 1 条(deduped=true), 选 ekimero 为播放文件, 两源路径均保留于 sources。磁盘音频未删除。",
}
json.dump({"meta": meta, "stations": merged}, open(M_OUT, "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)

report = {
    "generated_at": meta["generated_at"], "stats": dict(stats),
    "byte_identical_groups": {h: ps for h, ps in byte_dups.items()},
    "byte_identical_cross_source": {h: ps for h, ps in byte_cross.items()},
    "sample_deduped": [
        {"station": s["name"], "platform": r["platform"], "melody": r["melody"],
         "sources": r["sources"], "audio": r["audio"]}
        for s in merged for r in s["melodies"] if r["deduped"]
    ][:25],
}
json.dump(report, open(REPORT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

print("=== 合并完成 (v3) ===")
print("总车站:", meta["total_stations"])
print("有旋律车站:", meta["stations_with_melody"], " 无旋律:", meta["stations_without_melody"])
print("旋律记录总数:", meta["melody_records"])
print("  有音频:", stats["with_audio"], " 无音频:", stats["without_audio"])
print("去重(deduped)记录:", stats["deduped_records"],
      " 涉及车站:", meta["dedup"]["overlap_stations_both_sources"])
print("ekimero 补位 dokobell 缺音频:", stats["filled_by_ekimero"])
print("仅 dokobell:", stats["doc_only"], " 仅 ekimero:", stats["eki_only"])
print("字节级重复组:", len(byte_dups), " 跨源:", len(byte_cross))
print("输出 ->", M_OUT, " | 审计 ->", REPORT)
