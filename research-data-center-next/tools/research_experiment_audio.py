"""Fixed, read-only paired signal experiment on the verified MDVR-KCL distribution."""
from __future__ import annotations

import hashlib
import math
import os
import re
import stat
import struct
import threading
import zipfile
from collections import Counter
from contextlib import contextmanager
from statistics import median


RECORD = "reczz28S4ElbQPb1"
ARCHIVE = "/data/share/datasets/MDVR-KCL/26_29_09_2017_KCL.zip"
SIZE = 606144431
SHA256 = "45c43cdfa5d078833a6ac27574c471c9ca34d4cd4dea5877f31ebe93b1b5edf6"
SOURCE = {"id": RECORD, "title": "MDVR-KCL", "url": "https://zenodo.org/records/2867216",
          "credit": "Hagen Jaeger, Dhaval Trivedi, Michael Stadtschnitzer", "license": "CC BY 4.0"}
PARAMETERS = {"prefix_seconds": 2, "frame_ms": 20, "energy_gates_dbfs": [-50, -40],
              "crop_seconds": [10, 30], "expected_wav_files": 73, "archive_sha256": SHA256}
RAV_ARCHIVE = "/data/share/datasets/RAVDESS-Speech/noncommercial-originals/Audio_Speech_Actors_01-24.zip"
RAV_SHA256 = "5d208e01632cc3e5242106fa2af3273e6dc5239fb8143131979ac74c4aa40657"
RAV_SOURCE = {"id": "reczz28S4ElbQROC", "title": "RAVDESS Speech", "url": "https://zenodo.org/records/1188976",
              "credit": "Steven R. Livingstone, Frank A. Russo", "license": "CC BY-NC-SA 4.0 · 实验室获准的非商业研究"}
SPLIT = {"folds": 6, "seed": "rmp-ravdess-speaker-v1", "expected_recordings": 1440, "archive_sha256": RAV_SHA256}
_verified = {}
_lock = threading.Lock()


def _identity(file):
    st = os.fstat(file.fileno())
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns


@contextmanager
def verified_archive(path, size, sha, *, member_only=False):
    # Path, version and checksum are operator-maintained constants, never request parameters.
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0))
    with os.fdopen(fd, "rb") as stream:
        identity = _identity(stream)
        st = os.fstat(stream.fileno())
        if not stat.S_ISREG(st.st_mode) or identity[2] != size:
            raise ValueError("共享原件类型或大小与已核发行包不符。")
        if member_only and (os.name != "posix" or os.geteuid() == 0 or
                            (os.geteuid() != st.st_uid and st.st_gid not in {os.getegid(), *os.getgroups()})):
            raise PermissionError("请从具有该原件组权限的非商业研究账户运行。")
        with _lock:
            if _verified.get(sha) != identity:
                h = hashlib.sha256()
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    h.update(block)
                if _identity(stream) != identity or h.hexdigest() != sha:
                    raise ValueError("共享原件校验失败，请复核登记版本。")
                _verified[sha] = identity
        with zipfile.ZipFile(stream) as archive:
            yield archive
        if _identity(stream) != identity:
            raise ValueError("原件在分析期间发生变化，请重新运行。")


