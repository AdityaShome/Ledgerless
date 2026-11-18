"""Turn results/*.csv into tables (results/tables.md) and figures (results/figs/*.png).

Reads only the CSVs written by bench.run; nothing here changes a number.
    python -m bench.metrics
"""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

RESULTS = Path(__file__).resolve().parent.parent / "results"
FIGS = RESULTS / "figs"
MAIN = ("default_sdk", "request_id", "saga", "temporal_bridge", "ours")
ORDER_SC = ["F0_clean", "F1_crash_after_effect", "F2_receipt_lost", "F3_duplicate_delivery",
            "F4_replica_failover", "F5_replan_on_replay", "F6_partition_transient",
            "F6_partition_permanent", "F7_forged_receipt", "F8_upstream_abort"]
COLORS = {"default_sdk": "#8a8a8a", "request_id": "#d98e04", "saga": "#7b61c4",
          "temporal_bridge": "#2a7fbf", "ours": "#1b9e77", "ours_fine": "#c4402f",
          "ours_fine_persist": "#e377c2", "ours_medium_persist": "#17becf"}


def load(name: str) -> list[dict]:
    with open(RESULTS / name, newline="") as f:
        return list(csv.DictReader(f))


def num(x: str) -> float:
    return float(x) if x != "" else float("nan")


def pooled(rows: list[dict], key: str, **flt) -> float:
    """Sum of `key` over matching cells divided by total runs (pooled over depth/fanout)."""
    sel = [r for r in rows if all(r[k] == v for k, v in flt.items())]
    n = sum(num(r["n"]) for r in sel)
    if key.endswith(("_mean", "_p50", "_p95")):  # per-cell means: weight by runs per cell
        return sum(num(r[key]) * num(r["n"]) for r in sel) / n
    return sum(num(r[key]) for r in sel) / n


def md_table(head: list[str], body: list[list[str]]) -> str:
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(r) + " |" for r in body]
    return "\n".join(out)


def fig_duplicates(grid: list[dict]) -> None:
    fig, ax = plt.subplots(figsize=(10, 4.2))
    w = 0.16
    for i, s in enumerate(MAIN):
        ys = [100 * pooled(grid, "dup_runs", system=s, scenario=sc) for sc in ORDER_SC]
        ax.bar([x + (i - 2) * w for x in range(len(ORDER_SC))], ys, w, label=s,
               color=COLORS[s])
    ax.set_xticks(range(len(ORDER_SC)))
    ax.set_xticklabels([s.split("_")[0] + ("-perm" if "permanent" in s else "")
                        for s in ORDER_SC])
    ax.set_ylabel("% of runs with a duplicate effect")
    ax.set_title("Duplicate effects by scenario (pooled over depth and fan-out)")
    ax.set_ylim(0, 118)
    ax.legend(ncol=5, fontsize=8, loc="upper center")
    fig.tight_layout()
    fig.savefig(FIGS / "duplicates_by_scenario.png", dpi=150)
    plt.close(fig)


