from fastapi import HTTPException
from sqlalchemy import select

from src.models import Customer, Dataset, Segment, SegmentRun


def _load_run(db, run_id, side):
    run = db.get(SegmentRun, run_id)
    if not run:
        raise HTTPException(404, f"{side} 期实验不存在")
    if run.status != "completed":
        raise HTTPException(409, f"实验「{run.name}」尚未完成，仅已完成实验可以比较")
    return run


def _run_side(db, run):
    dataset = db.get(Dataset, run.dataset_id)
    segments = db.scalars(select(Segment).where(Segment.run_id == run.id).order_by(Segment.label)).all()
    code_by_id = dict(db.execute(select(Customer.id, Customer.code).where(Customer.dataset_id == run.dataset_id)).all())
    groups = []
    codes_by_label = {}
    for segment in segments:
        codes = {code_by_id[customer_id] for customer_id in segment.customer_ids if customer_id in code_by_id}
        codes_by_label[segment.label] = codes
        groups.append({"label": segment.label, "name": segment.name, "size": len(codes)})
    all_codes = set().union(*codes_by_label.values()) if codes_by_label else set()
    return dataset, groups, codes_by_label, all_codes


def _label_by_code(codes_by_label):
    return {code: label for label, codes in codes_by_label.items() for code in codes}


def _best_matching(groups_a, groups_b, cross):
    """Find which groups correspond across the two runs.

    A KMeans group number is arbitrary, so a group keeping the same people
    under another number must not read as customers migrating.  The pairing
    maximises the number of customers kept inside corresponding groups; the
    business name (a fixed rule on centres) is only a tie-breaker, because
    membership can shift while the name stays or changes.  Pairs with no
    shared customer cannot correspond and stay unmatched, which is how
    different group counts are represented.
    """
    name_a = {group["label"]: group["name"] for group in groups_a}
    name_b = {group["label"]: group["name"] for group in groups_b}
    scale = len(groups_b) + 1
    weights = {}
    for (label_a, label_b), count in cross.items():
        if count <= 0:
            continue
        weights[(label_a, label_b)] = count * scale + (1 if name_a[label_a] == name_b[label_b] else 0)

    labels_a = [group["label"] for group in groups_a]
    labels_b = [group["label"] for group in groups_b]
    if max(len(labels_a), len(labels_b)) > 7:
        # 正常候选 K 不超过 6；若未来放开，改用按共同客户从多到少的贪心配对，
        # 避免穷举阶乘级增长。
        pairs, used_a, used_b = [], set(), set()
        ranked = sorted(cross.items(), key=lambda item: item[1], reverse=True)
        for (a_label, b_label), count in ranked:
            if count <= 0 or a_label in used_a or b_label in used_b:
                continue
            pairs.append((a_label, b_label))
            used_a.add(a_label)
            used_b.add(b_label)
        return set(pairs)

    best = (0, 0, ())

    def walk(index, used_b, pairs, weight):
        nonlocal best
        if index == len(labels_a):
            candidate = (weight, len(pairs), tuple(sorted(pairs)))
            if candidate > best:
                best = candidate
            return
        walk(index + 1, used_b, pairs, weight)
        a_label = labels_a[index]
        for b_index, b_label in enumerate(labels_b):
            if b_index in used_b:
                continue
            pair_weight = weights.get((a_label, b_label))
            if pair_weight is None:
                continue
            used_b.add(b_index)
            pairs.append((a_label, b_label))
            walk(index + 1, used_b, pairs, weight + pair_weight)
            pairs.pop()
            used_b.remove(b_index)

    walk(0, set(), [], 0)
    return set(best[2])


def _share(part, whole):
    return round(part / whole, 4) if whole else 0.0


