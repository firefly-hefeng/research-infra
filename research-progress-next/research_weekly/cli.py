import argparse
import json
import os
import sys
from pathlib import Path
from .core import (FIELDS, atomic_write, child, init_dirs, load_config, locked, now,
                   read_text, report_markdown, select_week, write_json)
from . import summaries


def demo(cfg):
    if not cfg.get("demo"):
        raise ValueError("demo 命令仅允许演示配置")
    init_dirs(cfg, provision_members=True)
    current, previous = select_week(cfg, "current"), select_week(cfg, "previous")
    examples = {
        "lin": {"done": "完成语音样本的字段检查，统一采样率记录。\n整理预处理脚本的输入输出约定。", "results": "已生成数据核对清单；仍有少量录音缺少设备信息。\n本周尚未进行模型性能对比。", "blockers": "设备型号字段需要采集同学补充。", "next": "补齐字段后，开展小批量特征提取验证。"},
        "chen": {"done": "完成基线模型训练配置梳理。\n核对评测数据划分，记录复现实验步骤。", "results": "训练配置已归档，可按同一参数复跑。\n当前结果仅用于流程检查，尚未形成性能结论。", "blockers": "正式对比实验依赖特征数据准备完成。", "next": "使用固定数据快照运行基线，记录完整指标和失败样本。"},
        "zhou": {"done": "整理新人入门资料与周报填写规范。", "results": "明确了数据、配置和研究结论的记录方式。", "blockers": "未说明。", "next": "补充采集流程说明。"}}
    for m in cfg["members"]:
        fields = examples.get(m["id"], examples["zhou"])
        weeks = [previous] + ([current] if m["id"] != "zhou" else [])
        for week in weeks:
            p = child(cfg["roots"]["members"], m["id"], "reports", week + ".md")
            if not p.exists():
                atomic_write(p, report_markdown(m["name"], week, fields))
        p = child(cfg["roots"]["members"], m["id"], "files", "研究备忘.md")
        if not p.exists():
            atomic_write(p, f"# {m['name']}的研究备忘\n\n这是一份个人文件，不参与每周汇总。其他成员无法通过工作台访问。\n\n## 记录建议\n\n- 研究问题和待验证的假设\n- 实验配置与数据版本\n- 尚未准备纳入周报的个人笔记\n")
    docs = {
        "01-欢迎加入.md": "# 欢迎加入研究组\n\n从研究问题出发，留下可以接续的记录。\n\n## 第一天\n\n- 了解当前研究方向与负责人。\n- 确认自己可以使用的数据和计算资源。\n- 打开个人进展上传，按模板记录第一周计划。\n\n## 你的三个空间\n\n个人进展上传将标准周报存入已有成员目录；团队进度展示共享总结；团队知识库保存基础说明。\n\n## 团队约定\n\n不上传受试者身份、账号密钥等敏感信息。已提交周报的内容会被智能体读取，并可能出现在团队总结中。\n",
        "02-周报怎么写.md": "# 一份可接续的科研周报\n\n写清楚做了什么、得到了什么，以及还缺什么。\n\n## 本周完成\n\n描述实际开展的工作，区分已完成与仍在进行的事项。\n\n## 结果与证据\n\n写明数据版本、配置、指标来源和可核对的产物。没有结论时如实说明。\n\n## 问题与阻塞\n\n说明依赖、失败和需要协助的事项。\n\n## 下周计划\n\n写明下一步验证的问题和所需条件。\n\n## 提交说明\n\n四个栏目必须完整填写；未知信息写“未说明”。下载对应成员和周次的模板，填写后提交。同周已有不同内容的报告需联系维护人员更正。\n",
        "03-实验记录基础.md": "# 实验记录的基本要素\n\n让另一位同学能够理解并复跑你的实验。\n\n## 运行前\n\n- 记录研究问题、数据快照和划分。\n- 保存代码版本、环境、参数和随机种子。\n- 明确评测协议和资源预算。\n\n## 运行后\n\n- 保留输出、指标、失败项和日志。\n- 区分观察事实、个人解释和待验证的判断。\n- 用同一协议比较结果，保留负结果。\n"}
    for filename, text in docs.items():
        p = child(cfg["roots"]["knowledge"], filename)
        if not p.exists():
            atomic_write(p, text)
    for week in (previous, current):
        summaries.summarize(cfg, week, "extractive")
    print(f"演示数据已就绪（不会覆盖已有报告）。周次：{previous}、{current}。\n演示成员目录：lin / chen / zhou；无需登录\n这是虚构演示资料，汇总为规则摘录。")


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description="科研周报文件系统与汇总工具")
    parser.add_argument("--config", help="JSON 配置路径；也可使用 RESEARCH_CONFIG")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    sub.add_parser("demo")
    serve = sub.add_parser("serve"); serve.add_argument("--host", default="127.0.0.1"); serve.add_argument("--port", type=int, default=8765)
    prepare = sub.add_parser("prepare"); prepare.add_argument("--week", default="previous")
    publish = sub.add_parser("publish"); publish.add_argument("--job", required=True); publish.add_argument("--result", required=True); publish.add_argument("--force", action="store_true")
    summary = sub.add_parser("summarize"); summary.add_argument("--week", default="previous"); summary.add_argument("--mode", choices=["extractive", "agent", "api"]); summary.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        cfg = load_config(args.config); init_dirs(cfg, provision_members=args.cmd == "init")
        if args.cmd == "init":
            print("已为配置名单中的成员建立目录。上传接口只接收已有成员目录，不会自动开户。")
        elif args.cmd == "demo":
            demo(cfg)
        elif args.cmd == "serve":
            if (cfg.get("demo") or cfg["security"].get("transport") == "ssh-tunnel") and args.host not in ("127.0.0.1", "localhost", "::1"):
                raise ValueError("演示或 SSH 隧道环境只允许绑定本机地址")
            from .app import create_app
            from waitress import serve as start
            print(f"科研周记运行于 http://{args.host}:{args.port}", flush=True)
            start(create_app(args.config), host=args.host, port=args.port, threads=8, max_request_body_size=100_000)
        elif args.cmd == "prepare":
            job, manifest = summaries.prepare(cfg, args.week)
            print(json.dumps({"job": str(job), "week": manifest["week"], "submitted": len(manifest["reports"]), "missing": len(manifest["missing"]), "prompt": str(job / 'prompt.txt')}, ensure_ascii=False, indent=2))
        elif args.cmd == "publish":
            job = Path(args.job).absolute()
            if cfg["roots"]["state"] / "jobs" != job.parent:
                raise ValueError("job 必须来自当前配置的私有 jobs 目录")
            manifest = json.loads(read_text(job / "manifest.json", 2_000_000))
            result = json.loads(read_text(Path(args.result), 2_000_000))
            doc, changed = summaries.publish(cfg, manifest, result, "agent", args.force)
            write_json(job / "status.json", {"status": "published" if changed else "unchanged", "revision": doc["revision"]})
            print(f"{doc['week']}：{'已发布' if changed else '内容未变'}，版本 {doc['revision']}")
        elif args.cmd == "summarize":
            doc, changed = summaries.summarize(cfg, args.week, args.mode, args.force)
            print(f"{doc['week']}：{'已发布' if changed else '内容未变'}，版本 {doc['revision']}；{doc['engine_label']}")
    except (ValueError, OSError, KeyError) as exc:
        print(f"失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
