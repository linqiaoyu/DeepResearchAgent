from __future__ import annotations

import re


METRIC_CLAIM_PATTERN = re.compile(
    r"(?P<entity>[\u4e00-\u9fffA-Za-z0-9]+)\s*"
    r"(?P<period>\d{4})\s*年?\s*"
    r"(?P<scope>累计|单季|当季|年初至报告期末|未标注)?"
    r"(?P<metric>营业总收入|营业收入|业务收入|营收|归母净利润|"
    r"归属于上市公司股东的净利润|净利润|扣非净利润|"
    r"扣除非经常性损益后的净利润|毛利率|资本开支|资本支出)"
    r"\s*为\s*(?P<value>-?\d+(?:\.\d+)?)\s*(?P<unit>亿元|万元|元|%)"
)