def compare_runs(db, run_a_id, run_b_id):
    if run_a_id == run_b_id:
        raise HTTPException(409, "请选择两个不同的实验进行比较")
    run_a = _load_run(db, run_a_id, "A")
    run_b = _load_run(db, run_b_id, "B")
    dataset_a, groups_a, codes_a, all_a = _run_side(db, run_a)
    dataset_b, groups_b, codes_b, all_b = _run_side(db, run_b)

    common = all_a & all_b
    added = all_b - all_a if common else set()
    left = all_a - all_b if common else set()
    label_a = _label_by_code(codes_a)
    label_b = _label_by_code(codes_b)

    cross = {}
    for code in common:
        pair = (label_a[code], label_b[code])
        cross[pair] = cross.get(pair, 0) + 1

    overlap = {pair: count for pair, count in cross.items() if count > 0}
    matching = _best_matching(groups_a, groups_b, overlap) if common else set()
    retained = sum(cross.get(pair, 0) for pair in matching)
    migrated = len(common) - retained
    comparable = len(common) > 0

    summary = {
        "common": len(common),
        "retained": retained,
        "migrated": migrated,
        "added": len(added),
        "left": len(left),
        "migration_share_of_common": _share(migrated, len(common)),
        "migration_share_of_a": _share(migrated, len(all_a)),
        "migration_share_of_b": _share(migrated, len(all_b)),
        "reconciled": len(all_a) == retained + migrated + len(left) and len(all_b) == retained + migrated + len(added),
    }

    group_a_by_label = {group["label"]: group for group in groups_a}
    group_b_by_label = {group["label"]: group for group in groups_b}
    matches = []
    matched_a = {a_label for a_label, _ in matching}
    matched_b = {b_label for _, b_label in matching}
    if comparable:
        for a_label, b_label in sorted(matching):
            group_a, group_b = group_a_by_label[a_label], group_b_by_label[b_label]
            matches.append({
                "a_label": a_label,
                "a_name": group_a["name"],
                "a_size": group_a["size"],
                "b_label": b_label,
                "b_name": group_b["name"],
                "b_size": group_b["size"],
                "overlap": cross.get((a_label, b_label), 0),
                "share_of_a_group": _share(cross.get((a_label, b_label), 0), group_a["size"]),
                "label_changed": a_label != b_label,
                "name_changed": group_a["name"] != group_b["name"],
            })
        for group in groups_a:
            if group["label"] not in matched_a:
                matches.append({
                    "a_label": group["label"], "a_name": group["name"], "a_size": group["size"],
                    "b_label": None, "b_name": None, "b_size": None,
                    "overlap": 0, "share_of_a_group": 0.0,
                    "label_changed": False, "name_changed": False,
                })
        for group in groups_b:
            if group["label"] not in matched_b:
                matches.append({
                    "a_label": None, "a_name": None, "a_size": None,
                    "b_label": group["label"], "b_name": group["name"], "b_size": group["size"],
                    "overlap": 0, "share_of_a_group": 0.0,
                    "label_changed": False, "name_changed": False,
                })

    matrix = []
    migrations = []
    if comparable:
        for group_a in groups_a:
            cells = []
            for group_b in groups_b:
                pair = (group_a["label"], group_b["label"])
                count = cross.get(pair, 0)
                matched = pair in matching
                cells.append({
                    "b_label": group_b["label"],
                    "b_name": group_b["name"],
                    "count": count,
                    "share_of_common": _share(count, len(common)),
                    "share_of_a_group": _share(count, group_a["size"]),
                    "matched": matched,
                })
                if count and not matched:
                    migrations.append({
                        "a_label": group_a["label"], "a_name": group_a["name"],
                        "b_label": group_b["label"], "b_name": group_b["name"],
                        "count": count,
                        "share_of_common": _share(count, len(common)),
                        "share_of_a_group": _share(count, group_a["size"]),
                    })
            matrix.append({
                "a_label": group_a["label"],
                "a_name": group_a["name"],
                "a_size": group_a["size"],
                "cells": cells,
            })
        migrations.sort(key=lambda item: (-item["count"], item["a_label"], item["b_label"]))

    notes = []
    reason = ""
    if not comparable:
        reason = "两期没有共同的匿名客户编号，无法判断客户迁移或流失，不能进行群组比较。"
        notes.append(reason)
    else:
        renumbered = [item for item in matches if item["a_label"] is not None and item["b_label"] is not None and item["label_changed"]]
        if renumbered:
            pairs = "、".join(f"A{item['a_label']} → B{item['b_label']}" for item in renumbered)
            notes.append(f"群组编号发生变化（{pairs}），对应关系按两期共同客户的最大重叠自动识别；编号变化不视为客户流失。")
        if len(groups_a) != len(groups_b):
            notes.append(f"两期群数不同：A 期 {len(groups_a)} 群、B 期 {len(groups_b)} 群；没有对应群组的客户按实际去向计入迁移、新增或离开。")
        if migrated == 0:
            notes.append("共同客户在两期仍处于对应群组，没有发生群间迁移。")
        if added or left:
            notes.append(f"两期另有 {len(added)} 位新增客户、{len(left)} 位离开客户，编号已分别列出。")

    return {
        "run_a": {
            "id": run_a.id, "name": run_a.name, "dataset_id": run_a.dataset_id,
            "dataset_name": dataset_a.name if dataset_a else "未知数据集",
            "total": len(all_a), "group_count": len(groups_a), "created_at": run_a.created_at,
        },
        "run_b": {
            "id": run_b.id, "name": run_b.name, "dataset_id": run_b.dataset_id,
            "dataset_name": dataset_b.name if dataset_b else "未知数据集",
            "total": len(all_b), "group_count": len(groups_b), "created_at": run_b.created_at,
        },
        "comparable": comparable,
        "reason": reason,
        "summary": summary,
        "matches": matches,
        "matrix": matrix,
        "migrations": migrations,
        "added_codes": sorted(added),
        "left_codes": sorted(left),
        "notes": notes,
    }
