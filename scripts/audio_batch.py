#!/usr/bin/env python3.11
"""
批量音质提升: 遍历 songs/dokobell_melody 与 songs/ekimero 全部音频,
应用 audio_master 同款链路 (adeclip 削顶修复 + 去直流 + 高频清晰度 + 两遍响度归一),
输出 320kbps MP3 到 songs/<子目录>/<同名>.mp3。
原 songs/ 不动。支持断点续传(已存在且>1KB 跳过)。
用法:
  python3.11 audio_batch.py            # 全量
  python3.11 audio_batch.py --max 5    # 只处理前5个(测试)
  python3.11 audio_batch.py --sub dokobell_melody   # 只处理某子目录
"""
import subprocess, json, re, os, sys, argparse, tempfile

ROOT = "/workspace/jr-ring"
SRC_PARENT = "songs"
SUBS = ["dokobell_melody", "ekimero"]
OUT_ROOT = os.path.join(ROOT, "songs")
TMP = "/tmp/enh_mid"

def measure(path):
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", path,
         "-af", "loudnorm=I=-14:TP=-1.0:LRA=7:print_format=json",
         "-f", "null", "-"],
        capture_output=True, text=True)
    m = re.search(r'\{[^{}]*"input_i"[^{}]*\}', r.stderr, re.S)
    return json.loads(m.group(0))

def process(inp, outp):
    os.makedirs(os.path.dirname(outp), exist_ok=True)
    mid = os.path.join(TMP, os.path.basename(outp) + ".mid.wav")
    os.makedirs(TMP, exist_ok=True)
    # 1) 削顶修复 + 去直流 + 清晰度 -> 临时 24bit wav
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-i", inp,
                    "-af", "adeclip,highpass=f=20,highshelf=g=1.5:f=10000",
                    "-c:a", "pcm_s24le", mid], check=True, capture_output=True)
    m = measure(mid)
    af = (f"loudnorm=I=-14:TP=-1.0:LRA=7:"
          f"measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
          f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
          f"offset=0.0")
    # 2) 应用响度归一 -> 320k mp3
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-i", mid,
                    "-af", af, "-c:a", "libmp3lame", "-b:a", "320k", outp],
                   check=True, capture_output=True)
    os.remove(mid)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=0, help="最多处理N个(测试)")
    ap.add_argument("--sub", default="", help="只处理指定子目录")
    args = ap.parse_args()

    subs = [args.sub] if args.sub else SUBS
    files = []
    for sub in subs:
        sp = os.path.join(ROOT, SRC_PARENT, sub)
        for f in sorted(os.listdir(sp)):
            if f.lower().endswith((".mp3", ".wav")):
                files.append((sub, f))
    if args.max:
        files = files[:args.max]

    done = skip = fail = 0
    total = len(files)
    for i, (sub, f) in enumerate(files, 1):
        base = os.path.splitext(f)[0]
        inp = os.path.join(ROOT, SRC_PARENT, sub, f)
        outp = os.path.join(OUT_ROOT, sub, base + ".mp3")
        if os.path.exists(outp) and os.path.getsize(outp) > 1024:
            skip += 1
            continue
        try:
            process(inp, outp)
            done += 1
        except Exception as e:
            fail += 1
            print(f"[FAIL] {sub}/{f}: {e}", flush=True)
        if i % 25 == 0 or i == total:
            print(f"[progress] {i}/{total} 完成={done} 跳过={skip} 失败={fail}", flush=True)
    print(f"[summary] 总={total} 新处理={done} 跳过={skip} 失败={fail}", flush=True)

if __name__ == "__main__":
    main()
