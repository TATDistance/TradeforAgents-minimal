from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import List

from ai_trade_system.engine.config import load_config


def load_symbols(args: argparse.Namespace) -> List[str]:
    symbols = []
    if args.symbols:
        symbols.extend(args.symbols)

    if args.symbols_file:
        path = Path(args.symbols_file)
        if not path.exists():
            raise FileNotFoundError("股票池文件不存在: {0}".format(path))
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text or text.startswith("#"):
                    continue
                symbols.append(text)

    seen = set()
    unique = []
    for symbol in symbols:
        if symbol not in seen:
            seen.add(symbol)
            unique.append(symbol)
    return unique


def main() -> None:
    parser = argparse.ArgumentParser(description="批量调用 TradeforAgents-minimal 分析股票池。")
    parser.add_argument("--symbols", nargs="*", help="直接传入股票代码列表，例如 600028 510300 000001")
    parser.add_argument("--symbols-file", help="股票池文件，每行一个代码")
    parser.add_argument("--date", default=date.today().isoformat(), help="分析日期，默认今天")
    parser.add_argument("--mode", choices=["quick", "deep"], default="quick", help="分析模式")
    parser.add_argument("--request-timeout", type=int, default=120, help="单只股票超时秒数")
    parser.add_argument("--retries", type=int, default=1, help="单只股票重试次数")
    parser.add_argument("--direction-cache-days", type=int, default=3, help="方向缓存复用天数")
    parser.add_argument("--force-full-analysis", action="store_true", help="强制全量重跑，不复用方向缓存")
    parser.add_argument("--fail-on-any", action="store_true", help="只要有一只失败就整体返回失败")
    parser.add_argument("--dry-run", action="store_true", help="只打印命令，不实际执行")
    args = parser.parse_args()

    symbols = load_symbols(args)
    if not symbols:
        raise SystemExit("请通过 --symbols 或 --symbols-file 提供至少一个股票代码。")

    config = load_config()
    project_root = config.tradeforagents_results_dir.parent
    runner = project_root / "scripts" / "run_minimal_deepseek.sh"
    if not runner.exists():
        raise SystemExit("未找到 TradeforAgents-minimal CLI 脚本: {0}".format(runner))

    print("批量分析开始，共 {0} 只：{1}".format(len(symbols), ", ".join(symbols)), flush=True)
    failures = []
    successes = []
    for index, symbol in enumerate(symbols, start=1):
        cmd = [
            "bash",
            str(runner),
            symbol,
            args.date,
            "--mode",
            args.mode,
            "--request-timeout",
            str(args.request_timeout),
            "--retries",
            str(args.retries),
            "--direction-cache-days",
            str(args.direction_cache_days),
        ]
        if args.force_full_analysis:
            cmd.append("--force-full-analysis")
        print("[{0}/{1}] {2}".format(index, len(symbols), " ".join(cmd)), flush=True)
        if args.dry_run:
            continue
        result = subprocess.run(cmd, cwd=str(project_root))
        if result.returncode != 0:
            failures.append(symbol)
            print("[{0}/{1}] {2} 分析失败".format(index, len(symbols), symbol), flush=True)
        else:
            successes.append(symbol)
            print("[{0}/{1}] {2} 分析完成".format(index, len(symbols), symbol), flush=True)

    if failures:
        print("以下股票分析失败：{0}".format(", ".join(failures)), flush=True)
        if not successes:
            raise SystemExit(1)
        if args.fail_on_any:
            raise SystemExit(1)
        print(
            "其余股票已成功分析：{0}。流水线将继续使用成功结果。".format(", ".join(successes)),
            flush=True,
        )

    print("批量分析完成。接下来可以运行：", flush=True)
    print("python3 -m ai_trade_system.scripts.run_daily_plan --limit {0}".format(len(successes) or len(symbols)), flush=True)


if __name__ == "__main__":
    main()
