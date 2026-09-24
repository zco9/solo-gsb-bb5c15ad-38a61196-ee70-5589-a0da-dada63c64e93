"""说话人对齐核心逻辑（纯标准库，不依赖 FastAPI，便于单测）。

给定原标注词序列、若干人工锁定项（word_index -> speaker）与换人代价
switch_cost（0～10），在不改词序、文本、时间且严格满足锁定的前提下，
为每个词重新指派说话人，最小化：

    改动原 speaker 的词数 + switch_cost × 相邻换人次数

候选说话人取“原词 speaker”与“锁定 speaker”的并集，最多 8 个。
同成本取整条说话人序列（按候选 speaker 排序后的字母表）字典序最小。

算法（后向 DP + 贪心重建），O(n·k²) 时间、O(n·k) 空间，k <= 8：

* bwd[i][p]：词 i 固定为 speaker[p] 时，后缀 [i, n) 的最优成本（词 i 的
  改动词成本、词 i 与词 i+1 间的换人成本均计入）：
      bwd[i][p] = changed(i, p) + min_q( [p!=q]·switch_cost + bwd[i+1][q] )；
* 最优总成本 = min_p bwd[0][p]（锁定词只允许唯一候选）；
* 从左向右贪心重建：在仍能达成最优总成本的候选中按字母表顺序取最小
  speaker。任何最优序列的当前位置都必须满足
  “前缀成本 + 换人代价 + bwd[i][q] == optimum”，故每步取字母表最小的
  可行 speaker，归纳可得全局字典序最小的说话人序列。
"""

from .errors import DomainError
from .segmentation import validate_words

MAX_SPEAKERS = 8  # 候选说话人（原标注 ∪ 人工锁定）数量上限

INF = 10**18


def _fail(code, message, **extra):
    raise DomainError(code, message, **extra)


def reconcile_speakers(words, locks, switch_cost):
    """为每个词重新指派说话人；返回 (revised_words, changed_indices, total_cost)。

    参数：
    * words：每项需具备属性 start_ms / end_ms / text / speaker，沿用同一套
      词序与时间校验（422 错误码一致）；
    * locks：每项需具备属性 word_index / speaker，word_index 必须在
      [0, n) 内且不得重复；
    * switch_cost：0～10 的整数，每次相邻换人的代价。

    revised_words 为 dict 列表（start_ms/end_ms/text/speaker），词序、文本、
    时间与原词完全一致；changed_indices 为 speaker 被改动的词序号（升序）；
    total_cost = 改动词数 + switch_cost × 相邻换人次数。
    校验失败时抛出 DomainError（HTTP 422）。
    """
    validate_words(words)
    n = len(words)

    # ---- 锁定项校验：索引越界、重复 word_index ----
    locked = {}
    for pos, lock in enumerate(locks):
        idx = lock.word_index
        if idx < 0 or idx >= n:
            _fail(
                "lock_index_out_of_range",
                f"第 {pos} 个锁定项的 word_index({idx}) 超出范围 [0, {n - 1}]",
                word_index=idx,
                lock_position=pos,
                word_count=n,
            )
        if idx in locked:
            _fail(
                "duplicate_lock",
                f"word_index={idx} 存在重复锁定项，每个词至多锁定一次",
                word_index=idx,
            )
        locked[idx] = lock.speaker

    # ---- 候选说话人：原标注 ∪ 锁定值，排序保证字母表确定 ----
    candidates = sorted({w.speaker for w in words} | set(locked.values()))
    if len(candidates) > MAX_SPEAKERS:
        _fail(
            "too_many_speakers",
            f"候选说话人（原标注与锁定值的并集）共 {len(candidates)} 个，"
            f"超过上限 {MAX_SPEAKERS} 个",
            speaker_count=len(candidates),
            max_speakers=MAX_SPEAKERS,
        )
    k = len(candidates)
    spk_id = {s: p for p, s in enumerate(candidates)}

    # 每个词允许指派的候选下标：锁定词唯一，其余任选（均按字母表升序）
    allowed = [
        (spk_id[locked[i]],) if i in locked else range(k) for i in range(n)
    ]
    original_id = [spk_id[w.speaker] for w in words]

    # ---- 后向 DP：bwd[i][p] = 词 i 固定为 speaker[p] 时的最优后缀成本 ----
    bwd = [[INF] * k for _ in range(n + 1)]
    for p in range(k):
        bwd[n][p] = 0
    for i in range(n - 1, -1, -1):
        row_next = bwd[i + 1]
        next_allowed = allowed[i + 1] if i + 1 < n else range(k)
        for p in allowed[i]:
            best = INF
            for q in next_allowed:
                value = row_next[q] + (switch_cost if p != q else 0)
                if value < best:
                    best = value
            bwd[i][p] = (0 if p == original_id[i] else 1) + best

    # ---- 贪心重建：每步取仍能达成最优总成本的字母表最小 speaker ----
    # 已确定前缀（末位 prev_p）与前缀成本 prefix_cost 后，在位置 i 选 p 的
    # 完整成本为：prefix_cost + 词 i-1->i 换人 + changed(i,p) + suffix(i,p)，
    # 其中 suffix(i,p) = min_q([p!=q]·switch_cost + bwd[i+1][q])。
    chosen_ids = [-1] * n
    optimum = min(bwd[0][p] for p in allowed[0])
    prefix_cost = 0
    prev_p = -1
    for i in range(n):
        for p in allowed[i]:  # allowed 已按候选字母表升序
            transition = switch_cost if i > 0 and p != prev_p else 0
            local = (0 if p == original_id[i] else 1) + transition
            if i + 1 == n:
                suffix = 0
            else:
                suffix = INF
                for q in allowed[i + 1]:
                    value = bwd[i + 1][q] + (switch_cost if p != q else 0)
                    if value < suffix:
                        suffix = value
            if prefix_cost + local + suffix != optimum:
                continue
            chosen_ids[i] = p
            prefix_cost += local
            prev_p = p
            break
        # bwd 对所有允许候选均有限（锁定恒可满足），chosen_ids[i] 必已赋值

    revised = []
    changed_indices = []
    switches = 0
    for i, w in enumerate(words):
        p = chosen_ids[i]
        if p != original_id[i]:
            changed_indices.append(i)
        if i > 0 and p != chosen_ids[i - 1]:
            switches += 1
        revised.append(
            {
                "start_ms": w.start_ms,
                "end_ms": w.end_ms,
                "text": w.text,
                "speaker": candidates[p],
            }
        )
    total_cost = len(changed_indices) + switch_cost * switches
    return revised, changed_indices, total_cost
