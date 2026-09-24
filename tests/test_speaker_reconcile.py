"""说话人对齐核心逻辑单元测试 + 暴力枚举对拍（纯标准库）。

暴力枚举所有满足锁定的说话人指派（每词至多 8 个候选），按
(改动原 speaker 词数 + switch_cost × 换人次数, 说话人序列字典序)
取最优，与 reconcile_speakers 对比。
"""

import itertools
import random
import unittest
from types import SimpleNamespace

from app.errors import DomainError
from app.speaker_reconcile import MAX_SPEAKERS, reconcile_speakers


def W(start, end, text="字", speaker="A"):
    return SimpleNamespace(start_ms=start, end_ms=end, text=text, speaker=speaker)


def make_words(speakers, dur=500, gap=100, text="字"):
    words = []
    t = 0
    for s in speakers:
        words.append(W(t, t + dur, text, s))
        t += dur + gap
    return words


def L(index, speaker):
    return SimpleNamespace(word_index=index, speaker=speaker)


def brute_force(words, locks, switch_cost):
    """返回 (speaker 序列元组, changed 元组, total)；输入非法时抛出对应 DomainError。"""
    n = len(words)
    locked = {}
    for lock in locks:
        idx = lock.word_index
        if idx < 0 or idx >= n:
            raise DomainError("lock_index_out_of_range", "x", word_index=idx)
        if idx in locked:
            raise DomainError("duplicate_lock", "x", word_index=idx)
        locked[idx] = lock.speaker
    candidates = tuple(sorted({w.speaker for w in words} | set(locked.values())))
    if len(candidates) > MAX_SPEAKERS:
        raise DomainError("too_many_speakers", "x", speaker_count=len(candidates))

    best = None
    choices = [
        (candidates.index(locked[i]),) if i in locked else range(len(candidates))
        for i in range(n)
    ]
    for ids in itertools.product(*choices):
        changed = sum(1 for i, p in enumerate(ids) if candidates[p] != words[i].speaker)
        switches = sum(1 for a, b in zip(ids, ids[1:]) if a != b)
        total = changed + switch_cost * switches
        key = (total, ids)
        if best is None or key < best:
            best = key
    total, ids = best
    seq = tuple(candidates[p] for p in ids)
    changed_idx = tuple(
        i for i, s in enumerate(seq) if s != words[i].speaker
    )
    return seq, changed_idx, total


