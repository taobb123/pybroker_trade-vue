#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据获取模块
支持从数据库和API获取股票历史数据（混合方案）
"""

import os
import sys

# 必须先于 config 导入：cwd=pybroker_integration 时会抢到错误的 config 包
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
try:
    from path_bootstrap import prefer_ma_strategy_project_root

    prefer_ma_strategy_project_root(__file__)
except Exception:
    if _ROOT in sys.path:
        sys.path.remove(_ROOT)
    sys.path.insert(0, _ROOT)

import pandas as pd
import numpy as np
import pymysql
from datetime import datetime, timedelta
from typing import Optional
from config.db_config import DB_CONFIG
from config.settings import DATA_CONFIG
from utils.logger import logger


class DataFetcher:
    """数据获取类"""
    
    def __init__(self):
        self.db_config = DB_CONFIG
        self.connection = None
        
    def connect_db(self):
        """连接数据库"""
        try:
            if not self.connection:
                self.connection = pymysql.connect(
                    host=self.db_config['host'],
                    port=self.db_config['port'],
                    user=self.db_config['user'],
                    password=self.db_config['password'],
                    database=self.db_config['database'],
                    charset=self.db_config['charset'],
                    cursorclass=pymysql.cursors.DictCursor
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
    
    def fetch_from_database(self, code: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """
        从数据库获取股票历史数据
        
        Args:
            code: 股票代码（如'000001'）
            start_date: 开始日期（格式：'YYYY-MM-DD'）
            end_date: 结束日期（格式：'YYYY-MM-DD'）
        
        Returns:
            DataFrame: 包含date, open, high, low, close, volume列
            如果失败返回None
        """
        if not self.connect_db():
            return None
        
        try:
            # 尝试常见的表名和字段名
            # 这里假设有一个历史数据表，字段可能为：date/trade_date, code, open, high, low, close, volume
            # 如果表不存在，会抛出异常
            
            # 常见的历史数据表名
            possible_tables = [
                'stock_daily', 'daily_quotes', 'historical_data', 
                'stock_history', 'price_history', 'daily_data'
            ]
            
            # 常见日期字段名
            possible_date_fields = ['date', 'trade_date', 'trading_date', 'day']
            
            with self.connection.cursor() as cursor:
                # 检查哪个表存在
                found_table = None
                found_date_field = None
                
                for table in possible_tables:
                    cursor.execute(f"SHOW TABLES LIKE '{table}'")
                    if cursor.fetchone():
                        found_table = table
                        # 检查日期字段
                        cursor.execute(f"SHOW COLUMNS FROM {table}")
                        columns = [col['Field'] for col in cursor.fetchall()]
                        for date_field in possible_date_fields:
                            if date_field in columns:
                                found_date_field = date_field
                                break
                        if found_date_field:
                            break
                
                if not found_table or not found_date_field:
                    logger.debug("数据库中未找到历史数据表")
                    return None
                
                # 查询数据
                sql = f"""
                    SELECT {found_date_field} as date, open, high, low, close, volume
                    FROM {found_table}
                    WHERE code = %s 
                    AND {found_date_field} >= %s 
                    AND {found_date_field} <= %s
                    ORDER BY {found_date_field} ASC
                """
                
                cursor.execute(sql, (code, start_date, end_date))
                results = cursor.fetchall()
                
                if not results:
                    logger.debug(f"数据库中未找到股票 {code} 的历史数据")
                    return None
                
                # 转换为DataFrame
                df = pd.DataFrame(results)
                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values('date')
                
                # 确保数据类型正确
                numeric_cols = ['open', 'high', 'low', 'close', 'volume']
                for col in numeric_cols:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce')
                
                logger.info(f"从数据库获取 {code} 数据成功，共 {len(df)} 条记录")
                return df[['date', 'open', 'high', 'low', 'close', 'volume']]
                
        except Exception as e:
            logger.warning(f"从数据库获取数据失败: {e}")
            return None
    
    def fetch_from_api(self, code: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """
        从API获取股票历史数据
        
        根据配置优先使用akshare、tushare或yfinance
        
        Args:
            code: 股票代码（如'000001'）
            start_date: 开始日期（格式：'YYYY-MM-DD'）
            end_date: 结束日期（格式：'YYYY-MM-DD'）
        
        Returns:
            DataFrame: 包含date, open, high, low, close, volume列
            如果失败返回None
        """
        # 更稳定的动态回退链：
        # - 对ETF（5/1开头）：优先 yfinance → tushare(如配置) → akshare → baostock
        # - 对A股（0/3/6开头）：优先 tushare(如配置) → baostock → akshare → yfinance
        is_etf = code.startswith(('5', '1'))
        has_tushare_token = bool(DATA_CONFIG.get('tushare_token', '').strip())

        # 如果存在覆盖顺序，则优先生效
        override = DATA_CONFIG.get('provider_override', [])
        provider_chain = []
        if isinstance(override, list) and len(override) > 0:
            name_to_fn = {
                'akshare': self._fetch_from_akshare,
                'baostock': self._fetch_from_baostock,
                'yfinance': self._fetch_from_yfinance,
                # tushare 在ETF与A股上用不同函数，下面动态处理
            }
            logger.debug(f"使用 provider_override 配置: {override}")
            logger.debug(f"Tushare token 状态: {'已配置' if has_tushare_token else '未配置'}")
            for raw in override:
                name = str(raw).strip().lower()
                if name == 'tushare' or name == 'tushare_etf':
                    if not has_tushare_token:
                        logger.warning(f"跳过 {name}：token 未配置")
                        continue
                    if is_etf:
                        provider_chain.append(('tushare_etf', self._fetch_etf_from_tushare))
                        logger.debug(f"添加数据源: tushare_etf")
                    else:
                        provider_chain.append(('tushare', self._fetch_from_tushare))
                        logger.debug(f"添加数据源: tushare")
                elif name in name_to_fn:
                    provider_chain.append((name, name_to_fn[name]))
                    logger.debug(f"添加数据源: {name}")
            # 如果覆盖配置为空或无效，回退到默认链
        if not provider_chain:
            if is_etf:
                provider_chain.append(('yfinance', self._fetch_from_yfinance))
                if has_tushare_token:
                    provider_chain.append(('tushare_etf', self._fetch_etf_from_tushare))
                provider_chain.append(('akshare', self._fetch_from_akshare))
                provider_chain.append(('baostock', self._fetch_from_baostock))
            else:
                if has_tushare_token:
                    provider_chain.append(('tushare', self._fetch_from_tushare))
                provider_chain.append(('baostock', self._fetch_from_baostock))
                provider_chain.append(('akshare', self._fetch_from_akshare))
                provider_chain.append(('yfinance', self._fetch_from_yfinance))

        logger.info(f"数据源调用链（共 {len(provider_chain)} 个）: {[name for name, _ in provider_chain]}")
        for name, fn in provider_chain:
            logger.info(f"尝试使用 {name} 获取 {code} 数据...")
            df = self._call_with_retries(fn, code, start_date, end_date, provider_name=name)
            if df is not None:
                logger.info(f"✓ 成功从 {name} 获取 {code} 数据")
                return df
            logger.warning(f"✗ {name} 获取 {code} 失败，尝试下一个提供方...")
        logger.error(f"所有数据源都失败，无法获取 {code} 数据")
        return None

    def _call_with_retries(self, fn, code: str, start_date: str, end_date: str, provider_name: str,
                            max_retries: int = 3) -> Optional[pd.DataFrame]:
        """对单个提供方连续重试，不在本地插入延时（仅兜底层异常）。"""
        for attempt in range(max_retries):
            try:
                return fn(code, start_date, end_date)
            except Exception as e:
                logger.warning(f"{provider_name} 调用异常: {e}")
        return None
    
    def _fetch_from_akshare(self, code: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """
        从akshare获取股票历史数据
        
        Args:
            code: 股票代码
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            DataFrame或None
        """
        try:
            import akshare as ak
            logger.info(f"使用akshare获取 {code} 数据...")
            
            # akshare需要日期格式为YYYYMMDD
            start_date_str = start_date.replace('-', '')
            end_date_str = end_date.replace('-', '')
            
            # 调用akshare接口
            # 注意：A股与ETF使用不同接口
            try:
                if code.startswith(('5', '1')):
                    # ETF: 使用东财ETF历史接口
                    df = ak.fund_etf_hist_em(
                        symbol=code,
                        period="daily",
                        start_date=start_date_str,
                        end_date=end_date_str,
                        adjust=""
                    )
                else:
                    # A股：常规A股历史接口
                    df = ak.stock_zh_a_hist(
                        symbol=code, 
                        period="daily",
                        start_date=start_date_str,
                        end_date=end_date_str,
                        adjust="qfq"  # 使用前复权，确保与常见行情软件口径一致
                    )
            except Exception as e:
                logger.warning(f"akshare接口调用失败: {e}")
                return None
            
            if df is None or df.empty:
                logger.warning(f"akshare返回空数据")
                return None
            
            # 检查并转换列名（akshare的中文列名，ETF与A股列名略有差异）
            column_mapping = {}
            for col in df.columns:
                if '日期' in str(col) or 'date' in str(col).lower():
                    column_mapping[col] = 'date'
                elif '开盘' in str(col) or 'open' in str(col).lower():
                    column_mapping[col] = 'open'
                elif '收盘' in str(col) or 'close' in str(col).lower():
                    column_mapping[col] = 'close'
                elif '最高' in str(col) or 'high' in str(col).lower():
                    column_mapping[col] = 'high'
                elif '最低' in str(col) or 'low' in str(col).lower():
                    column_mapping[col] = 'low'
                elif '成交量' in str(col) or 'volume' in str(col).lower():
                    column_mapping[col] = 'volume'
            
            if not column_mapping:
                # 如果没有找到匹配的列，尝试使用标准列名
                standard_cols = ['date', 'open', 'high', 'low', 'close', 'volume']
                if len(df.columns) >= len(standard_cols):
                    df.columns = standard_cols[:len(df.columns)]
                else:
                    logger.warning(f"无法识别akshare返回的列名: {df.columns.tolist()}")
                    return None
            else:
                df = df.rename(columns=column_mapping)
            
            # 确保日期列存在
            if 'date' not in df.columns:
                logger.warning("akshare返回数据中未找到日期列")
                return None
            
            # 转换为标准格式
            df['date'] = pd.to_datetime(df['date'])
            
            # 确保必需的列都存在
            required_cols = ['date', 'open', 'high', 'low', 'close', 'volume']
            missing_cols = [col for col in required_cols if col not in df.columns]
            if missing_cols:
                logger.warning(f"akshare返回数据缺少列: {missing_cols}")
                return None
            
            # 选择并排序
            df = df[required_cols].copy()
            df = df.sort_values('date').reset_index(drop=True)
            
            # 数据类型转换
            numeric_cols = ['open', 'high', 'low', 'close', 'volume']
            for col in numeric_cols:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # 删除NaN行
            df = df.dropna()
            
            if df.empty:
                logger.warning(f"akshare数据清洗后为空")
                return None
            
            logger.info(f"✓ 从akshare获取 {code} 数据成功，共 {len(df)} 条记录")
            logger.debug(f"  日期范围: {df['date'].min()} 至 {df['date'].max()}")
            return df
            
        except ImportError:
            logger.debug("akshare未安装，使用: pip install akshare")
            return None
        except Exception as e:
            logger.warning(f"akshare获取数据失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return None
    
    def _fetch_from_tushare(self, code: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """
        从tushare获取股票历史数据
        
        Args:
            code: 股票代码
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            DataFrame或None
        """
        try:
            import tushare as ts
            logger.info(f"使用tushare获取 {code} 数据...")
            
            # 检查token配置
            tushare_token = DATA_CONFIG.get('tushare_token', '')
            if not tushare_token:
                logger.warning(f"tushare token未配置，请在config/settings.py中设置DATA_CONFIG['tushare_token']")
                return None
            
            logger.debug(f"Tushare token 长度: {len(tushare_token)}")
            
            # 设置token
            try:
                ts.set_token(tushare_token)
                pro = ts.pro_api()
                logger.debug("Tushare token 设置成功，pro_api 创建成功")
            except Exception as e:
                logger.error(f"tushare token设置失败: {type(e).__name__}: {e}")
                import traceback
                logger.debug(traceback.format_exc())
                return None
            
            # 转换股票代码格式（tushare需要带市场前缀）
            # 深市：000xxx/300xxx 以及 深市ETF常见前缀 15xxxx/16xxxx/18xxxx -> *.SZ
            # 沪市：600xxx 以及 沪市ETF常见前缀 51xxxx/56xxxx/58xxxx/59xxxx -> *.SH
            # 科创板：688xxx -> *.SH
            if code.startswith(('0', '3', '1')):
                ts_code = f"{code}.SZ"
            elif code.startswith(('6', '5', '688')):
                ts_code = f"{code}.SH"
            else:
                logger.warning(f"无法识别股票代码格式: {code}")
                return None
            
            logger.debug(f"转换后的 tushare 代码: {ts_code}")
            
            # 转换日期格式（tushare需要YYYYMMDD格式）
            start_date_str = start_date.replace('-', '')
            end_date_str = end_date.replace('-', '')
            
            logger.debug(f"请求参数: ts_code={ts_code}, start_date={start_date_str}, end_date={end_date_str}")
            
            # 调用tushare接口：优先使用 pro_bar 并开启前复权，无法使用时回退到 daily（不复权）
            df = None
            error_msgs = []
            
            # 方法1: 尝试 pro_bar（前复权）
            try:
                logger.debug(f"尝试使用 ts.pro_bar 获取数据（前复权）...")
                df = ts.pro_bar(
                    ts_code=ts_code,
                    start_date=start_date_str,
                    end_date=end_date_str,
                    adj='qfq',   # 前复权
                    freq='D',
                    asset='E',
                    fields='trade_date,open,high,low,close,vol'
                )
                logger.debug(f"ts.pro_bar 调用成功，返回数据行数: {len(df) if df is not None else 0}")
            except Exception as e1:
                error_msgs.append(f"pro_bar失败: {type(e1).__name__}: {str(e1)}")
                logger.debug(f"ts.pro_bar 失败: {e1}")
                
                # 方法2: 尝试 daily（不复权）
                try:
                    logger.debug(f"尝试使用 pro.daily 获取数据（不复权）...")
                    df = pro.daily(
                        ts_code=ts_code,
                        start_date=start_date_str,
                        end_date=end_date_str
                    )
                    logger.debug(f"pro.daily 调用成功，返回数据行数: {len(df) if df is not None else 0}")
                except Exception as e2:
                    error_msgs.append(f"daily失败: {type(e2).__name__}: {str(e2)}")
                    logger.debug(f"pro.daily 失败: {e2}")
            
            if df is None or df.empty:
                error_detail = " | ".join(error_msgs) if error_msgs else "未知错误"
                logger.error(f"tushare接口调用失败 - {code} ({ts_code}): {error_detail}")
                logger.error(f"请求参数: start_date={start_date_str}, end_date={end_date_str}")
                import traceback
                logger.debug(traceback.format_exc())
                return None
            
            logger.debug(f"tushare返回数据列: {list(df.columns)}")
            logger.debug(f"tushare返回数据行数: {len(df)}")
            
            # tushare返回的列名通常是：trade_date, open, high, low, close, vol
            # 需要转换为标准格式
            column_mapping = {
                'trade_date': 'date',
                'vol': 'volume'
            }
            
            # 重命名列
            df = df.rename(columns=column_mapping)
            
            # 如果日期列名不是date，尝试查找
            if 'date' not in df.columns:
                # 查找可能的日期列
                for col in df.columns:
                    if 'date' in col.lower() or '时间' in col:
                        df = df.rename(columns={col: 'date'})
                        logger.debug(f"找到日期列并重命名: {col} -> date")
                        break
            
            if 'date' not in df.columns:
                logger.error(f"tushare返回数据中未找到日期列，可用列: {list(df.columns)}")
                return None
            
            # 转换日期格式
            df['date'] = pd.to_datetime(df['date'], format='%Y%m%d', errors='coerce')
            
            # 确保必需的列都存在
            required_cols = ['date', 'open', 'high', 'low', 'close', 'volume']
            
            # 查找volume列（可能是vol）
            if 'volume' not in df.columns and 'vol' in df.columns:
                df = df.rename(columns={'vol': 'volume'})
            
            missing_cols = [col for col in required_cols if col not in df.columns]
            if missing_cols:
                logger.warning(f"tushare返回数据缺少列: {missing_cols}")
                return None
            
            # 选择并排序
            df = df[required_cols].copy()
            df = df.sort_values('date').reset_index(drop=True)
            
            # 数据类型转换
            numeric_cols = ['open', 'high', 'low', 'close', 'volume']
            for col in numeric_cols:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # 删除NaN行
            df = df.dropna()
            
            if df.empty:
                logger.warning(f"tushare数据清洗后为空")
                return None
            
            logger.info(f"✓ 从tushare获取 {code} 数据成功，共 {len(df)} 条记录")
            logger.debug(f"  日期范围: {df['date'].min()} 至 {df['date'].max()}")
            return df
            
        except ImportError:
            logger.debug("tushare未安装，使用: pip install tushare")
            return None
        except Exception as e:
            logger.warning(f"tushare获取数据失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return None

    def _fetch_etf_from_tushare(self, code: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """
        从tushare获取ETF日行情（fund_daily）
        """
        try:
            import tushare as ts
            logger.info(f"使用tushare获取ETF {code} 数据...")

            tushare_token = DATA_CONFIG.get('tushare_token', '')
            if not tushare_token:
                logger.debug("tushare token未配置，跳过ETF tushare获取")
                return None

            try:
                ts.set_token(tushare_token)
                pro = ts.pro_api()
            except Exception as e:
                logger.warning(f"tushare token设置失败: {e}")
                return None

            # 代码加市场后缀
            if code.startswith(('0', '3', '1')):
                ts_code = f"{code}.SZ"
            elif code.startswith(('6', '5')):
                ts_code = f"{code}.SH"
            else:
                logger.warning(f"无法识别ETF代码格式: {code}")
                return None

            start_date_str = start_date.replace('-', '')
            end_date_str = end_date.replace('-', '')

            try:
                df = pro.fund_daily(ts_code=ts_code, start_date=start_date_str, end_date=end_date_str)
            except Exception as e:
                logger.warning(f"tushare fund_daily 调用失败: {e}")
                return None

            if df is None or df.empty:
                logger.warning("tushare fund_daily 返回空数据")
                return None

            df = df.rename(columns={'trade_date': 'date', 'vol': 'volume'})
            if 'date' not in df.columns:
                for col in df.columns:
                    if 'date' in col.lower():
                        df = df.rename(columns={col: 'date'})
                        break
            if 'volume' not in df.columns and 'vol' in df.columns:
                df = df.rename(columns={'vol': 'volume'})

            if 'date' not in df.columns:
                logger.warning("tushare ETF 返回数据中未找到日期列")
                return None

            df['date'] = pd.to_datetime(df['date'], format='%Y%m%d', errors='coerce')
            required_cols = ['date', 'open', 'high', 'low', 'close', 'volume']
            missing_cols = [c for c in required_cols if c not in df.columns]
            if missing_cols:
                logger.warning(f"tushare ETF 返回缺少列: {missing_cols}")
                return None

            df = df[required_cols].sort_values('date').reset_index(drop=True)
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')

            df = df.dropna()
            if df.empty:
                logger.warning("tushare ETF 数据清洗后为空")
                return None

            logger.info(f"✓ 从tushare获取ETF {code} 数据成功，共 {len(df)} 条记录")
            return df
        except ImportError:
            logger.debug("tushare未安装，使用: pip install tushare")
            return None
        except Exception as e:
            logger.warning(f"tushare ETF 获取数据失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return None
    
    def _fetch_from_yfinance(self, code: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """
        从yfinance获取股票历史数据
        
        注意：yfinance主要用于国际股票，对A股支持有限
        对于A股，需要将代码转换为yfinance格式：000001.SZ 或 600000.SS
        
        Args:
            code: 股票代码（如'000001'）
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            DataFrame或None
        """
        try:
            import yfinance as yf
            logger.info(f"使用yfinance获取 {code} 数据...")
            
            # 转换股票代码格式（yfinance需要市场后缀）
            # 深市：000xxx/300xxx/深市ETF(1xxxxx) -> *.SZ
            # 沪市：600xxx/沪市ETF(5xxxxx) -> *.SS（yfinance使用SS而不是SH）
            if code.startswith(('0', '3', '1')):
                yf_symbol = f"{code}.SZ"
            elif code.startswith(('6', '5')):
                yf_symbol = f"{code}.SS"
            else:
                logger.warning(f"无法识别股票代码格式: {code}")
                return None
            
            # 创建ticker对象
            ticker = yf.Ticker(yf_symbol)
            
            # 转换日期格式（yfinance接受字符串格式）
            try:
                df = ticker.history(start=start_date, end=end_date)
            except Exception as e:
                logger.warning(f"yfinance接口调用失败: {e}")
                return None
            
            if df is None or df.empty:
                logger.warning(f"yfinance返回空数据，可能是代码格式问题或数据不可用")
                return None
            
            # yfinance返回的列名通常是：Open, High, Low, Close, Volume（首字母大写）
            # 需要转换为标准格式（小写）
            column_mapping = {
                'Open': 'open',
                'High': 'high',
                'Low': 'low',
                'Close': 'close',
                'Volume': 'volume'
            }
            
            # 检查列名（可能有Date作为索引）
            df = df.rename(columns=column_mapping)
            
            # yfinance的索引通常是日期
            if df.index.name is None or 'date' in str(df.index.name).lower():
                df = df.reset_index()
                # 检查是否有Date列
                for col in df.columns:
                    if 'date' in str(col).lower():
                        df = df.rename(columns={col: 'date'})
                        break
                # 如果仍然没有date列，使用索引
                if 'date' not in df.columns and not df.empty:
                    df['date'] = df.index
                    df = df.reset_index(drop=True)
            
            if 'date' not in df.columns:
                logger.warning("yfinance返回数据中未找到日期列")
                return None
            
            # 转换日期格式
            df['date'] = pd.to_datetime(df['date'])
            
            # 确保必需的列都存在
            required_cols = ['date', 'open', 'high', 'low', 'close', 'volume']
            
            missing_cols = [col for col in required_cols if col not in df.columns]
            if missing_cols:
                logger.warning(f"yfinance返回数据缺少列: {missing_cols}")
                return None
            
            # 选择并排序
            df = df[required_cols].copy()
            df = df.sort_values('date').reset_index(drop=True)
            
            # 数据类型转换
            numeric_cols = ['open', 'high', 'low', 'close', 'volume']
            for col in numeric_cols:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # 删除NaN行
            df = df.dropna()
            
            if df.empty:
                logger.warning(f"yfinance数据清洗后为空")
                return None
            
            logger.info(f"✓ 从yfinance获取 {code} 数据成功，共 {len(df)} 条记录")
            logger.debug(f"  日期范围: {df['date'].min()} 至 {df['date'].max()}")
            return df
            
        except ImportError:
            logger.debug("yfinance未安装，使用: pip install yfinance")
            return None
        except Exception as e:
            logger.warning(f"yfinance获取数据失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return None
    
    def _fetch_from_baostock(self, code: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """
        从baostock获取股票历史数据
        
        baostock是一个免费的A股数据接口，数据质量可靠，适合量化交易
        
        Args:
            code: 股票代码（如'000001'）
            start_date: 开始日期（格式：'YYYY-MM-DD'）
            end_date: 结束日期（格式：'YYYY-MM-DD'）
        
        Returns:
            DataFrame或None
        """
        try:
            import baostock as bs
            logger.info(f"使用baostock获取 {code} 数据...")
            
            # 登录baostock系统
            lg = bs.login()
            if lg.error_code != '0':
                logger.warning(f"baostock登录失败，错误代码：{lg.error_code}，错误信息：{lg.error_msg}")
                return None
            
            try:
                # 转换股票代码格式（baostock需要市场前缀）
                # 深市：000xxx/300xxx/深市ETF(1xxxxx) -> sz.xxxxxx
                # 沪市：600xxx/沪市ETF(5xxxxx) -> sh.xxxxxx
                if code.startswith(('0', '3', '1')):
                    bs_code = f"sz.{code}"
                elif code.startswith(('6', '5')):
                    bs_code = f"sh.{code}"
                else:
                    logger.warning(f"无法识别股票代码格式: {code}")
                    bs.logout()
                    return None
                
                # 查询历史K线数据
                # fields: date,code,open,high,low,close,volume,amount
                # adjustflag: 复权状态(1：后复权， 2：前复权，3：不复权）
                rs = bs.query_history_k_data_plus(
                    bs_code,
                    "date,open,high,low,close,volume",
                    start_date=start_date,
                    end_date=end_date,
                    frequency="d",  # d=日k线
                    adjustflag="2"  # 2=前复权（1后复权，3不复权）
                )
                
                if rs.error_code != '0':
                    logger.warning(f"baostock查询失败，错误代码：{rs.error_code}，错误信息：{rs.error_msg}")
                    bs.logout()
                    return None
                
                # 获取数据并转换为DataFrame
                data_list = []
                while rs.next():
                    data_list.append(rs.get_row_data())
                
                if not data_list:
                    logger.warning(f"baostock返回空数据")
                    bs.logout()
                    return None
                
                # 转换为DataFrame
                df = pd.DataFrame(data_list, columns=rs.fields)
                
                # baostock返回的列名：date, open, high, low, close, volume
                # 已经符合标准格式，只需确保列名正确
                if 'date' not in df.columns:
                    logger.warning("baostock返回数据中未找到日期列")
                    bs.logout()
                    return None
                
                # 转换日期格式
                df['date'] = pd.to_datetime(df['date'])
                
                # 确保必需的列都存在
                required_cols = ['date', 'open', 'high', 'low', 'close', 'volume']
                missing_cols = [col for col in required_cols if col not in df.columns]
                if missing_cols:
                    logger.warning(f"baostock返回数据缺少列: {missing_cols}")
                    bs.logout()
                    return None
                
                # 选择并排序
                df = df[required_cols].copy()
                df = df.sort_values('date').reset_index(drop=True)
                
                # 数据类型转换
                numeric_cols = ['open', 'high', 'low', 'close', 'volume']
                for col in numeric_cols:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                
                # 删除NaN行和成交量为0的行（停牌日）
                df = df.dropna()
                df = df[df['volume'] > 0].reset_index(drop=True)
                
                if df.empty:
                    logger.warning(f"baostock数据清洗后为空")
                    bs.logout()
                    return None
                
                logger.info(f"✓ 从baostock获取 {code} 数据成功，共 {len(df)} 条记录")
                logger.debug(f"  日期范围: {df['date'].min()} 至 {df['date'].max()}")
                return df
                
            finally:
                # 登出系统
                bs.logout()
            
        except ImportError:
            logger.debug("baostock未安装，使用: pip install baostock")
            return None
        except Exception as e:
            logger.warning(f"baostock获取数据失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return None
    
    def generate_mock_data(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        生成模拟数据（用于测试和开发）
        
        Args:
            code: 股票代码
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            DataFrame: 模拟的OHLC数据
        """
        logger.warning(f"使用模拟数据：{code} ({start_date} 至 {end_date})")
        
        # 生成日期序列
        start = pd.to_datetime(start_date)
        end = pd.to_datetime(end_date)
        dates = pd.date_range(start=start, end=end, freq='B')  # B = 工作日
        
        # 生成模拟价格数据（随机游走）
        n_days = len(dates)
        initial_price = 10.0 + np.random.uniform(-2, 2)
        
        # 生成收盘价（随机游走）
        returns = np.random.normal(0.001, 0.02, n_days)  # 日均收益率0.1%，波动率2%
        prices = [initial_price]
        for ret in returns[1:]:
            prices.append(prices[-1] * (1 + ret))
        
        # 生成OHLC数据
        data = []
        for i, (date, close) in enumerate(zip(dates, prices)):
            # 生成当天的高低价（相对于收盘价）
            volatility = np.random.uniform(0.01, 0.03)
            high = close * (1 + volatility * np.random.uniform(0.3, 1.0))
            low = close * (1 - volatility * np.random.uniform(0.3, 1.0))
            open_price = prices[i-1] if i > 0 else close
            
            # 确保 high >= close >= low, high >= open >= low
            high = max(high, close, open_price)
            low = min(low, close, open_price)
            
            volume = int(np.random.uniform(1000000, 10000000))
            
            data.append({
                'date': date,
                'open': round(open_price, 2),
                'high': round(high, 2),
                'low': round(low, 2),
                'close': round(close, 2),
                'volume': volume
            })
        
        df = pd.DataFrame(data)
        logger.info(f"生成模拟数据成功，共 {len(df)} 条记录")
        return df
    
    def fetch_stock_data(self, code: str, start_date: str, end_date: str, 
                        use_mock_if_fail: bool = False) -> pd.DataFrame:
        """
        获取股票历史数据（混合方案）
        优先级：数据库 → API → 模拟数据（可选）
        
        Args:
            code: 股票代码（如'000001'）
            start_date: 开始日期（格式：'YYYY-MM-DD'）
            end_date: 结束日期（格式：'YYYY-MM-DD'）
            use_mock_if_fail: 如果数据库和API都失败，是否使用模拟数据
        
        Returns:
            DataFrame: 包含date, open, high, low, close, volume列
            标准格式的股票历史数据
        """
        logger.info(f"获取股票 {code} 数据 ({start_date} 至 {end_date})")
        
        # 优先从数据库获取
        df = self.fetch_from_database(code, start_date, end_date)
        if df is not None and not df.empty:
            return df
        
        # 数据库失败，尝试从API获取
        logger.info("数据库未找到数据，尝试从API获取...")
        df = self.fetch_from_api(code, start_date, end_date)
        if df is not None and not df.empty:
            return df
        
        # API也失败，根据参数决定是否使用模拟数据
        if use_mock_if_fail:
            logger.info("API获取失败，使用模拟数据...")
            return self.generate_mock_data(code, start_date, end_date)
        else:
            # 不使用模拟数据，返回空DataFrame
            logger.warning(f"无法获取股票 {code} 的历史数据（数据库和API都失败），返回空数据")
            return pd.DataFrame()
    
    def __enter__(self):
        """上下文管理器入口"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器退出"""
        self.close_db()

