from dataclasses import asdict, dataclass
from datetime import datetime
import math


@dataclass(frozen=True)
class Metrics:
    site_id: str
    site_name: str
    source: str
    scope: str
    start: datetime
    end: datetime
    total: int
    success: int
    failure: int
    p50_seconds: float | None = None
    p95_seconds: float | None = None
    latency_samples: int | None = None
    window_kind: str = "absolute"

    def __post_init__(self):
        if self.start.tzinfo is None or self.end.tzinfo is None or self.start >= self.end:
            raise ValueError("统计时间必须带时区，且结束时间晚于开始时间")
        for value in (self.total, self.success, self.failure):
            if type(value) is not int or value < 0:
                raise ValueError("调用次数必须是非负整数")
        if self.success + self.failure != self.total:
            raise ValueError("数据口径不一致：成功数 + 失败数 != 调用总量")
        if self.latency_samples is not None:
            if type(self.latency_samples) is not int or not 0 <= self.latency_samples <= self.total:
                raise ValueError("耗时样本数量无效")
        for value in (self.p50_seconds, self.p95_seconds):
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
                raise ValueError("耗时必须是有限的非负秒数")
        if self.p50_seconds is not None and self.p95_seconds is not None and self.p50_seconds > self.p95_seconds:
            raise ValueError("P50 不能大于 P95")

    @property
    def success_rate(self):
        return self.success / self.total if self.total else None

    def to_dict(self):
        result = asdict(self)
        result.update(start=self.start.isoformat(), end=self.end.isoformat())
        return result

    @classmethod
    def from_dict(cls, value):
        return cls(**{**value, "start": datetime.fromisoformat(value["start"]), "end": datetime.fromisoformat(value["end"])})


@dataclass(frozen=True)
class Assessment:
    status: str
    reasons: list[str]
    baseline: float | None
