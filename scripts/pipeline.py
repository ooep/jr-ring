#!/usr/bin/env python3.11
"""全量音质提升流水线(串行, 可重入/断点续传):
1. 批量音质提升全部音频 -> songs/ (audio_batch 自带续传)
2. 更新 mapping.json 路径到 songs/ (.wav->.mp3 归一)
3. 校验所有 audio 路径存在 (应=0 缺失)
4. git 提交并推送
日志同时写 /tmp/pipeline.log 与 stdout。
"""
import subprocess, sys, os, datetime

ROOT = "/workspace/jr-ring"
LOG = "/tmp/pipeline.log"

def log(msg):
    t = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{t}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def run(cmd, label):
    log(f"== {label}: {' '.join(cmd)}")
    r = subprocess.run(cmd, cwd=ROOT)
    if r.returncode != 0:
        log(f"!! {label} 返回码 {r.returncode}")
        return False
    return True

def main():
    # 1) 批量处理 (续传)
    log("STEP1 批量音质提升开始")
    if not run([sys.executable, "scripts/audio_batch.py"], "audio_batch"):
        log("STEP1 批量失败, 中止"); return
    log("STEP1 批量完成")

    # 2) 更新映射路径
    log("STEP2 更新 mapping.json 路径")
    if not run([sys.executable, "scripts/update_mapping_paths.py"], "update_mapping"):
        log("STEP2 映射更新失败, 中止"); return
    log("STEP2 映射更新完成")

    # 3) 校验
    log("STEP3 校验音频文件存在")
    chk = subprocess.run([sys.executable, "-c",
        "import json,os;m=json.load(open('mapping.json',encoding='utf-8'));"
        "miss=[r['audio'] for st in m['stations'] for r in st.get('melodies',[]) "
        "if r.get('audio') and not os.path.exists(r['audio'])];"
        "print('MISS',len(miss));[print(' ',x) for x in miss[:20]]"],
        cwd=ROOT, capture_output=True, text=True)
    log(chk.stdout.strip())
    if "MISS 0" not in chk.stdout:
        log("STEP3 校验失败(有缺失), 中止推送"); return
    log("STEP3 校验通过")

    # 4) git 提交推送
    log("STEP4 git 提交并推送")
    run(["gh", "auth", "setup-git"], "gh_setup")
    run(["git", "add", "-A"], "git_add")
    r = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True)
    if not r.stdout.strip():
        log("STEP4 无变更, 跳过提交"); return
    run(["git", "commit", "-q", "-m",
         "全量音质提升: 1313个音频经削顶修复+响度归一(-14LUFS)输出320k MP3到songs/, 更新mapping路径"],
        "git_commit")
    if not run(["git", "push", "origin", "master"], "git_push"):
        log("STEP4 推送失败, 请手动重试"); return
    log("STEP4 推送完成")
    log("PIPELINE_DONE")

if __name__ == "__main__":
    main()