class ReconcileTests(unittest.TestCase):
    def test_no_locks_zero_switch_cost_keeps_original(self):
        words = make_words(["A", "B", "A", "B"])
        revised, changed, total = reconcile_speakers(words, [], 0)
        self.assertEqual([w["speaker"] for w in revised], ["A", "B", "A", "B"])
        self.assertEqual(changed, [])
        self.assertEqual(total, 0)

    def test_smooths_noisy_labels_with_switch_cost(self):
        # 碎标注 A B A B A：原 4 次换人；cost=3 时抹平为全 A，仅改 2 词
        words = make_words(["A", "B", "A", "B", "A"])
        revised, changed, total = reconcile_speakers(words, [], 3)
        self.assertEqual([w["speaker"] for w in revised], ["A"] * 5)
        self.assertEqual(changed, [1, 3])
        self.assertEqual(total, 2)

    def test_single_isolated_word_gets_absorbed(self):
        # A A B A A，cost=1：改 B->A 花 1，省 2 次换人（省 2）=> 全 A
        words = make_words(["A", "A", "B", "A", "A"])
        revised, changed, total = reconcile_speakers(words, [], 1)
        self.assertEqual([w["speaker"] for w in revised], ["A"] * 5)
        self.assertEqual(changed, [2])
        self.assertEqual(total, 1)

    def test_high_switch_cost_prefers_flat_sequence(self):
        # A B A B，cost=10：原标注 4 改 0 换 = 30；全 A / 全 B 各改 2 词、
        # 0 换 = 2，取字典序全 A
        words = make_words(["A", "B", "A", "B"])
        revised, changed, total = reconcile_speakers(words, [], 10)
        self.assertEqual([w["speaker"] for w in revised], ["A"] * 4)
        self.assertEqual(changed, [1, 3])
        self.assertEqual(total, 2)

    def test_lock_introduces_new_speaker(self):
        words = make_words(["A", "B", "A"])
        # cost=0：换人免费，只改锁定词本身
        revised, changed, total = reconcile_speakers(words, [L(1, "C")], 0)
        self.assertEqual([w["speaker"] for w in revised], ["A", "C", "A"])
        self.assertEqual(changed, [1])
        self.assertEqual(total, 1)
        # cost=10：CCC 改 3 词=3，优于 ACA（改 1 + 2 换人 = 21）
        revised, changed, total = reconcile_speakers(words, [L(1, "C")], 10)
        self.assertEqual([w["speaker"] for w in revised], ["C", "C", "C"])
        self.assertEqual(changed, [0, 1, 2])
        self.assertEqual(total, 3)

    def test_locks_at_both_ends(self):
        words = make_words(["A", "B", "A"])
        revised, changed, total = reconcile_speakers(
            words, [L(0, "C"), L(2, "C")], 10
        )
        self.assertEqual([w["speaker"] for w in revised], ["C", "C", "C"])
        self.assertEqual(total, 3)

    def test_lock_matching_original_is_free(self):
        words = make_words(["A", "B", "A"])
        # 锁定词 1 为 B（与原标注一致）；cost=10：AAA 需改锁定词（违反锁定），
        # 可选方案中 BBB 改词 0、2 共 2 词，优于 ABA 的 20
        revised, changed, total = reconcile_speakers(
            words, [L(1, "B")], 10
        )
        self.assertEqual([w["speaker"] for w in revised], ["B", "B", "B"])
        self.assertEqual(changed, [0, 2])
        self.assertEqual(total, 2)

    def test_tie_break_lexicographic(self):
        # A B，cost=1：AB（1 换人）、AA（改 1）、BB（改 1）同为成本 1，
        # 说话人序列字典序最小为 AA
        words = make_words(["A", "B"])
        revised, _, total = reconcile_speakers(words, [], 1)
        self.assertEqual([w["speaker"] for w in revised], ["A", "A"])
        self.assertEqual(total, 1)
        # B A 同理：候选 A<B，字典序最小仍是 AA（改词 0）
        words = make_words(["B", "A"])
        revised, changed, _ = reconcile_speakers(words, [], 1)
        self.assertEqual([w["speaker"] for w in revised], ["A", "A"])
        self.assertEqual(changed, [0])

    def test_word_order_text_time_preserved(self):
        words = [
            W(10, 20, "你", "A"),
            W(20, 35, "好", "B"),
            W(100, 140, "呀", "A"),
        ]
        revised, _, _ = reconcile_speakers(words, [], 5)
        for out, w in zip(revised, words):
            self.assertEqual(out["start_ms"], w.start_ms)
            self.assertEqual(out["end_ms"], w.end_ms)
            self.assertEqual(out["text"], w.text)

    def test_single_word(self):
        words = make_words(["X"])
        revised, changed, total = reconcile_speakers(words, [], 0)
        self.assertEqual(revised[0]["speaker"], "X")
        self.assertEqual(changed, [])
        self.assertEqual(total, 0)
        # 锁定为新说话人：唯一候选该锁，改 1 词，无换人
        revised, changed, total = reconcile_speakers(words, [L(0, "Y")], 10)
        self.assertEqual(revised[0]["speaker"], "Y")
        self.assertEqual(changed, [0])
        self.assertEqual(total, 1)


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.words = make_words(["A", "B"])

    def test_lock_index_out_of_range_high(self):
        with self.assertRaises(DomainError) as ctx:
            reconcile_speakers(self.words, [L(2, "A")], 0)
        self.assertEqual(ctx.exception.code, "lock_index_out_of_range")
        self.assertEqual(ctx.exception.extra["word_index"], 2)
        self.assertEqual(ctx.exception.extra["word_count"], 2)

    def test_lock_index_negative(self):
        with self.assertRaises(DomainError) as ctx:
            reconcile_speakers(self.words, [L(-1, "A")], 0)
        self.assertEqual(ctx.exception.code, "lock_index_out_of_range")
        self.assertEqual(ctx.exception.extra["word_index"], -1)

    def test_duplicate_lock_rejected(self):
        with self.assertRaises(DomainError) as ctx:
            reconcile_speakers(
                self.words, [L(0, "A"), L(1, "B"), L(0, "C")], 0
            )
        self.assertEqual(ctx.exception.code, "duplicate_lock")
        self.assertEqual(ctx.exception.extra["word_index"], 0)

    def test_too_many_speakers(self):
        # 8 个不同原说话人 + 1 个锁定新值 = 9 > 8
        words = make_words(list("ABCDEFGH"))
        with self.assertRaises(DomainError) as ctx:
            reconcile_speakers(words, [L(0, "I")], 0)
        self.assertEqual(ctx.exception.code, "too_many_speakers")
        self.assertEqual(ctx.exception.extra["speaker_count"], 9)
        self.assertEqual(ctx.exception.extra["max_speakers"], MAX_SPEAKERS)

    def test_eight_speakers_accepted(self):
        words = make_words(list("ABCDEFGH"))
        revised, _, _ = reconcile_speakers(words, [], 0)
        self.assertEqual(len(revised), 8)
        self.assertEqual([w["speaker"] for w in revised], list("ABCDEFGH"))

    def test_union_counts_locked_speakers_only(self):
        # 原标注 7 种 + 锁入 1 种新值 = 8，恰好允许
        words = make_words(list("ABCDEFG"))
        revised, _, _ = reconcile_speakers(words, [L(0, "H")], 0)
        self.assertEqual(revised[0]["speaker"], "H")

    def test_word_validation_reused(self):
        bad = [W(0, 2000, "甲", "A"), W(1500, 3000, "乙", "A")]  # 时间重叠
        with self.assertRaises(DomainError) as ctx:
            reconcile_speakers(bad, [], 0)
        self.assertEqual(ctx.exception.code, "overlapping_time_range")


