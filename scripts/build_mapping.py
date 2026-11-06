#!/usr/bin/env python3
# 构建 jr-ring 的 mapping.json：覆盖我们网站全部车站，匹配到旋律的填充，否则留空
import json, re, datetime, urllib.parse

GEO = "/root/.codebuddy/artifact/stations.geojson"
DKST = "/root/.codebuddy/artifact/dkst_station_melodies.json"
OUT = "/workspace/jr-ring/mapping.json"

geo = json.load(open(GEO, encoding="utf-8"))
dkst = json.load(open(DKST, encoding="utf-8"))

# 我们网站的车站索引：站名 -> {operators, lines, coord}
idx = {}
for f in geo["features"]:
    p = f["properties"]
    name = p.get("station")
    if not name:
        continue
    op = p.get("op")
    line = p.get("line")
    coord = None
    g = f.get("geometry") or {}
    if g.get("type") == "Point" and g.get("coordinates"):
        c = g["coordinates"]
        coord = [round(c[0], 6), round(c[1], 6)]
    e = idx.setdefault(name, {"operators": set(), "lines": set(), "coord": coord})
    if op: e["operators"].add(op)
    if line: e["lines"].add(line)
    if coord and not e["coord"]:
        e["coord"] = coord

def clean_melody(s):
    s = s.split(" -->")[0].split("【未収録】")[0].strip()
    return s

# 构建映射
stations_out = []
matched = 0
for name, info in idx.items():
    entry = {
        "name": name,
        "operators": sorted(info["operators"]),
        "lines": sorted(info["lines"]),
        "coord": info["coord"],
        "melodies": [],
        "song_files": [],
    }
    if name in dkst:
        matched += 1
        for plat in dkst[name]:
            melody = clean_melody(plat.get("melody", ""))
            if not melody:
                continue
            entry["melodies"].append({
                "platform": plat.get("platform", ""),
                "melody": melody,
                "source": "https://ekimero.com/stations/" + urllib.parse.quote(name),
            })
    stations_out.append(entry)

# 按名称排序，稳定输出
stations_out.sort(key=lambda x: x["name"])

meta = {
    "project": "jr-ring",
    "description": "日本车站发车旋律(駅メロ/ステーションベル)与 jr.suki.ing(mini-japanrail-3d) 车站的映射",
    "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
    "station_source": "https://github.com/ooep/floral-salad-8734 (data/stations.geojson)",
    "melody_source": "https://ekimero.com/companies/JR%E6%9D%B1%E6%97%A5%E6%9C%AC/ + https://www.dkst.net/ (ssmn93/dokobell_melody, ssmn93/depart-melody)",
    "total_stations": len(stations_out),
    "stations_with_melody": matched,
    "stations_without_melody": len(stations_out) - matched,
    "note": "song_files 在运行 scripts/download.py 下载后填充；未匹配到的车站 melodies/song_files 为空。",
}

out = {"meta": meta, "stations": stations_out}
json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"written {OUT}")
print(f"total={meta['total_stations']} matched={matched} empty={meta['stations_without_melody']}")
# 统计有旋律的车站里，旋律总数
mel_total = sum(len(s['melodies']) for s in stations_out)
print(f"melody entries total: {mel_total}")
