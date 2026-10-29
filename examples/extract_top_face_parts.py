"""Rank located solids in a STEP file and export individually verified STEP cases."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from occ_harness.engine import Harness, ROOT, write_json


def require(response):
    if not response.get("ok"):
        raise RuntimeError(json.dumps(response, ensure_ascii=False))
    return response.get("data", response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--resume", action="store_true", help="Verify/reuse existing exports owned by a matching source manifest")
    args = parser.parse_args()
    source, output = args.source.resolve(strict=True), args.output.resolve()
    if args.count < 1:
        parser.error("count must be positive")
    if output.exists() and any(output.iterdir()) and not args.resume:
        parser.error("output directory must be empty (existing files will not be overwritten)")
    output.mkdir(parents=True, exist_ok=True)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    if args.resume:
        previous = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        if previous.get("source_sha256") != source_hash or previous.get("requested_count") != args.count:
            parser.error("Cannot resume: source hash or requested count differs from manifest")
    session = "em_rank_" + str(time.time_ns())
    h = Harness(ROOT / ".occ-harness", timeout=args.timeout)
    manifest = {"source": str(source), "source_sha256": source_hash, "source_bytes": source.stat().st_size,
                "session": session, "ranking_basis": "Unique located solids; unique located faces per solid; descending face count, ascending source solid index for ties",
                "requested_count": args.count, "exports": []}
    write_json(output / "manifest.json", manifest)
    require(h.start(session))
    print(f"Session {session}; importing {source.stat().st_size / 1048576:.2f} MiB STEP", flush=True)
    try:
        started = time.monotonic()
        assembly = require(h.call(session, "import", shape="em_source", path=source.as_posix(), format="step"))
        manifest["source_inspection"] = assembly
        print(f"Imported in {time.monotonic()-started:.1f}s: {assembly['topology']}; valid={assembly['valid']}", flush=True)
        # Exact installed-version help and lightweight counts avoid mass geometry measurements.
        require(h.help(session, "explode"))
        require(h.help(session, "nbshapes"))
        ranking_script = r'''
set candidates [explode em_source So]
set rows {}
set source_index 0
foreach candidate $candidates {
    incr source_index
    set counts [nbshapes $candidate -t]
    if {![regexp {FACE\s*:\s*([0-9]+)} $counts -> face_count]} {
        error "Cannot obtain face count for $candidate"
    }
    lappend rows "$face_count\t$source_index\t$candidate"
}
join $rows "\n"
'''
        result = require(h.execute(session, ranking_script, []))
        if result["result_truncated"]:
            raise RuntimeError("Ranking result was truncated")
        ranked = []
        for line in result["result"].splitlines():
            faces, index, shape = line.split("\t")
            ranked.append({"faces": int(faces), "source_solid_index": int(index), "shape": shape})
        ranked.sort(key=lambda r: (-r["faces"], r["source_solid_index"]))
        if len(ranked) < args.count:
            raise RuntimeError(f"Only {len(ranked)} solids available, fewer than {args.count}")
        manifest["candidate_count"] = len(ranked)
        manifest["all_solids_ranked"] = ranked
        with (output / "all_solids_ranked.csv").open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=["rank", "faces", "source_solid_index", "shape"])
            writer.writeheader()
            for rank, item in enumerate(ranked, 1):
                writer.writerow(dict(rank=rank, **item))
        print(f"Ranked {len(ranked)} solids. Top face counts: {[r['faces'] for r in ranked[:args.count]]}", flush=True)
        write_json(output / "manifest.json", manifest)
        for rank, item in enumerate(ranked[:args.count], 1):
            original = require(h.call(session, "inspect", shape=item["shape"]))
            if original["topology"]["face"] != item["faces"] or original["topology"]["solid"] != 1:
                raise RuntimeError("Candidate topology differs from ranking")
            name = f"{rank:02d}_faces_{item['faces']:04d}_solid_{item['source_solid_index']:04d}.stp"
            path = output / name
            if args.resume and path.is_file():
                exported = {"bytes": path.stat().st_size}
            else:
                exported = require(h.call(session, "export", shape=item["shape"], path=path.as_posix(), format="step"))
            print(f"Exported {name} ({exported['bytes']} bytes); verifying STEP roundtrip", flush=True)
            verified = require(h.call(session, "import", shape=f"verify_{rank:02d}", path=path.as_posix(), format="step"))
            if verified["topology"]["face"] != item["faces"] or verified["topology"]["solid"] != 1:
                raise RuntimeError(f"STEP roundtrip topology mismatch: {name}")
            for key in ("min", "max"):
                for before, after in zip(original["bbox"][key], verified["bbox"][key]):
                    if abs(before-after) > max(1e-6, abs(before)*1e-8):
                        raise RuntimeError(f"STEP roundtrip bounding box mismatch: {name}")
            before, after = original["volume"], verified["volume"]
            # Trimmed spline STEP conversions can slightly change numerical integration
            # and healing can merge redundant edges; record measured differences.
            if before is not None and after is not None and abs(before-after) > max(1e-5, abs(before)*1e-5):
                raise RuntimeError(f"STEP roundtrip volume mismatch: {name}")
            entry = dict(rank=rank, **item, file=name, bytes=exported["bytes"],
                         sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                         volume_relative_difference=abs(before-after)/abs(before) if before else None,
                         edge_count_difference=verified["topology"]["edge"]-original["topology"]["edge"],
                         source_inspection=original, roundtrip_inspection=verified)
            manifest["exports"].append(entry)
            write_json(output / "manifest.json", manifest)
            print(f"Verified {rank:02d}: faces={verified['topology']['face']}, valid={verified['valid']}", flush=True)
        manifest["complete"] = True
        write_json(output / "manifest.json", manifest)
        lines = ["# toStudent_EM 面数最多的实体", "", f"来源：`{source}`", "",
                 f"从 {len(ranked)} 个按位置区分的 solid 中，按唯一面数降序选取前 {args.count} 个；保留原坐标。", "",
                 "| 编号 | STEP 文件 | 面数 | 源 solid 索引 | 往返检查有效 |", "| --- | --- | ---: | ---: | --- |"]
        for item in manifest["exports"]:
            lines.append(f"| {item['rank']:02d} | [{item['file']}]({item['file']}) | {item['faces']} | {item['source_solid_index']} | {item['roundtrip_inspection']['valid']} |")
        lines += ["", "每个 STEP 已重新导入，核对实体数、面数、包围盒及体积；完整信息见 manifest.json。", "",
                  "选面时请说明文件编号，并提供面编号或截图标记；不同软件的面编号可能不同。"]
        (output / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(json.dumps({"complete": True, "output": str(output), "count": len(manifest["exports"]),
                          "face_counts": [x["faces"] for x in manifest["exports"]]}, ensure_ascii=False), flush=True)
    finally:
        h.stop(session)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
