from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Optional

import pandas as pd


class MarketDataProvider(ABC):
    """Interface chung cho nguồn dữ liệu giá thị trường."""

    name: str = "base"

    @abstractmethod
    def get_ohlcv(
        self,
        symbol: str,
        start: date,
        end: date,
        interval: str = "1D",
    ) -> pd.DataFrame:
        """Trả về DataFrame chuẩn: date, open, high, low, close, volume."""
        raise NotImplementedError

    def is_available(self) -> bool:
        return True


class FundamentalDataProvider(ABC):
    """Interface chung cho nguồn dữ liệu báo cáo tài chính."""

    name: str = "base"

    @abstractmethod
    def load_table(
        self,
        symbol: str,
        table_type: str,
        period: str,
        lang: str = "vi",
    ) -> pd.DataFrame:
        raise NotImplementedError

    def is_available(self) -> bool:
        return True