def read_wav_prefix(archive, entry):
    """Read RIFF PCM or float data without extracting a file or seeking across a compressed recording."""
    with archive.open(entry) as f:
        if f.read(4) != b"RIFF" or len(f.read(4)) != 4 or f.read(4) != b"WAVE":
            raise ValueError("非 RIFF/WAVE")
        position = 12
        fmt = None
        while position < 128 * 1024:
            header = f.read(8)
            if len(header) != 8:
                break
            tag, length = struct.unpack("<4sI", header)
            position += 8
            if tag == b"data" and fmt:
                codec, channels, rate, align, bits = fmt
                if not (1 <= channels <= 8 and 1000 <= rate <= 192000 and align == channels * (bits // 8)):
                    raise ValueError("声道、采样率或帧大小不支持")
                if length <= 0 or position + length > entry.file_size or length % align:
                    raise ValueError("PCM 数据长度无效")
                size = min(length, rate * align * PARAMETERS["prefix_seconds"])
                if size > 2 * 1024 * 1024:
                    raise ValueError("超出每条录音采样预算")
                raw = f.read(size)
                if len(raw) != size:
                    raise ValueError("PCM 片段不完整")
                return codec, channels, rate, bits, length / (rate * align), raw
            padded = length + (length & 1)
            if position + padded > 128 * 1024:
                break
            payload = f.read(padded)
            if len(payload) != padded:
                break
            position += padded
            if tag == b"fmt " and length >= 16:
                codec, channels, rate, _, align, bits = struct.unpack_from("<HHIIHH", payload)
                if codec == 65534 and length >= 40:
                    guid = payload[24:40]
                    if guid[2:] == bytes.fromhex("000000001000800000aa00389b71"):
                        codec = int.from_bytes(guid[:2], "little")
                if not ((codec == 1 and bits in (8, 16, 24, 32)) or (codec == 3 and bits in (32, 64))):
                    raise ValueError("不支持的音频编码")
                fmt = codec, channels, rate, align, bits
    raise ValueError("未找到可读的短 WAV 头")


def frame_powers(codec, channels, rate, bits, raw):
    """Mean squared normalized amplitude across all channel samples, per non-overlapping frame."""
    samples = max(1, round(rate * PARAMETERS["frame_ms"] / 1000)) * channels
    step = samples * (bits // 8)
    scale = 1 if codec == 3 else 2 ** (bits - 1)
    result = []
    for start in range(0, len(raw) - step + 1, step):
        frame = raw[start:start + step]
        if codec == 1 and bits == 24:
            values = (int.from_bytes(frame[i:i + 3], "little", signed=True) for i in range(0, step, 3))
        elif codec == 1 and bits == 8:
            values = (s - 128 for s in frame)
        else:
            code = {16: "h", 32: "i"}[bits] if codec == 1 else {32: "f", 64: "d"}[bits]
            values = struct.unpack(f"<{samples}{code}", frame)
        power = sum(x * x for x in values) / (samples * scale * scale)
        if not math.isfinite(power):
            raise ValueError("音频样本含非有限数值")
        result.append(power)
    return result


def measure(archive):
    entries = [i for i in archive.infolist() if not i.is_dir() and i.filename.casefold().endswith(".wav")]
    if len(entries) != PARAMETERS["expected_wav_files"] or len({i.filename for i in entries}) != len(entries):
        raise ValueError("录音条目数或唯一性与发行清单不符。")
    durations, deltas, retained = [], [], [0, 0]
    rates, channels, errors = Counter(), Counter(), Counter()
    count_frames = 0
    changed = 0
    for item in sorted(entries, key=lambda i: i.filename):
        try:
            codec, nc, hz, bits, duration, raw = read_wav_prefix(archive, item)
            powers = frame_powers(codec, nc, hz, bits, raw)
            if not powers:
                raise ValueError("不足一个完整分析帧")
        except ValueError as exc:
            errors[str(exc)] += 1
            continue
        durations.append(duration)
        rates[hz] += 1
        channels[nc] += 1
        counts = [sum(p >= 10 ** (threshold / 10) for p in powers) for threshold in PARAMETERS["energy_gates_dbfs"]]
        for i, count in enumerate(counts):
            retained[i] += count
        count_frames += len(powers)
        changed += counts[0] != counts[1]
        deltas.append(100 * (counts[0] - counts[1]) / len(powers))
    metrics = {"wav_files": len(entries), "analyzed_recordings": len(durations), "exclusions": dict(errors),
               "sample_rates_hz": dict(rates), "channels": dict(channels), "frames": count_frames}
    if not durations:
        return metrics
    total = sum(durations)
    metrics.update(
        recorded_seconds=round(total, 3), median_recording_seconds=round(median(durations), 3),
        retained_frame_pct={str(t): round(100 * n / count_frames, 3) for t, n in zip(PARAMETERS["energy_gates_dbfs"], retained)},
        changed_recordings=changed, paired_median_loss_pp=round(median(deltas), 3),
        crop_retained_duration_pct={str(s): round(100 * sum(min(s, d) for d in durations) / total, 3)
                                   for s in PARAMETERS["crop_seconds"]},
    )
    return metrics


def analyze():
    base = {"sources": [SOURCE], "parameters": dict(PARAMETERS),
            "limitations": ["仅分析这个发行包。统计单位为录音，未按参与者去重。",
                            "能量门限仅作用于各录音开头最多两秒。保留比例不代表全段语音比例或人声检测准确率。",
                            "截取覆盖量按 WAV 原始时长计算。未测试转录质量、模型性能或临床效度。"]}
    try:
        with verified_archive(ARCHIVE, SIZE, SHA256) as archive:
            m = measure(archive)
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as exc:
        reason = str(exc) if type(exc) is ValueError else "共享发行包无法读取或解码，请核对挂载、读取权限与版本。"
        return {**base, "status": "unavailable", "metrics": {}, "observations": [reason]}
    if not m["analyzed_recordings"]:
        return {**base, "status": "unavailable", "metrics": m, "observations": ["没有取得可用于两种门限配对分析的录音。"]}
    return {**base, "status": "partial" if m["exclusions"] else "completed", "metrics": m, "observations": [
        f"共同分析 {m['analyzed_recordings']}/{m['wav_files']} 条录音，共 {m['frames']} 个短时帧。"
        f"门限从 −50 提至 −40 dBFS 后，{m['changed_recordings']} 条录音的保留帧数发生变化，"
        f"逐录音保留率降幅中位数为 {m['paired_median_loss_pp']} 个百分点。",
        f"从每条录音起点截取 10 秒、30 秒，分别覆盖样本总时长的 {m['crop_retained_duration_pct']['10']}% 和 {m['crop_retained_duration_pct']['30']}%。"
    ], "next": "可按受试者及录音任务分层，比较整段不同位置的窗口，并用人工标注核对低能量帧中的有效语音。"}


def speaker_splits(names):
    """Counterfactual split assignment on the *same* real recordings, without fitting a model."""
    rows = []
    for path in names:
        filename = path.rsplit("/", 1)[-1].lower()
        if not filename.endswith(".wav") or path.startswith("__MACOSX/"):
            continue
        match = re.fullmatch(r"03-01-(0[1-8])-0[12]-0[12]-0[12]-(0[1-9]|1[0-9]|2[0-4])\.wav", filename)
        if not match:
            raise ValueError("语音文件名与发布方七段编码不一致。")
        emotion, actor = match.groups()
        rows.append((filename, actor, emotion))
    actors = sorted({r[1] for r in rows})
    if len(rows) != SPLIT["expected_recordings"] or len({r[0] for r in rows}) != len(rows) or len(actors) != 24:
        raise ValueError("有效试次或演员数与已核发行清单不符。")
    def seeded(value):
        return hashlib.sha256((SPLIT["seed"] + "/" + value).encode("ascii")).hexdigest()
    k = SPLIT["folds"]
    actors_by_fold = {a: i % k for i, a in enumerate(sorted(actors, key=seeded))}
    folds = {"recording": [[] for _ in range(k)], "speaker": [[] for _ in range(k)]}
    total_labels = Counter(r[2] for r in rows)
    for i, row in enumerate(sorted(rows, key=lambda r: seeded(r[0]))):
        folds["recording"][i % k].append(row)
        folds["speaker"][actors_by_fold[row[1]]].append(row)
    measures = {}
    for mode, groups in folds.items():
        seen = 0
        deviations = []
        fold_sizes = []
        for i, test in enumerate(groups):
            train_actors = {r[1] for j, g in enumerate(groups) if j != i for r in g}
            seen += sum(r[1] in train_actors for r in test)
            labels = Counter(r[2] for r in test)
            fold_sizes.append(len(test))
            deviations.extend(abs(labels[c] / len(test) - n / len(rows)) * 100 for c, n in total_labels.items())
        measures[mode] = {"seen_actor_recordings": seen, "seen_actor_pct": round(100 * seen / len(rows), 3),
                          "max_emotion_share_deviation_pp": round(max(deviations), 3), "fold_sizes": fold_sizes}
    return {"recordings": len(rows), "actors": len(actors), "emotion_categories": len(total_labels), **measures}


def analyze_splits():
    base = {"parameters": dict(SPLIT), "sources": [RAV_SOURCE], "limitations": [
        "分析对象是固定台词的演员语音，只比较拆分策略产生的说话人重叠及类别比例。",
        "按演员隔离不会消除录制环境、台词或语言等其他混杂；本实验没有估计情绪识别性能。"]}
    try:
        with verified_archive(RAV_ARCHIVE, 208468073, RAV_SHA256, member_only=True) as archive:
            metrics = speaker_splits(archive.namelist())
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as exc:
        reason = str(exc) if type(exc) is ValueError else "获准的普通成员进程未能读取非商业语音包，请核对挂载和读取组。"
        return {**base, "status": "unavailable", "metrics": {}, "observations": [reason]}
    return {**base, "status": "completed", "metrics": metrics, "observations": [
        f"同一批 {metrics['recordings']} 条录音、{metrics['actors']} 位演员，在六折对照中，按录音拆分时有 "
        f"{metrics['recording']['seen_actor_pct']}% 的测试录音在训练集中出现过同一演员，按演员拆分时为 {metrics['speaker']['seen_actor_pct']}%。",
        f"两种拆分下，单折情绪类别占比偏离全库比例最多分别为 {metrics['recording']['max_emotion_share_deviation_pp']} 和 "
        f"{metrics['speaker']['max_emotion_share_deviation_pp']} 个百分点。"],
        "next": "如要测试跨说话人的情绪识别，可固定同一组演员互斥折，在相同训练预算下比较基线并逐折报告性能。"}
