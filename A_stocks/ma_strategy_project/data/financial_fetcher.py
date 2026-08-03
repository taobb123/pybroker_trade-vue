#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
财务数据获取模块
支持从API获取股票财务数据，用于事件驱动策略（财报策略）
"""

import pandas as pd
import time
from datetime import datetime
from typing import Optional, Dict, List
from config.db_config import DB_CONFIG
from config.settings import DATA_CONFIG
from utils.logger import logger


class FinancialDataFetcher:
    """财务数据获取类"""
    
    def __init__(self):
        """初始化财务数据获取器"""
        self.db_config = DB_CONFIG
        self.data_config = DATA_CONFIG
        self.connection = None
        self.financial_cache = {}  # 内存缓存
        self._akshare_available = None
    
    def __enter__(self):
        """上下文管理器入口"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.close_db()
        return False
    
    def connect_db(self):
        """连接数据库"""
        try:
            if not self.connection:
                self.connection = __import__('pymysql').connect(
                    host=self.db_config['host'],
                    port=self.db_config['port'],
                    user=self.db_config['user'],
                    password=self.db_config['password'],
                    database=self.db_config['database'],
                    charset=self.db_config['charset'],
                    cursorclass=__import__('pymysql').cursors.DictCursor
                )
            return True
        except Exception as e:
            logger.warning(f"数据库连接失败: {e}")
            return False
    
    def close_db(self):
        """关闭数据库连接"""
        if self.connection:
            self.connection.close()
            self.connection = None
    
    def _check_akshare(self):
        """检查akshare是否可用"""
        if self._akshare_available is None:
            try:
                import akshare as ak
                self._akshare_available = True
            except ImportError:
                self._akshare_available = False
                logger.warning("akshare未安装，请使用: pip install akshare")
        return self._akshare_available
    
    def normalize_stock_code(self, code: str) -> str:
        """
        标准化股票代码格式
        
        Args:
            code: 股票代码，支持多种格式 (如 '000001', 'SZ000001', 'sh000001')
        
        Returns:
            标准化后的代码（纯数字，如 '000001'）
        """
        if pd.isna(code) or not code:
            return None
        
        code = str(code).strip().upper()
        # 移除前缀
        code = code.replace('SZ', '').replace('SH', '').replace('sz', '').replace('sh', '').strip()
        return code
    
    def get_financial_data(
        self, 
        code: str, 
        period: str = 'report',
        retry: int = 1  # 性能优化：减少重试次数（2 -> 1）
    ) -> Optional[Dict]:
        """
        获取单个股票的财务数据
        
        Args:
            code: 股票代码（如 '000001' 或 'SZ000001'）
            period: 报告期类型，'report'表示最新报告，'quarter'表示季度报告
            retry: 重试次数
        
        Returns:
            财务数据字典，包含以下字段：
            - net_profit: 净利润（元）
            - revenue: 营业收入（元）
            - roe: 净资产收益率（%）
            - roa: 总资产收益率（%）
            - eps: 每股收益（元）
            - bps: 每股净资产（元）
            - profit_margin: 净利润率（%）
            - total_assets: 总资产（元）
            - total_liabilities: 总负债（元）
            - net_assets: 净资产（元）
            - asset_liability_ratio: 资产负债率（%）
            - operating_cashflow: 经营现金流（元）
            - total_shares: 总股本（万股）
            - circulating_shares: 流通股本（万股）
            - report_date: 报告期日期（YYYY-MM-DD）
            - report_type: 报告类型（年报/季报/半年报）
        
        如果获取失败返回None
        """
        # 标准化股票代码
        normalized_code = self.normalize_stock_code(code)
        if not normalized_code:
            logger.warning(f"无效的股票代码: {code}")
            return None
        
        # 检查缓存
        cache_key = f"{normalized_code}_{period}"
        if cache_key in self.financial_cache:
            logger.debug(f"从缓存获取 {normalized_code} 的财务数据")
            return self.financial_cache[cache_key]
        
        # 检查akshare是否可用
        if not self._check_akshare():
            logger.error("akshare不可用，无法获取财务数据")
            return None
        
        # 获取财务数据
        financial_dict = self._fetch_from_akshare(normalized_code, retry)
        
        if financial_dict:
            # 标准化和清理数据
            standardized_data = self._standardize_financial_data(financial_dict, normalized_code)
            if standardized_data:
                # 缓存数据
                self.financial_cache[cache_key] = standardized_data
                return standardized_data
        
        return None
    
    def _fetch_from_akshare(self, stock_code: str, retry: int = 1) -> Optional[Dict]:
        """
        从akshare获取财务数据
        
        Args:
            stock_code: 股票代码（纯数字，如 '000001'）
            retry: 重试次数
        
        Returns:
            原始财务数据字典
        """
        import akshare as ak
        
        api_methods = [
            ('stock_financial_abstract', lambda: ak.stock_financial_abstract(symbol=stock_code)),
        ]
        
        for api_name, api_func in api_methods:
            for attempt in range(retry):
                try:
                    logger.debug(f"尝试从 {api_name} 获取 {stock_code} 的财务数据 (尝试 {attempt + 1}/{retry})")
                    # 性能优化：直接调用API，减少延迟
                    df = api_func()
                    
                    if df is None or df.empty:
                        time.sleep(0.1)  # 减少延迟：0.3 -> 0.1秒
                        continue
                    
                    # 检查是否有"指标"列
                    if '指标' not in df.columns:
                        logger.debug(f"{api_name} 返回数据格式异常，缺少'指标'列")
                        continue
                    
                    # 提取最新一期数据
                    latest_col = self._extract_latest_report_date(df)
                    if latest_col is None:
                        logger.warning(f"无法从 {stock_code} 的数据中找到有效的报告期")
                        continue
                    
                    # 构建指标字典
                    financial_dict = {}
                    for _, row in df.iterrows():
                        indicator = str(row['指标']).strip()
                        value = row.get(latest_col)
                        if pd.notna(value):
                            try:
                                financial_dict[indicator] = float(value)
                            except (ValueError, TypeError):
                                pass
                    
                    if financial_dict:
                        logger.info(f"成功从 {api_name} 获取 {stock_code} 的财务数据，共 {len(financial_dict)} 个指标")
                        return financial_dict
                    
                except Exception as e:
                    if attempt < retry - 1:
                        logger.debug(f"{api_name} 获取失败，重试中: {str(e)[:50]}")
                        time.sleep(0.2)  # 减少延迟：0.5 -> 0.2秒
                        continue
                    else:
                        logger.warning(f"{stock_code} 从 {api_name} 获取财务数据失败: {str(e)[:50]}")
                        break
        
        return None
    
    def _extract_latest_report_date(self, df: pd.DataFrame) -> Optional[str]:
        """
        从DataFrame中提取最新的报告期列名
        
        Args:
            df: 财务数据DataFrame
        
        Returns:
            最新报告期的列名，如果未找到返回None
        """
        date_cols = []
        
        # 收集所有可能的日期列
        for col in df.columns:
            col_str = str(col)
            # 跳过非日期列
            if col_str in ['指标', '选项', '.', 'Unnamed']:
                continue
            # 8位数字格式 (YYYYMMDD)
            if col_str.isdigit() and len(col_str) == 8:
                date_cols.append(col_str)
        
        # 如果没有8位数字，尝试其他格式
        if not date_cols:
            for col in df.columns:
                col_str = str(col)
                if any(year in col_str for year in ['2024', '2023', '2022', '2025', '2021']):
                    date_cols.append(col_str)
        
        if not date_cols:
            return None
        
        # 选择最新的日期列（排除未来日期）
        current_date = datetime.now().strftime('%Y%m%d')
        valid_dates = []
        for d in date_cols:
            if d.isdigit() and len(d) == 8:
                if d <= current_date:  # 只选择小于等于当前日期的
                    valid_dates.append(d)
        
        if valid_dates:
            # 优先选择最新的有效日期（通常是最近的年报或季报）
            latest_col = sorted(valid_dates, reverse=True)[0]
            return latest_col
        else:
            # 如果没有有效日期，尝试选择最近的年份列
            year_based = sorted(
                [d for d in date_cols if any(y in str(d) for y in ['2024', '2023', '2022'])],
                reverse=True,
                key=lambda x: str(x)
            )
            if year_based:
                return year_based[0]
            else:
                # 最后备选：选择第一个可用的
                return date_cols[0] if date_cols else None
    
    def _standardize_financial_data(self, raw_data: Dict, code: str) -> Optional[Dict]:
        """
        标准化财务数据格式
        
        Args:
            raw_data: 原始财务数据字典
            code: 股票代码
        
        Returns:
            标准化后的财务数据字典
        """
        standardized = {
            'code': code,
            'net_profit': None,
            'revenue': None,
            'roe': None,
            'roa': None,
            'eps': None,
            'bps': None,
            'profit_margin': None,
            'total_assets': None,
            'total_liabilities': None,
            'net_assets': None,
            'asset_liability_ratio': None,
            'operating_cashflow': None,
            'free_cashflow': None,
            'total_shares': None,
            'circulating_shares': None,
            'report_date': None,
            'report_type': None,
        }
        
        # 指标名称映射（支持多种可能的名称格式）
        indicator_mapping = {
            'net_profit': ['净利润', '净利润(元)', '归母净利润', '归属于母公司所有者的净利润', '归属母公司净利润'],
            'revenue': ['营业收入', '营业收入(元)', '主营业务收入', '营业总收入'],
            'roe': ['净资产收益率(ROE)', 'ROE', '净资产收益率', '加权平均净资产收益率', '净资产收益率(%)'],
            'roa': ['总资产收益率(ROA)', 'ROA', '总资产收益率', '总资产收益率(%)', '资产收益率'],
            'eps': ['每股收益', '基本每股收益', '每股收益(元)', '每股收益（元）'],
            'bps': ['每股净资产', '每股净资产(元)', '归属于母公司股东的每股净资产', '每股净资产（元）'],
            'total_assets': ['总资产', '总资产(元)', '资产总计'],
            'total_liabilities': ['总负债', '总负债(元)', '负债合计', '负债总计'],
            'net_assets': ['净资产', '净资产(元)', '归属于母公司股东权益合计', '股东权益合计', '所有者权益合计', '股东权益合计(净资产)'],
            'operating_cashflow': ['经营活动产生的现金流量净额', '经营现金流', '经营活动现金流净额', '经营活动产生的现金流量', '经营现金流净额'],
            'free_cashflow': ['自由现金流', '自由现金流量', '自由现金流（元）'],
            'total_shares': ['总股本', '总股本(万股)', '股本', '总股本（万股）'],
            'circulating_shares': ['流通股本', '流通股本(万股)', '流通A股', '流通股本（万股）'],
        }
        
        # 映射指标
        for key, possible_names in indicator_mapping.items():
            for name in possible_names:
                if name in raw_data:
                    value = raw_data[name]
                    if pd.notna(value):
                        standardized[key] = value
                        break
        
        # 计算衍生指标
        # 净利润率 = 净利润 / 营业收入
        if standardized['net_profit'] and standardized['revenue'] and standardized['revenue'] > 0:
            standardized['profit_margin'] = (standardized['net_profit'] / standardized['revenue']) * 100
        
        # 资产负债率 = 总负债 / 总资产
        if standardized['total_liabilities'] and standardized['total_assets'] and standardized['total_assets'] > 0:
            standardized['asset_liability_ratio'] = (standardized['total_liabilities'] / standardized['total_assets']) * 100
        
        # 确定报告类型（根据报告期日期判断）
        if standardized['report_date']:
            # 可以从报告期日期推断类型
            pass  # 暂时留空，后续可以从原始数据中提取
        
        # 验证数据完整性
        key_indicators = ['net_profit', 'revenue', 'roe']
        if not any(standardized[k] is not None for k in key_indicators):
            logger.warning(f"{code} 的财务数据缺少关键指标，可能不完整")
        
        return standardized
    
    def get_multiple_periods(self, code: str, periods: int = 4) -> Optional[List[Dict]]:
        """
        获取多个报告期的财务数据
        
        Args:
            code: 股票代码
            periods: 获取的报告期数量
        
        Returns:
            财务数据列表，按报告期从新到旧排序
        """
        # 这个功能需要扩展API调用来获取历史多个报告期
        # 目前先返回最新一期的数据
        latest = self.get_financial_data(code)
        if latest:
            return [latest]
        return None
    
    def clear_cache(self):
        """清空内存缓存"""
        self.financial_cache.clear()
        logger.debug("财务数据缓存已清空")
