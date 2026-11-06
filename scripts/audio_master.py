#!/usr/bin/env python3.11
"""
音质提升链路 (非语音降噪):
  1) adeclip        : 修复源文件自带的削顶(clipping)失真
  2) highpass f=20  : 去直流/超低频
  3) highshelf +1.5dB @10kHz : 轻提高频清晰度(air)
  4) 两遍 loudnorm  : 测量 -> 线性归一到 -14 LUFS / TP -1.0 (统一饱满电平, 保留动态)
  输出 24bit 无损 WAV, 采样率保持原片。
用法: python3.11 audio_master.py <in> <out>
"""
import subprocess, json, re, sys, os

def measure(path):
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", path,
         "-af", "loudnorm=I=-14:TP=-1.0:LRA=7:print_format=json",
         "-f", "null", "-"],
        capture_output=True, text=True)
    m = re.search(r'\{[^{}]*"input_i"[^{}]*\}', r.stderr, re.S)
    return json.loads(m.group(0))

def run(cmd):
    subprocess.run(cmd, check=True, capture_output=True)

def process(inp, outp):
    mid = outp + ".mid.wav"
    # 第一步: 削顶修复 + 去直流 + 清晰度
    run(["ffmpeg", "-y", "-hide_banner", "-i", inp,
         "-af", "adeclip,highpass=f=20,highshelf=g=1.5:f=10000",
         "-c:a", "pcm_s24le", mid])
    m = measure(mid)
    af = (
        f"loudnorm=I=-14:TP=-1.0:LRA=7:"
        f"measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
        f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
        f"offset=0.0"
    )
    run(["ffmpeg", "-y", "-hide_banner", "-i", mid,
         "-af", af, "-c:a", "pcm_s24le", outp])
    os.remove(mid)

if __name__ == "__main__":
    inp, outp = sys.argv[1], sys.argv[2]
    process(inp, outp)
    print(f"[done] -> {outp}")
