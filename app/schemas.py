"""请求/响应 Pydantic 模型。"""

from pydantic import BaseModel, Field


class WordIn(BaseModel):
    start_ms: int = Field(..., ge=0, description="词起始时间（毫秒）")
    end_ms: int = Field(..., ge=0, description="词结束时间（毫秒）")
    text: str = Field(..., min_length=1, description="词文本；段文本为词文本原样拼接")
    speaker: str = Field(..., min_length=1, description="说话人标识；换人处强制断段")


class SegmentRequest(BaseModel):
    words: list[WordIn] = Field(..., min_length=1, description="按时间排列的词序列")


class SegmentOut(BaseModel):
    index: int
    start_word: int = Field(..., description="段首词序号（0-based，含）")
    end_word: int = Field(..., description="段末词序号（0-based，含）")
    start_ms: int
    end_ms: int
    duration_ms: int
    speaker: str
    text: str
    char_count: int = Field(..., description="Unicode 字符数（code point）")


class SegmentResponse(BaseModel):
    segments: list[SegmentOut]
    total_score: int
    srt: str


class AdBreakRequest(BaseModel):
    words: list[WordIn] = Field(..., min_length=1, description="按时间排列的词序列")
    break_count: int = Field(..., ge=1, le=5, description="插播点个数（1～5）")
    min_silence_ms: int = Field(..., ge=1, description="候选静音时长下限（毫秒，正整数）")
    min_spacing_ms: int = Field(..., ge=0, description="相邻插播点最小间隔（毫秒，非负整数）")


class AdBreakOut(BaseModel):
    index: int
    time_ms: int = Field(..., description="插播时间：静音区间的整数中点")
    silence_start_ms: int = Field(..., description="静音起点（前词 end_ms）")
    silence_end_ms: int = Field(..., description="静音终点（后词 start_ms）")
    silence_ms: int = Field(..., description="该处静音时长（毫秒）")


class AdBreakResponse(BaseModel):
    breaks: list[AdBreakOut] = Field(..., description="按时间升序的插播点")
    total_silence_ms: int = Field(..., description="选中静音的总毫秒数")


class LockIn(BaseModel):
    word_index: int = Field(..., description="被锁定词的序号（0-based）；越界在领域校验中返回 422")
    speaker: str = Field(..., min_length=1, description="该词必须指派的说话人标识")


class SpeakerReconcileRequest(BaseModel):
    words: list[WordIn] = Field(..., min_length=1, description="按时间排列的词序列（含原 speaker 标注）")
    locks: list[LockIn] = Field(default_factory=list, description="人工锁定项；word_index 不得越界或重复")
    switch_cost: int = Field(..., ge=0, le=10, description="相邻换人代价（0～10 的整数）")


class WordOut(BaseModel):
    start_ms: int
    end_ms: int
    text: str
    speaker: str = Field(..., description="重新指派后的说话人标识")


class SpeakerReconcileResponse(BaseModel):
    words: list[WordOut] = Field(..., description="修订后的词序列：词序、文本、时间与原词完全一致")
    changed_indices: list[int] = Field(..., description="speaker 被改动的词序号（0-based，升序）")
    total_cost: int = Field(..., description="改动词数 + switch_cost × 相邻换人次数")