class DifferentialTests(unittest.TestCase):
    def test_matches_brute_force(self):
        random.seed(20260924)
        pool = ["A", "B", "C"]
        checked = 0
        for trial in range(500):
            n = random.randint(1, 8)
            speakers = [random.choice(pool) for _ in range(n)]
            words = make_words(speakers)
            switch_cost = random.randint(0, 10)
            # 随机生成 0~2 个不冲突锁定
            locks = []
            used = set()
            for _ in range(random.randint(0, 2)):
                idx = random.randrange(n)
                if idx in used:
                    continue
                used.add(idx)
                # 小概率引入新说话人
                spk = random.choice(pool + ["C", "D"])
                locks.append(L(idx, spk))

            exp_seq, exp_changed, exp_total = brute_force(
                words, locks, switch_cost
            )
            revised, changed, total = reconcile_speakers(
                words, locks, switch_cost
            )
            self.assertEqual(
                tuple(w["speaker"] for w in revised),
                exp_seq,
                f"trial {trial}: {speakers}, locks={locks}, cost={switch_cost}",
            )
            self.assertEqual(tuple(changed), exp_changed, f"trial {trial}")
            self.assertEqual(total, exp_total, f"trial {trial}")
            # 总成本与两部分自洽
            switches = sum(
                1
                for a, b in zip(exp_seq, exp_seq[1:])
                if a != b
            )
            self.assertEqual(total, len(exp_changed) + switch_cost * switches)
            checked += 1
        self.assertGreater(checked, 400)

    def test_matches_brute_force_with_switch_cost_extremes(self):
        # 边界 switch_cost 0 / 10 单独多跑一些组合
        words_specs = [
            ["A", "B"], ["B", "A"], ["A", "B", "A", "B"],
            ["A", "A", "B"], ["C", "A", "B", "A", "C"],
        ]
        for spec in words_specs:
            words = make_words(spec)
            for cost in (0, 10):
                for locks in ([], [L(len(spec) - 1, "A")], [L(0, "B")]):
                    exp = brute_force(words, locks, cost)
                    revised, changed, total = reconcile_speakers(
                        words, locks, cost
                    )
                    self.assertEqual(
                        tuple(w["speaker"] for w in revised), exp[0],
                        f"{spec} locks={locks} cost={cost}",
                    )
                    self.assertEqual(total, exp[2])


if __name__ == "__main__":
    unittest.main()