def fig_sweep(sweep: list[dict]) -> None:
    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    for s in dict.fromkeys(r["system"] for r in sweep):
        rows = sorted((r for r in sweep if r["system"] == s), key=lambda r: float(r["p_replan"]))
        ax.plot([float(r["p_replan"]) for r in rows],
                [100 * num(r["dup_runs"]) / num(r["n"]) for r in rows], marker="o",
                label=s, color=COLORS.get(s))
    ax.set_xlabel("p_replan (chance a retry re-plans the request)")
    ax.set_ylabel("% of runs with a duplicate effect")
    ax.set_title("C1: duplicates vs re-planning (F5, depth 3)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(FIGS / "c1_replan_sweep.png", dpi=150)
    plt.close(fig)


def fig_rq4(rq4: list[dict]) -> None:
    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    x = range(len(rq4))
    ax.bar([i - 0.2 for i in x], [100 * num(r["false_dedup_rate"]) for r in rq4], 0.4,
           label="false dedup (legit effect blocked)", color="#d98e04")
    ax.bar([i + 0.2 for i in x], [100 * num(r["missed_dedup_rate"]) for r in rq4], 0.4,
           label="missed dedup (re-planned duplicate ran)", color="#c4402f")
    ax.set_xticks(list(x))
    ax.set_xticklabels([r["policy"] for r in rq4])
    ax.set_ylabel("%")
    ax.set_title("RQ4: digest granularity trade-off")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(FIGS / "rq4_granularity.png", dpi=150)
    plt.close(fig)


def fig_overhead(grid: list[dict]) -> None:
    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    systems = ("default_sdk", "request_id", "saga", "temporal_bridge", "ours", "ours_fine_persist")
    base = pooled(grid, "msgs_mean", system="default_sdk", scenario="F0_clean")
    ys = [pooled(grid, "msgs_mean", system=s, scenario="F0_clean") / base for s in systems]
    ax.bar(systems, ys, color=[COLORS.get(s, "#555") for s in systems])
    ax.set_ylabel("messages / default SDK (clean run)")
    ax.set_title("C4: message overhead, no faults")
    plt.setp(ax.get_xticklabels(), rotation=25, ha="right", fontsize=8)
    fig.tight_layout()
    fig.savefig(FIGS / "c4_overhead.png", dpi=150)
    plt.close(fig)


def tables(grid: list[dict], sweep: list[dict], rq4: list[dict]) -> str:
    sc_short = [s.split("_")[0] + ("p" if "permanent" in s else "") for s in ORDER_SC]
    parts = ["# Result tables (generated by bench.metrics; do not edit)\n"]

    def dup_table(systems, title, key, fmt):
        body = [[s] + [fmt(pooled(grid, key, system=s, scenario=sc)) for sc in ORDER_SC]
                for s in systems]
        return f"## {title}\n\n" + md_table(["system"] + sc_short, body) + "\n"

    allsys = sorted({r["system"] for r in grid})
    parts.append(dup_table(allsys, "% of runs with a duplicate effect", "dup_runs",
                           lambda v: f"{100 * v:.1f}"))
    parts.append(dup_table(allsys, "% of runs with a LOST effect (missing and not flagged)",
                           "lost_runs", lambda v: f"{100 * v:.1f}"))
    parts.append(dup_table(allsys, "% of runs completed", "completed", lambda v: f"{100 * v:.0f}"))
    parts.append(dup_table(allsys, "% of runs quarantined", "quarantined",
                           lambda v: f"{100 * v:.0f}"))
    f7 = [[s, "n/a" if s in ("default_sdk", "saga") else
           f"{100 * pooled(grid, 'forged_accepted', system=s, scenario='F7_forged_receipt'):.0f}"]
          for s in allsys]
    parts.append("## F7: % of runs where a forged receipt was accepted\n\n"
                 + md_table(["system", "accepted"], f7) + "\n")
    f8 = [[s, f"{100 * pooled(grid, 'residual_runs', system=s, scenario='F8_upstream_abort'):.0f}"]
          for s in allsys]
    parts.append("## F8: % of runs with effects left standing after the abort\n\n"
                 + md_table(["system", "residual"], f8) + "\n")

    ov = []
    base_m = pooled(grid, "msgs_mean", system="default_sdk", scenario="F0_clean")
    base_b = pooled(grid, "bytes_mean", system="default_sdk", scenario="F0_clean")
    for s in allsys:
        m = pooled(grid, "msgs_mean", system=s, scenario="F0_clean")
        b = pooled(grid, "bytes_mean", system=s, scenario="F0_clean")
        rb = pooled(grid, "recovery_bytes_mean", system=s, scenario="F0_clean")
        pb = pooled(grid, "plan_bytes_mean", system=s, scenario="F0_clean")
        ov.append([s, f"{m:.1f}", f"{m / base_m:.2f}x", f"{b:.0f}", f"{b / base_b:.2f}x",
                   f"{rb:.0f}", f"{pb:.0f}"])
    parts.append("## Overhead, fault-free run (pooled over depth and fan-out)\n\n" + md_table(
        ["system", "msgs", "vs default", "bytes", "vs default", "recovery bytes",
         "plan bytes stored"], ov) + "\n")

    lat = [[s] + [f"{pooled(grid, 'msgs_p50', system=s, scenario=sc) * 1:.0f}/"
                  f"{max(num(r['msgs_p95']) for r in grid if r['system'] == s and r['scenario'] == sc):.0f}"
                  for sc in ("F0_clean", "F1_crash_after_effect", "F5_replan_on_replay")]
           for s in MAIN]
    parts.append("## Message-count latency proxy under faults (p50/p95 messages per run)\n\n"
                 "Messages stand in for latency (the engine is synchronous). p50 is the mean of "
                 "cell medians, p95 the worst cell p95.\n\n"
                 + md_table(["system", "F0", "F1", "F5"], lat) + "\n")

    sw = []
    for s in dict.fromkeys(r["system"] for r in sweep):
        rows = sorted((r for r in sweep if r["system"] == s), key=lambda r: float(r["p_replan"]))
        sw.append([s] + [f"{100 * num(r['dup_runs']) / num(r['n']):.1f}" for r in rows])
    ps = sorted({float(r["p_replan"]) for r in sweep})
    parts.append("## C1: % of runs with a duplicate vs p_replan (F5, depth 3)\n\n"
                 + md_table(["system"] + [f"p={p}" for p in ps], sw) + "\n")

    parts.append("## RQ4: granularity\n\n" + md_table(
        ["policy", "false dedup %", "missed dedup %"],
        [[r["policy"], f"{100 * num(r['false_dedup_rate']):.1f}",
          f"{100 * num(r['missed_dedup_rate']):.1f}"] for r in rq4]) + "\n")
    return "\n".join(parts)


def main() -> None:
    FIGS.mkdir(parents=True, exist_ok=True)
    grid, sweep, rq4 = load("grid.csv"), load("c1_replan_sweep.csv"), load("rq4_granularity.csv")
    fig_duplicates(grid)
    fig_sweep(sweep)
    fig_rq4(rq4)
    fig_overhead(grid)
    (RESULTS / "tables.md").write_text(tables(grid, sweep, rq4), encoding="utf-8")


if __name__ == "__main__":
    main()
