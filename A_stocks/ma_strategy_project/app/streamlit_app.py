#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
# 已移除 plotly 导入，使用数值替代图表以提升性能
# import plotly.express as px
# import plotly.graph_objects as go

# 允许从项目根目录导入包
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# 允许从项目父级目录导入（用于访问 manage_stocks.py）
PARENT_ROOT = os.path.dirname(ROOT)
if PARENT_ROOT not in sys.path:
    sys.path.insert(0, PARENT_ROOT)

from data.fetcher import DataFetcher
from strategies.moving_average import MovingAverageStrategy
from strategies.mean_reversion import MeanReversionStrategy
from backtest.engine import BacktestEngine
from backtest.analyzer import PerformanceAnalyzer
from backtest.portfolio import run_portfolio_backtest
from utils.visualization import plot_equity_curve, plot_price_ma_signals, plot_mean_reversion_signals
from utils.data_validator import validate_data_for_plot
from config.settings import BACKTEST_CONFIG, STRATEGY_DEFAULT_PARAMS
from optimization.grid_search import grid_search_ma

# 导入股票管理器
try:
    from manage_stocks import StockManager
except ImportError:
    StockManager = None


def display_chart(chart_result: str, caption: str = "", height: int = 1000):
    """
    显示图表，自动检测是HTML字符串还是文件路径
    
    Args:
        chart_result: 图表结果（HTML字符串或文件路径）
        caption: 图表标题
        height: HTML图表高度（像素），默认1000以确保完整显示
    """
    try:
        from utils.logger import logger
        logger.info(f"[display_chart] 函数被调用: chart_result类型={type(chart_result)}, 长度={len(chart_result) if chart_result else 0}, height={height}")
    except Exception:
        pass
    
    if not chart_result:
        try:
            from utils.logger import logger
            logger.warning("[display_chart] chart_result为空，不显示图表")
        except Exception:
            pass
        return
    
    # 检测是否为HTML字符串（mpld3或Plotly生成的HTML）
    lower = chart_result.strip().lower()
    if (lower.startswith('<!doctype') or lower.startswith('<html') or 
        lower.startswith('<div') or 'mpld3' in lower[:500] or 
        'plotly' in lower[:500] or 'plotly.js' in lower[:1000]):
        # 是HTML字符串，使用components.html显示
        try:
            from utils.logger import logger
            logger.info(f"[display_chart] 检测到HTML字符串，使用components.html显示，高度={height}")
            
            # 验证HTML完整性（支持mpld3和Plotly）
            html_checks = {
                '包含图表库': 'mpld3' in chart_result.lower() or 'plotly' in chart_result.lower(),
                '包含script标签': '<script' in chart_result.lower(),
                '包含图表元素': '<svg' in chart_result.lower() or 'plotly' in chart_result.lower() or 'mpld3' in chart_result.lower(),
                '长度合理': len(chart_result) > 1000
            }
            
            failed_checks = [k for k, v in html_checks.items() if not v]
            if failed_checks:
                logger.warning(f"[display_chart] HTML验证失败项: {failed_checks}")
                # 显示诊断信息
                with st.expander("⚠️ HTML验证警告", expanded=False):
                    st.write("**检查结果:**")
                    for check, passed in html_checks.items():
                        st.write(f"{'✓' if passed else '✗'} {check}: {passed}")
                    st.write(f"\n**HTML长度:** {len(chart_result)} 字符")
                    st.write(f"\n**前500字符预览:**")
                    st.code(chart_result[:500], language='html')
        except Exception:
            pass
        
        # 设置足够的高度并禁用滚动，确保图表完整显示在固定区域内
        # 使用unsafe_allow_html=False确保安全，但允许JavaScript执行
        # 注意：某些Streamlit版本不支持key参数，已移除
        try:
            components.html(
                chart_result, 
                height=height, 
                scrolling=False
            )
        except Exception as e:
            st.error(f"图表渲染失败: {str(e)}")
            with st.expander("查看错误详情", expanded=False):
                import traceback
                st.code(traceback.format_exc())
            # 尝试使用markdown作为备用方案
            try:
                st.warning("⚠️ 图表渲染失败，尝试备用显示方式...")
                st.markdown(f'<div style="height:{height}px; overflow:auto;">{chart_result}</div>', unsafe_allow_html=True)
            except Exception:
                pass
        if caption:
            st.caption(caption)
    else:
        # 是文件路径，使用st.image显示
        try:
            from utils.logger import logger
            logger.info(f"[display_chart] 检测到文件路径: {chart_result}, 文件存在: {os.path.exists(chart_result)}")
        except Exception:
            pass
        if os.path.exists(chart_result):
            st.image(chart_result, caption=caption)
        else:
            try:
                from utils.logger import logger
                logger.error(f"[display_chart] 文件不存在: {chart_result}")
            except Exception:
                pass


st.set_page_config(page_title="股票历史回测系统", layout="wide")
st.title("股票历史回测系统")

# 添加表格样式CSS（只在页面加载时执行一次）
st.markdown("""
<style>
.dataframe th, .dataframe td {
    text-align: center !important;
}
[data-testid="stDataFrame"] table {
    margin: 0 auto;
}
/* 放大涨跌幅箭头大小，保持整体文本整洁 */
[data-testid="stMetricDelta"] svg {
    width: 28px !important;
    height: 28px !important;
    min-width: 28px !important;
    min-height: 28px !important;
    vertical-align: middle !important;
}
[data-testid="stMetricDelta"] {
    font-size: 18px !important;
    font-weight: 600 !important;
    line-height: 1.5 !important;
    display: inline-flex !important;
    align-items: center !important;
    gap: 4px !important;
}
/* 确保metric组件整体对齐 */
[data-testid="stMetricValue"] {
    font-size: 24px !important;
    font-weight: 700 !important;
}
[data-testid="stMetricLabel"] {
    font-size: 14px !important;
    font-weight: 500 !important;
}
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def get_stock_manager():
    """获取缓存的 StockManager 实例"""
    if StockManager is None:
        return None
    try:
        manager = StockManager()
        if manager.connection:
            return manager
        else:
            return None
    except Exception as e:
        st.error(f"数据库连接失败: {e}")
        return None


# 列名映射字典：数据库列名 -> 用户友好的中文名称
COLUMN_NAME_MAP = {
    'code': '股票代码',
    'name': '股票名称',
    'current_price': '现价',
    'change_amount': '涨跌额',
    'change_percent': '涨跌幅(%)',
    'high_price': '最高价',
    'low_price': '最低价',
    'open_price': '开盘价',
    'pre_close_price': '昨收价',
    'volume': '成交量',
    'turnover': '成交额',
    'total_market_value': '总市值',
    'circulating_market_value': '流通市值',
    'industry': '所属行业',
    'pe_ratio': '市盈率',
    'pb_ratio': '市净率',
    'change_5days': '5日涨跌幅(%)',
    'change_10days': '10日涨跌幅(%)',
    'change_20days': '20日涨跌幅(%)',
}


def process_dataframe_for_display(df: pd.DataFrame) -> pd.DataFrame:
    """
    处理DataFrame以便更好地展示：
    1. 删除全为空的列
    2. 重命名列为用户友好的中文名称
    3. 处理None和空值
    4. 将股票代码列过滤为纯数字（去掉SH/SZ前缀）
    5. 将市值列格式化为"亿"为单位
    """
    if df.empty:
        return df
    
    # 创建副本避免修改原始数据
    df_processed = df.copy()
    
    # 1. 替换字符串'None'为NaN，以便dropna正确识别
    df_processed = df_processed.replace(['None', 'null', ''], np.nan)
    
    # 2. 删除全为空的列
    df_processed = df_processed.dropna(axis=1, how='all')
    
    # 3. 只重命名存在于DataFrame中的列
    columns_to_rename = {col: new_name for col, new_name in COLUMN_NAME_MAP.items() 
                         if col in df_processed.columns}
    df_processed = df_processed.rename(columns=columns_to_rename)
    
    # 4. 如果存在"股票代码"列，将其过滤为纯数字
    if '股票代码' in df_processed.columns:
        df_processed['股票代码'] = df_processed['股票代码'].apply(
            lambda x: extract_stock_code_number(str(x)) if pd.notna(x) and str(x) else x
        )
    
    # 5. 格式化市值列为"亿"单位（除以100000000）
    # 重要：格式化后会变成字符串（如"1315.50亿"），Streamlit表格的交互式排序会按字符串排序
    # 因此在格式化前，如果有市值列，先按数值排序确保默认顺序正确
    market_value_columns = ['总市值', '流通市值']
    
    # 在格式化前，如果存在市值列，按总市值升序排序（从小到大）
    # 这样可以确保默认显示顺序正确，即使格式化后变成字符串
    # 注意：格式化后市值列变成字符串（如"1315.50亿"），Streamlit表格的交互式排序会按字符串排序，
    # 导致排序不正确（如"10284.09亿"会排在"1029.77亿"前面）。因此必须在格式化前按数值排序。
    if '总市值' in df_processed.columns:
        try:
            # 确保总市值列为数值类型
            df_processed['总市值_numeric'] = pd.to_numeric(df_processed['总市值'], errors='coerce')
            # 按总市值升序排序（从小到大）
            df_processed = df_processed.sort_values('总市值_numeric', ascending=True, na_position='last')
            # 删除临时排序列
            df_processed = df_processed.drop(columns=['总市值_numeric'])
        except:
            pass  # 如果排序失败，继续格式化
    
    # 格式化市值列为"亿"单位
    for col in market_value_columns:
        if col in df_processed.columns:
            def format_market_value(x):
                try:
                    if pd.isna(x) or x == '' or str(x).strip() == '' or str(x) == 'None':
                        return ''
                    # 转换为数值并除以1亿
                    value = float(x) / 100000000
                    return f"{value:.2f}亿"
                except (ValueError, TypeError):
                    return str(x) if pd.notna(x) else ''
            
            df_processed[col] = df_processed[col].apply(format_market_value)
    
    return df_processed


def extract_stock_code_number(code_str):
    """从股票代码中提取纯数字（去掉SH/SZ前缀）"""
    if pd.isna(code_str) or not code_str:
        return None
    code_str = str(code_str).strip()
    # 去掉SH、SZ前缀，提取数字部分
    code_str = code_str.replace('SH', '').replace('SZ', '').strip()
    # 提取数字
    import re
    match = re.search(r'\d+', code_str)
    if match:
        return match.group()
    return None


def render_dataframe_with_style(df: pd.DataFrame):
    """
    渲染DataFrame并应用居中样式
    
    注意：市值列已格式化为字符串（如"1315.50亿"），如果用户点击列头进行交互式排序，
    会按字符串排序导致结果不正确。因此数据已在查询时和格式化前按数值正确排序。
    
    Args:
        df: 要显示的DataFrame
    """
    if df.empty:
        st.info("暂无数据")
        return
    
    # 检查是否包含市值列，如果是则提示排序限制
    if '总市值' in df.columns or '流通市值' in df.columns:
        st.caption("💡 提示：市值列已格式化为\"亿\"单位，数据已按数值正确排序。如需重新排序，请使用查询功能。")
    
    # 正常显示表格（数据已按市值升序排序）
    st.dataframe(df, width='stretch', hide_index=True)


def render_csi300_query_section():
    """渲染沪深300查询区域"""
    if StockManager is None:
        st.warning("⚠️ StockManager 未加载，请检查 manage_stocks.py 是否在正确位置")
        return
    
    manager = get_stock_manager()
    if manager is None:
        st.error("⚠️ 无法连接到数据库，请检查数据库配置")
        return
    
    st.markdown("---")
    st.header("📊 沪深300成分股查询")
    
    # 获取统计信息
    try:
        stats = manager.get_change_statistics()
        industry_dist = manager.get_industry_distribution()
    except Exception as e:
        st.error(f"获取统计信息失败: {e}")
        stats = None
        industry_dist = []
    
    # 显示全局统计（使用数值替代图表，提升性能）
    if stats:
        # 统计指标显示
        col1, col2, col3, col4, col5, col6 = st.columns(6)
        
        with col1:
            st.metric("总股票数", f"{stats['total']}")
        
        gainers = stats.get('gainers', 0) or 0
        losers = stats.get('losers', 0) or 0
        total_changed = gainers + losers
        
        with col2:
            if total_changed > 0:
                gainer_pct = (gainers / total_changed * 100) if total_changed > 0 else 0
                st.metric("上涨股票", f"{gainers}", f"{gainer_pct:.1f}%")
            else:
                st.metric("上涨股票", "0", "0%")
        
        with col3:
            if total_changed > 0:
                loser_pct = (losers / total_changed * 100) if total_changed > 0 else 0
                # 使用负数delta显示向下的红色箭头，保留一位小数（使用数值而不是字符串）
                st.metric("下跌股票", f"{losers}", delta=-round(loser_pct, 1))
            else:
                st.metric("下跌股票", "0", delta=0)
        
        avg_change = stats.get('avg_change') if stats.get('avg_change') is not None else 0
        max_change = stats.get('max_change') if stats.get('max_change') is not None else 0
        min_change = stats.get('min_change') if stats.get('min_change') is not None else 0
        
        with col4:
            st.metric("平均涨跌幅", f"{avg_change:+.2f}%")
        
        with col5:
            # 最大涨幅：只显示箭头指示，不显示主数值文本
            if max_change > 0:
                st.metric("最大涨幅", "", delta=round(max_change, 2))
            else:
                st.metric("最大涨幅", "0.00%")
        
        with col6:
            # 最大跌幅：只显示箭头指示，不显示主数值文本
            if min_change < 0:
                st.metric("最大跌幅", "", delta=round(min_change, 2))
            else:
                st.metric("最大跌幅", "0.00%")
    
    # 多标签页查询
    tab1, tab2, tab3, tab4 = st.tabs(["单一条件查询", "多条件组合查询", "涨跌幅榜", "全部记录"])
    
    with tab1:
        st.subheader("单一条件查询")
        
        # 第一行：查询类型选择和具体查询输入框（长度一致）
        col_type, col_input = st.columns([1, 1])
        with col_type:
            query_type = st.selectbox("选择查询类型", 
                                      ["按股票名称查询", "按行业查询", "按价格范围查询"],
                                      key="single_query_type")
        
        # 根据查询类型显示相应的输入控件
        if query_type == "按股票名称查询":
            with col_input:
                name = st.text_input("股票名称（支持模糊查询）", key="single_name")
            
            # 查询按钮：约6个字符宽度，左对齐
            col_btn_left, col_btn_right = st.columns([6, 20])
            with col_btn_left:
                if st.button("查询", key="btn_single_name", use_container_width=True):
                    if name:
                        # 异步查询操作
                        with st.spinner("查询中..."):
                            results = manager.query_stock_by_name(name)
                            st.session_state['single_query_results'] = results
                            st.rerun()
                    else:
                        st.warning("请输入股票名称")
        
        elif query_type == "按行业查询":
            # 动态获取行业列表
            industries = [ind['industry'] for ind in industry_dist if ind['industry']]
            if industries:
                with col_input:
                    industry = st.selectbox("选择行业", ["全部"] + industries, key="single_industry")
                
                # 查询按钮：约6个字符宽度，左对齐
                col_btn_left, col_btn_right = st.columns([6, 20])
                with col_btn_left:
                    if st.button("查询", key="btn_single_industry", use_container_width=True):
                        # 异步查询操作
                        with st.spinner("查询中..."):
                            if industry == "全部":
                                # 选择"全部"时，返回所有记录
                                results = manager.query_all_stocks()
                            else:
                                # 选择具体行业时，返回该行业的记录
                                results = manager.query_stock_by_industry(industry)
                            st.session_state['single_query_results'] = results
                            st.rerun()
            else:
                st.warning("暂无行业数据")
        
        elif query_type == "按价格范围查询":
            with col_input:
                col_price1, col_price2 = st.columns(2)
                with col_price1:
                    min_price = st.slider("最低价格", min_value=0.0, max_value=300.0, 
                                         value=0.0, step=0.1, key="single_min_price")
                    st.caption(f"当前: {min_price:.2f}")
                with col_price2:
                    max_price = st.slider("最高价格", min_value=0.0, max_value=300.0, 
                                         value=300.0, step=0.1, key="single_max_price")
                    st.caption(f"当前: {max_price:.2f}")
            
            # 查询按钮：约6个字符宽度，左对齐
            col_btn_left, col_btn_right = st.columns([6, 20])
            with col_btn_left:
                if st.button("查询", key="btn_single_price", use_container_width=True):
                    if min_price <= max_price:
                        # 异步查询操作
                        with st.spinner("查询中..."):
                            results = manager.query_by_price_range(min_price, max_price)
                            st.session_state['single_query_results'] = results
                            st.rerun()
                    else:
                        st.warning("最低价格不能大于最高价格")
        
        # 在所有控件下方统一显示结果（适用于所有查询类型）
        if 'single_query_results' in st.session_state:
            results = st.session_state['single_query_results']
            if results and len(results) > 0:
                df_results = pd.DataFrame(results)
                st.success(f"找到 {len(results)} 条记录")
                df_display = process_dataframe_for_display(df_results)
                render_dataframe_with_style(df_display)
            else:
                st.info("未找到匹配的记录")
        else:
            # 如果没有任何结果，显示占位
            st.info("请输入查询条件并点击查询按钮")
    
    with tab2:
        st.subheader("多条件组合查询")
        st.caption("可以同时设置多个条件进行组合查询（AND关系）")
        
        # 第一行：查询条件控件
        col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
        
        with col1:
            name_filter = st.text_input("股票名称（可选）", key="filter_name", placeholder="留空不限")
        
        with col2:
            industries = [ind['industry'] for ind in industry_dist if ind['industry']]
            if industries:
                industry_filter = st.selectbox("行业（可选）", ["全部"] + industries, key="filter_industry")
                if industry_filter == "全部":
                    industry_filter = None
            else:
                industry_filter = None
                st.selectbox("行业（可选）", ["暂无行业数据"], key="filter_industry_disabled", disabled=True)
        
        with col3:
            # 直接显示最低价格滑块，不使用复选框
            min_price_filter = st.slider("最低价格", min_value=0.0, max_value=300.0,
                                        value=0.0, step=0.1, key="filter_min_price")
            st.caption(f"当前: {min_price_filter:.2f}")
        
        with col4:
            # 直接显示最高价格滑块，不使用复选框
            max_price_filter = st.slider("最高价格", min_value=0.0, max_value=300.0,
                                        value=300.0, step=0.1, key="filter_max_price")
            st.caption(f"当前: {max_price_filter:.2f}")
        
        # 第二行：查询按钮（左对齐）
        col_btn_left, col_btn_right = st.columns([6, 20])
        with col_btn_left:
            if st.button("查询", key="btn_filter", use_container_width=True):
                name_param = name_filter.strip() if name_filter and name_filter.strip() else None
                # 异步查询操作，使用spinner显示加载状态
                with st.spinner("查询中..."):
                    results = manager.query_with_filters(
                        name=name_param,
                        industry=industry_filter,
                        min_price=min_price_filter,
                        max_price=max_price_filter
                    )
                    st.session_state['filter_results'] = results
                    st.rerun()
        
        # 显示查询结果（从session_state读取，避免触发回测）
        if 'filter_results' in st.session_state:
            results = st.session_state['filter_results']
            if results:
                df_results = pd.DataFrame(results)
                st.success(f"找到 {len(results)} 条记录")
                df_display = process_dataframe_for_display(df_results)
                render_dataframe_with_style(df_display)
            else:
                st.info("未找到匹配的记录")
    
    with tab3:
        st.subheader("涨跌幅榜")
        col_gain, col_lose = st.columns(2)
        
        with col_gain:
            st.markdown("### 📈 涨幅榜")
            top_n_gain = st.number_input("显示前N名", min_value=5, max_value=50, value=15, key="top_n_gain")
            if st.button("查询涨幅榜", key="btn_gainers"):
                # 异步查询操作，使用spinner显示加载状态
                with st.spinner("查询中..."):
                    st.session_state['gainers_results'] = manager.query_top_gainers(top_n_gain)
                    st.rerun()
            
            # 显示查询结果（从session_state读取，避免触发回测）
            if 'gainers_results' in st.session_state:
                results_gain = st.session_state['gainers_results']
                if results_gain:
                    df_gain = pd.DataFrame(results_gain)
                    st.success(f"显示前 {len(results_gain)} 名")
                    df_display = process_dataframe_for_display(df_gain)
                    render_dataframe_with_style(df_display)
                else:
                    st.info("暂无数据")
        
        with col_lose:
            st.markdown("### 📉 跌幅榜")
            top_n_lose = st.number_input("显示前N名", min_value=5, max_value=50, value=15, key="top_n_lose")
            if st.button("查询跌幅榜", key="btn_losers"):
                # 异步查询操作，使用spinner显示加载状态
                with st.spinner("查询中..."):
                    st.session_state['losers_results'] = manager.query_top_losers(top_n_lose)
                    st.rerun()
            
            # 显示查询结果（从session_state读取，避免触发回测）
            if 'losers_results' in st.session_state:
                results_lose = st.session_state['losers_results']
                if results_lose:
                    df_lose = pd.DataFrame(results_lose)
                    st.success(f"显示前 {len(results_lose)} 名")
                    df_display = process_dataframe_for_display(df_lose)
                    render_dataframe_with_style(df_display)
                else:
                    st.info("暂无数据")
    
    with tab4:
        st.subheader("全部记录")
        
        # 点击按钮时查询数据（不自动查询，需要用户点击）
        if st.button("查询全部记录", key="btn_all"):
            with st.spinner("查询中..."):
                results_all = manager.query_all_stocks()
                st.session_state['all_results'] = results_all
                st.rerun()
        
        # 显示查询结果（停留在当前标签页，位于按钮下方）
        if 'all_results' in st.session_state:
            results_all = st.session_state['all_results']
            if results_all and len(results_all) > 0:
                df_all = pd.DataFrame(results_all)
                st.success(f"共 {len(results_all)} 条记录")
                df_display = process_dataframe_for_display(df_all)
                render_dataframe_with_style(df_display)
            else:
                st.info("暂无数据或查询失败，请检查数据源")
        else:
            st.info("点击上方按钮查询全部记录")
    
    st.markdown("---")


@st.cache_data(show_spinner=False)
def load_data(code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """加载股票数据，如果数据为空则返回空DataFrame，不再使用模拟数据"""
    if not code or not code.strip():
        return pd.DataFrame()
    
    with DataFetcher() as fetcher:
        try:
            # 不使用模拟数据，如果数据为空则返回空DataFrame
            data = fetcher.fetch_stock_data(code, start_date, end_date, use_mock_if_fail=False)
            return data if data is not None and not data.empty else pd.DataFrame()
        except (ValueError, Exception) as e:
            # 如果获取数据失败，返回空DataFrame
            import logging
            logging.warning(f"获取股票 {code} 数据失败: {e}")
            return pd.DataFrame()


def run_single_backtest(code: str, start_date: str, end_date: str, strategy):
    """运行单标回测，如果数据为空则返回None"""
    data = load_data(code, start_date, end_date)
    
    # 检查数据是否为空
    if data is None or data.empty:
        return None, None, None
    
    engine = BacktestEngine(strategy=strategy, initial_capital=BACKTEST_CONFIG['initial_capital'], commission=BACKTEST_CONFIG['commission'])
    results = engine.run(data)
    analyzer = PerformanceAnalyzer()
    analysis = analyzer.analyze(results)
    return data, results, analysis


def import_csi300_from_excel(manager, uploaded_file):
    """
    从上传的Excel文件导入沪深300数据到数据库
    
    Args:
        manager: StockManager实例
        uploaded_file: Streamlit上传的文件对象
    
    Returns:
        tuple: (success: bool, message: str, stats: dict)
    """
    if manager is None or not manager.connection:
        return False, "数据库连接失败", None
    
    try:
        import io
        # 1) 读取文件
        file_content = uploaded_file.read()
        file_name = uploaded_file.name.lower()
        
        # 尝试多种方式读取：先尝试CSV（tab分隔，多种编码），再尝试Excel
        df = None
        read_error = None
        
        # 如果是Excel文件，优先尝试Excel读取
        if file_name.endswith(('.xls', '.xlsx')):
            try:
                # 尝试使用pandas的Excel读取器
                if file_name.endswith('.xls'):
                    # 对于.xls文件，尝试使用xlrd引擎
                    try:
                        df = pd.read_excel(io.BytesIO(file_content), engine='xlrd')
                    except Exception:
                        # 如果xlrd不可用，尝试默认引擎
                        df = pd.read_excel(io.BytesIO(file_content))
                else:
                    # 对于.xlsx文件，使用openpyxl引擎
                    try:
                        df = pd.read_excel(io.BytesIO(file_content), engine='openpyxl')
                    except Exception:
                        # 如果openpyxl不可用，尝试默认引擎
                        df = pd.read_excel(io.BytesIO(file_content))
            except Exception as e:
                read_error = f"Excel读取失败: {str(e)}"
        
        # 如果Excel读取失败或不是Excel文件，尝试CSV
        if df is None:
            try:
                df = pd.read_csv(io.BytesIO(file_content), sep='\t', encoding='gbk')
            except Exception as e1:
                try:
                    df = pd.read_csv(io.BytesIO(file_content), sep='\t', encoding='gb2312')
                except Exception as e2:
                    try:
                        df = pd.read_csv(io.BytesIO(file_content), sep='\t', encoding='utf-8')
                    except Exception as e3:
                        error_msg = "无法读取文件"
                        if read_error:
                            error_msg += f"。{read_error}"
                        error_msg += "。请确保文件格式为Excel (.xls/.xlsx) 或CSV (tab分隔)"
                        raise ValueError(error_msg)
        
        if df.empty:
            return False, "文件为空或格式不正确", None
        
        # 检查必要的列是否存在
        required_columns = ['代码', '名称']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            available_columns = ', '.join(df.columns.tolist()[:10])  # 显示前10个列名
            return False, f"文件缺少必要的列: {', '.join(missing_columns)}。文件中的列: {available_columns}...", None
        
        # 2) 数据清洗和映射
        def fmt_percent(v):
            if pd.isna(v) or v == '':
                return None
            s = str(v).strip()
            s = s.replace('%', '')
            if s.startswith('+'):
                s = s.replace('+', '')
            try:
                return float(s)
            except Exception:
                return None

        def fmt_num(v):
            if pd.isna(v) or v == '':
                return None
            try:
                return float(v)
            except Exception:
                return None

        records = []
        for _, row in df.iterrows():
            code = str(row.get('代码', '')).strip() if pd.notna(row.get('代码')) else None
            name = str(row.get('名称', '')).strip() if pd.notna(row.get('名称')) else None
            current_price = fmt_num(row.get('现价'))
            change_percent = fmt_percent(row.get('涨幅'))
            change_amount = round(current_price * change_percent / 100, 2) if (current_price is not None and change_percent is not None) else None
            total_mv = fmt_num(row.get('总市值'))
            circ_mv = fmt_num(row.get('流通市值'))
            industry = str(row.get('所属行业', '')).strip() if pd.notna(row.get('所属行业')) else None
            pe_ratio = fmt_num(row.get('市盈(动)'))
            pb_ratio = fmt_num(row.get('市净率'))
            chg5 = fmt_percent(row.get('5日涨幅'))
            chg10 = fmt_percent(row.get('10日涨幅'))
            chg20 = fmt_percent(row.get('20日涨幅'))

            records.append((
                code, name, current_price, change_amount, change_percent,
                None, None, None, None,  # high_price, low_price, open_price, pre_close_price
                None, None,  # volume, turnover
                total_mv, circ_mv, industry, pe_ratio, pb_ratio,
                chg5, chg10, chg20
            ))
        
        if not records:
            return False, "没有有效的数据记录可以导入", None

        # 3) 清空表并插入
        try:
            with manager.connection.cursor() as cursor:
                cursor.execute("TRUNCATE TABLE csi300_stocks")
                insert_sql = (
                    "INSERT INTO csi300_stocks "
                    "(code, name, current_price, change_amount, change_percent, "
                    " high_price, low_price, open_price, pre_close_price, "
                    " volume, turnover, total_market_value, circulating_market_value, "
                    " industry, pe_ratio, pb_ratio, change_5days, change_10days, change_20days) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
                )
                affected = cursor.executemany(insert_sql, records)
                # 处理executemany可能返回元组的情况
                if isinstance(affected, tuple):
                    affected = affected[0] if len(affected) > 0 else len(records)
                elif affected is None:
                    affected = len(records)
                manager.connection.commit()
        except Exception as db_error:
            manager.connection.rollback()
            raise Exception(f"数据库操作失败: {str(db_error)}")
        
        # 4) 验证数据
        with manager.connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) as c FROM csi300_stocks")
            total = cursor.fetchone()['c']
            cursor.execute("""
                SELECT 
                    SUM(change_percent IS NOT NULL) as has_change,
                    SUM(current_price IS NOT NULL) as has_price,
                    SUM(industry IS NOT NULL) as has_industry
                FROM csi300_stocks
            """)
            stats = cursor.fetchone()
        
        stats_dict = {
            'total': total,
            'affected': affected,
            'has_change': stats['has_change'],
            'has_price': stats['has_price'],
            'has_industry': stats['has_industry']
        }
        
        return True, f"成功导入 {affected} 条记录", stats_dict
        
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        # 提取更友好的错误信息
        error_msg = str(e)
        if not error_msg or error_msg == "(0, '')":
            error_msg = "未知错误，请检查文件格式和数据库连接"
        return False, f"导入失败: {error_msg}", None


def render_import_section():
    """在sidebar上方渲染沪深300数据导入区域"""
    manager = get_stock_manager()
    if manager is None:
        return
    
    with st.sidebar:
        st.markdown("---")
        st.header("📥 数据导入")
        
        uploaded_file = st.file_uploader(
            "上传沪深300.xls文件",
            type=['xls', 'xlsx', 'csv'],
            help="上传沪深300成分股Excel文件，将自动更新数据库表"
        )
        
        if uploaded_file is not None:
            # 显示文件信息
            st.info(f"📄 已选择文件: {uploaded_file.name}")
            
            # 确认按钮
            if st.button("🚀 开始导入", type="primary", use_container_width=True):
                with st.spinner("正在导入数据..."):
                    success, message, stats = import_csi300_from_excel(manager, uploaded_file)
                    
                    if success:
                        st.success(message)
                        if stats:
                            st.caption(f"总记录数: {stats['total']} | 有涨跌幅: {stats['has_change']} | 有价格: {stats['has_price']} | 有行业: {stats['has_industry']}")
                        # 清除缓存，使查询区域能立即看到新数据
                        st.cache_data.clear()
                        st.cache_resource.clear()  # 清除资源缓存，确保StockManager重新初始化
                        st.rerun()
                    else:
                        st.error(message)
        
        st.markdown("---")


def sidebar_controls():
    with st.sidebar:
        st.header("参数")
        # 初始加载时清空股票代码
        code = st.text_input("股票代码", value="")
        
        # 添加开始回测按钮（紧接股票代码下方，方便直接点击）
        run_backtest = st.button("🚀 开始回测", type="primary", use_container_width=True)
        
        st.markdown("---")
        
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=365)
        s = st.date_input("开始日期", value=start_date)
        e = st.date_input("结束日期", value=end_date)
        s, e = str(s), str(e)

        strat_choice = st.selectbox("选择策略", ["MA 均线", "MR 均值回归"], index=0)
        # 策略参数
        if strat_choice.startswith("MA"):
            short_w = st.number_input("短期均线", min_value=2, max_value=120, value=STRATEGY_DEFAULT_PARAMS['moving_average']['short_window'])
            long_w = st.number_input("长期均线", min_value=5, max_value=300, value=STRATEGY_DEFAULT_PARAMS['moving_average']['long_window'])
            use_best = st.checkbox("先做网格搜索并应用最佳参数", value=False)
            mr_window = st.number_input("MR窗口（用于计算Z分数）", min_value=5, max_value=300, value=20, help="用于在MA图表中显示Z分数的滚动窗口大小")
            
            # 高级参数：提前信号
            st.markdown("**⚙️ 高级参数（优化买卖时机）**")
            enable_early = st.checkbox("启用提前信号", value=False, help="在均线接近交叉时提前发出买卖信号，减少踏空和卖飞")
            if enable_early:
                early_threshold = st.slider("提前信号阈值(%)", min_value=0.1, max_value=5.0, value=2.0, step=0.1, 
                                           help="当两条均线距离小于此百分比时，提前发出信号")
            else:
                early_threshold = 2.0  # 即使禁用，也使用默认值（代码中会忽略）
            
            volume_confirm = st.checkbox("成交量确认", value=True, help="买入/卖出信号需要成交量放大确认")
            
            reverse_signals = st.checkbox("反转买卖信号", value=True, 
                                         help="启用后：上穿买入/下穿卖出（反向策略）。默认：下穿买入/上穿卖出（超跌买入，超涨卖出）")
            
            ma_advanced_params = {
                "enable_early_signals": enable_early,
                "early_signal_threshold": early_threshold,
                "volume_confirmation": volume_confirm,
                "reverse_signals": reverse_signals
            }
            mr_params = None
        else:
            window = st.number_input("窗口(window)", min_value=5, max_value=300, value=20)
            entry_z = st.number_input("进场Z阈值", min_value=0.5, max_value=5.0, value=2.0, step=0.1)
            exit_z = st.number_input("出场Z阈值", min_value=-1.0, max_value=2.0, value=0.0, step=0.1)
            short_w = long_w = None  # 占位
            use_best = False
            
            # 高级参数：提前信号
            st.markdown("**⚙️ 高级参数（优化买卖时机）**")
            enable_early_entry = st.checkbox("启用提前进场/出场", value=True, help="在Z分数接近阈值时提前发出信号，减少踏空和卖飞")
            if enable_early_entry:
                early_entry_threshold = st.slider("提前信号阈值(Z分数)", min_value=0.1, max_value=1.0, value=0.3, step=0.1,
                                                 help="当Z分数接近进场/出场阈值但未达到时，提前此数值发出信号")
            else:
                early_entry_threshold = 0.3
            
            momentum_confirm = st.checkbox("动量确认", value=False, help="买入需要价格下跌动量，卖出需要价格上涨动量")
            
            reverse_signals = st.checkbox("反转买卖信号", value=False, 
                                         help="启用后：超跌卖出/回归买入（反向策略）。默认：超跌买入/回归卖出（与MA策略一致）")
            
            mr_params = {
                "window": int(window), 
                "entry_z": float(entry_z), 
                "exit_z": float(exit_z),
                "enable_early_entry": enable_early_entry,
                "early_entry_threshold": early_entry_threshold,
                "momentum_confirmation": momentum_confirm,
                "reverse_signals": reverse_signals
            }
            mr_window = None  # MR策略不需要额外的窗口参数
            ma_advanced_params = None

        # 默认选择"单标回测"
        actions = st.multiselect(
            "选择要执行的功能",
            ["单标回测", "参数优化", "组合回测"],
            default=["单标回测"],
        )
        portfolio_codes = st.text_input("组合股票(逗号分隔)", value="600111,601318,600519")
        
        # 参数验证
        param_valid = True
        param_errors = []
        
        if not code or not code.strip():
            param_valid = False
            param_errors.append("股票代码不能为空")
        
        if strat_choice.startswith("MA"):
            if short_w is None or long_w is None:
                param_valid = False
                param_errors.append("MA策略需要设置短期和长期均线参数")
            elif short_w >= long_w:
                param_valid = False
                param_errors.append("短期均线周期必须小于长期均线周期")
        
        if param_errors:
            for error in param_errors:
                st.error(f"❌ {error}")
        
        if not param_valid:
            run_backtest = False  # 参数不完整时禁用回测
    
    return code, s, e, strat_choice, (None if short_w is None else int(short_w)), (None if long_w is None else int(long_w)), use_best, actions, [c.strip() for c in portfolio_codes.split(',') if c.strip()], mr_params, (int(mr_window) if mr_window is not None else None), ma_advanced_params, run_backtest


# 渲染沪深300查询区域（在标题下方）
render_csi300_query_section()

# 渲染导入功能（在sidebar上方，参数栏之前）
render_import_section()

code, s_date, e_date, strat_choice, short_w, long_w, use_best, actions, pf_codes, mr_params, mr_window, ma_advanced_params, run_backtest = sidebar_controls()


if strat_choice.startswith("MA") and ("参数优化" in actions) and use_best and run_backtest:
    data = load_data(code, s_date, e_date)
    if data is None or data.empty:
        st.error(f"无法获取股票 {code} 的历史数据，请检查股票代码是否正确或数据源是否可用")
    else:
        with st.spinner("正在网格搜索..."):
            best, _all = grid_search_ma(
                data,
                short_choices=[5, 10, 15],
                long_choices=[20, 40, 60, 90],
                initial_capital=BACKTEST_CONFIG['initial_capital'],
                commission=BACKTEST_CONFIG['commission'],
            )
            short_w, long_w = best.short_window, best.long_window
        st.success(f"最佳参数：短期 {short_w} 长期 {long_w} (按总收益率)")


if "单标回测" in actions and run_backtest:
    st.header("均线策略")
    st.subheader("单标回测")
    
    # 参数验证（双重检查）
    if not code or not code.strip():
        st.warning("⚠️ 请输入股票代码")
    elif strat_choice.startswith("MA") and (short_w is None or long_w is None or short_w >= long_w):
        st.warning("⚠️ MA策略参数设置不正确：短期均线周期必须小于长期均线周期")
    else:
        with st.spinner("回测中..."):
            # 构建策略对象
            if strat_choice.startswith("MA"):
                if ma_advanced_params:
                    strategy_obj = MovingAverageStrategy(
                        short_window=short_w, 
                        long_window=long_w,
                        early_signal_threshold=ma_advanced_params.get('early_signal_threshold', 2.0),
                        enable_early_signals=ma_advanced_params.get('enable_early_signals', True),
                        volume_confirmation=ma_advanced_params.get('volume_confirmation', False),
                        reverse_signals=ma_advanced_params.get('reverse_signals', False)
                    )
                else:
                    strategy_obj = MovingAverageStrategy(short_window=short_w, long_window=long_w)
            else:
                if mr_params:
                    strategy_obj = MeanReversionStrategy(**mr_params)
                else:
                    strategy_obj = MeanReversionStrategy()
            data, results, analysis = run_single_backtest(code, s_date, e_date, strategy_obj)
        
        # 检查回测结果是否为空
        if data is None or results is None or analysis is None:
            st.error(f"无法获取股票 {code} 的历史数据，请检查股票代码是否正确或数据源是否可用")
        else:
            # 报告和图表左对齐，放在同一列
            st.markdown(f"- 初始资金: {analysis['initial_capital']:.2f}")
            st.markdown(f"- 最终资产: {analysis['final_value']:.2f}")
            st.markdown(f"- 总收益率: {analysis['total_return']:+.2f}%  年化: {analysis['annual_return']:+.2f}%")
            st.markdown(f"- 夏普比率: {analysis['sharpe_ratio']:.2f}  最大回撤: {analysis['max_drawdown_pct']:.2f}%")
            st.markdown(f"- 交易次数: {analysis['num_trades']}")
            
            # 年化收益率计算公式详解
            with st.expander("📊 年化收益率计算公式", expanded=False):
                periods = analysis.get('periods', len(data))
                periods_per_year = 252  # 每年交易日数
                years = periods / periods_per_year
                total_return_pct = analysis['total_return']
                
                st.markdown("**计算公式：**")
                st.code(f"""
年化收益率 = ((1 + 总收益率 / 100) ^ (1 / 年数) - 1) × 100%

计算过程：
1. 总收益率 = {total_return_pct:.4f}%
2. 交易日数 = {periods} 天
3. 年数 = 交易日数 / 252 = {periods} / 252 = {years:.4f} 年
4. 年化收益率 = ((1 + {total_return_pct:.4f}% / 100) ^ (1 / {years:.4f}) - 1) × 100%
              = ((1 + {total_return_pct/100:.6f}) ^ ({1/years:.6f}) - 1) × 100%
              = ({analysis['annual_return']:.4f})%
                """, language="text")
            
            # 交易明细表格
            if 'trades' in results and len(results['trades']) > 0:
                with st.expander("📋 交易明细表（点击展开查看完整交易记录）", expanded=False):
                    # 准备交易明细数据
                    trades_df = pd.DataFrame(results['trades'])
                    
                    # 从回测数据中获取信号信息，用于校验
                    result_data = results['data']
                    
                    # 为每笔交易添加信号验证信息
                    enhanced_trades = []
                    for trade in results['trades']:
                        trade_date = pd.to_datetime(trade['date'])
                        # 找到交易日期对应的数据行
                        trade_row = result_data[result_data['date'] == trade_date]
                        if len(trade_row) > 0:
                            row = trade_row.iloc[0]
                            enhanced_trade = trade.copy()
                            
                            # 添加价格和信号信息
                            enhanced_trade['close'] = row.get('close', trade['price'])
                            
                            # MA策略相关信息
                            if 'ma_short' in row and 'ma_long' in row:
                                enhanced_trade['ma_short'] = row.get('ma_short', None)
                                enhanced_trade['ma_long'] = row.get('ma_long', None)
                                enhanced_trade['ma_diff_pct'] = ((row.get('ma_short', 0) - row.get('ma_long', 0)) / row.get('ma_long', 1) * 100) if row.get('ma_long', 0) > 0 else 0
                            
                            # MR策略相关信息
                            if 'z' in row:
                                enhanced_trade['z_score'] = row.get('z', None)
                                enhanced_trade['mr_mean'] = row.get('mr_mean', None)
                                enhanced_trade['mr_std'] = row.get('mr_std', None)
                            
                            # 信号类型
                            enhanced_trade['signal'] = row.get('signal', 0)
                            enhanced_trade['positions'] = row.get('positions', 0)
                            
                            # 添加校验标记（用于验证交易是否符合策略规则）
                            if strat_choice.startswith("MA"):
                                ma_short_val = row.get('ma_short')
                                ma_long_val = row.get('ma_long')
                                if pd.notna(ma_short_val) and pd.notna(ma_long_val):
                                    # 检查交易是否符合策略规则
                                    reverse_enabled = ma_advanced_params.get('reverse_signals', False) if ma_advanced_params else False
                                    if trade['type'] == 'BUY':
                                        # 买入：默认应该是下穿（短期 < 长期），反转时应该是上穿（短期 > 长期）
                                        if reverse_enabled:
                                            valid = ma_short_val > ma_long_val  # 反转：上穿买入
                                        else:
                                            valid = ma_short_val < ma_long_val  # 默认：下穿买入
                                        enhanced_trade['valid_signal'] = "✓" if valid else "✗"
                                    else:  # SELL
                                        # 卖出：默认应该是上穿（短期 > 长期），反转时应该是下穿（短期 < 长期）
                                        if reverse_enabled:
                                            valid = ma_short_val < ma_long_val  # 反转：下穿卖出
                                        else:
                                            valid = ma_short_val > ma_long_val  # 默认：上穿卖出
                                        enhanced_trade['valid_signal'] = "✓" if valid else "✗"
                                else:
                                    enhanced_trade['valid_signal'] = "-"
                            else:  # MR策略
                                z_val = row.get('z')
                                entry_z = mr_params.get('entry_z', 2.0) if mr_params else 2.0
                                exit_z = mr_params.get('exit_z', 0.0) if mr_params else 0.0
                                reverse_enabled = mr_params.get('reverse_signals', False) if mr_params else False
                                if pd.notna(z_val):
                                    if trade['type'] == 'BUY':
                                        # 买入：默认应该是 Z <= -entry_z（超跌），反转时应该是 Z >= exit_z
                                        if reverse_enabled:
                                            valid = z_val >= exit_z
                                        else:
                                            valid = z_val <= -entry_z
                                        enhanced_trade['valid_signal'] = "✓" if valid else "✗"
                                    else:  # SELL
                                        # 卖出：默认应该是 Z >= exit_z（回归），反转时应该是 Z <= -entry_z
                                        if reverse_enabled:
                                            valid = z_val <= -entry_z
                                        else:
                                            valid = z_val >= exit_z
                                        enhanced_trade['valid_signal'] = "✓" if valid else "✗"
                                else:
                                    enhanced_trade['valid_signal'] = "-"
                            
                            enhanced_trades.append(enhanced_trade)
                        else:
                            enhanced_trades.append(trade)
                    
                    trades_df = pd.DataFrame(enhanced_trades)
                    
                    # 格式化日期
                    if 'date' in trades_df.columns:
                        trades_df['date'] = pd.to_datetime(trades_df['date']).dt.strftime('%Y-%m-%d')
                    
                    # 添加序号
                    trades_df.insert(0, '序号', range(1, len(trades_df) + 1))
                    
                    # 格式化数值列
                    numeric_cols = ['price', 'shares', 'cost', 'proceeds', 'pnl', 'cash_after', 
                                   'close', 'ma_short', 'ma_long', 'ma_diff_pct', 
                                   'z_score', 'mr_mean', 'mr_std', 'signal', 'positions']
                    for col in numeric_cols:
                        if col in trades_df.columns:
                            if col in ['ma_diff_pct', 'z_score']:
                                trades_df[col] = trades_df[col].apply(lambda x: f"{x:.3f}" if pd.notna(x) else "-")
                            else:
                                trades_df[col] = trades_df[col].apply(lambda x: f"{x:.2f}" if pd.notna(x) else "-")
                    
                    # valid_signal 列已经是字符串，不需要格式化
                    
                    # 重命名列（根据策略类型显示不同列）
                    base_column_map = {
                        '序号': '序号',
                        'date': '交易日期',
                        'type': '类型',
                        'price': '成交价格',
                        'shares': '股数',
                        'cost': '买入成本',
                        'proceeds': '卖出收入',
                        'pnl': '盈亏',
                        'cash_after': '交易后现金'
                    }
                    
                    # 根据策略类型添加信号列
                    if strat_choice.startswith("MA"):
                        base_column_map.update({
                            'close': '收盘价',
                            'ma_short': '短期均线',
                            'ma_long': '长期均线',
                            'ma_diff_pct': '均线差值%',
                            'signal': '信号',
                            'positions': '持仓变化',
                            'valid_signal': '信号校验'
                        })
                    else:  # MR策略
                        base_column_map.update({
                            'close': '收盘价',
                            'z_score': 'Z分数',
                            'mr_mean': '均值',
                            'mr_std': '标准差',
                            'signal': '信号',
                            'positions': '持仓变化',
                            'valid_signal': '信号校验'
                        })
                    
                    # 只保留存在的列
                    display_cols = [col for col in base_column_map.keys() if col in trades_df.columns]
                    trades_df_display = trades_df[display_cols].copy()
                    trades_df_display = trades_df_display.rename(columns=base_column_map)
                    
                    # 显示表格
                    st.dataframe(trades_df_display, width='stretch', hide_index=True)
                    
                    # 添加说明
                    st.caption("💡 **信号说明：** 信号=1表示买入信号，信号=-1表示卖出信号。持仓变化=1表示开仓/加仓，持仓变化=-1表示平仓。")
                    st.caption("💡 **信号校验：** ✓表示交易符合策略规则，✗表示不符合（可能存在问题），-表示无法校验（数据缺失）。")
                    if strat_choice.startswith("MA"):
                        reverse_enabled = ma_advanced_params.get('reverse_signals', False) if ma_advanced_params else False
                        if reverse_enabled:
                            st.caption("💡 **MA策略规则（反转模式）：** 买入时短期均线应高于长期均线（上穿），卖出时短期均线应低于长期均线（下穿）。")
                        else:
                            st.caption("💡 **MA策略规则（默认模式）：** 买入时短期均线应低于长期均线（下穿），卖出时短期均线应高于长期均线（上穿）。")
                    else:
                        reverse_enabled = mr_params.get('reverse_signals', False) if mr_params else False
                        if reverse_enabled:
                            st.caption("💡 **MR策略规则（反转模式）：** 买入时Z分数应≥exit_z（回归），卖出时Z分数应≤-entry_z（超跌）。")
                        else:
                            st.caption("💡 **MR策略规则（默认模式）：** 买入时Z分数应≤-entry_z（超跌），卖出时Z分数应≥exit_z（回归）。")
                    
                    # 统计信息
                    buy_trades = [t for t in results['trades'] if t['type'] == 'BUY']
                    sell_trades = [t for t in results['trades'] if t['type'] == 'SELL']
                    
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("买入次数", len(buy_trades))
                    with col2:
                        st.metric("卖出次数", len(sell_trades))
                    with col3:
                        if len(sell_trades) > 0:
                            profitable = sum(1 for t in sell_trades if t.get('pnl', 0) > 0)
                            win_rate = (profitable / len(sell_trades)) * 100
                            st.metric("胜率", f"{win_rate:.1f}%")
                        else:
                            st.metric("胜率", "N/A")
                    with col4:
                        if len(sell_trades) > 0:
                            avg_pnl = np.mean([t.get('pnl', 0) for t in sell_trades])
                            st.metric("平均盈亏", f"{avg_pnl:+.2f}")
                        else:
                            st.metric("平均盈亏", "N/A")
            else:
                st.info("⚠️ 本次回测期间没有发生任何交易")
            
            try:
                # 权益曲线 - 使用折叠加载
                with st.expander("📈 权益曲线（点击展开查看）", expanded=False):
                    fig_path = plot_equity_curve(results['data'])
                    if fig_path:
                        st.image(fig_path, caption="权益曲线")
                # 价格+均线+买卖点（MA策略）或均值回归图表（MR策略）
                if strat_choice.startswith("MA"):
                    if ma_advanced_params:
                        strategy_for_signal = MovingAverageStrategy(
                            short_window=short_w, 
                            long_window=long_w,
                            early_signal_threshold=ma_advanced_params.get('early_signal_threshold', 2.0),
                            enable_early_signals=ma_advanced_params.get('enable_early_signals', True),
                            volume_confirmation=ma_advanced_params.get('volume_confirmation', False),
                            reverse_signals=ma_advanced_params.get('reverse_signals', False)
                        )
                    else:
                        strategy_for_signal = MovingAverageStrategy(short_window=short_w, long_window=long_w)
                    sig_df = strategy_for_signal.generate_signals(data)
                    # 计算Z分数并添加到数据中（用于在工具提示中显示）
                    if mr_window is not None:
                        mr_mean = sig_df['close'].rolling(window=int(mr_window), min_periods=1).mean()
                        mr_std = sig_df['close'].rolling(window=int(mr_window), min_periods=1).std(ddof=0)
                        mr_std = mr_std.replace(0, np.nan)
                        sig_df['z'] = (sig_df['close'] - mr_mean) / mr_std
                        sig_df['z'] = sig_df['z'].fillna(0)
                    
                    # 确保图表使用的数据与回测数据一致（使用回测引擎返回的数据，它包含完整的信号信息）
                    # 但需要确保sig_df的positions与result_data一致
                    chart_data = results['data'].copy()  # 使用回测引擎返回的数据，确保一致性
                    # 如果回测数据中没有ma_short/ma_long，从sig_df复制
                    if 'ma_short' not in chart_data.columns and 'ma_short' in sig_df.columns:
                        chart_data['ma_short'] = sig_df['ma_short']
                        chart_data['ma_long'] = sig_df['ma_long']
                    
                    # 验证数据完整性和有效性
                    price_fig = None
                    try:
                        from utils.logger import logger
                        logger.info(f"[streamlit_app] 准备生成MA策略图表: chart_data.shape={chart_data.shape}, columns={list(chart_data.columns)}")
                    except Exception:
                        pass
                    
                    if not validate_data_for_plot(chart_data, plot_type="ma", verbose=False):
                        st.warning("⚠️ 图表数据验证失败，请检查数据完整性")
                        try:
                            from utils.logger import logger
                            logger.warning("[streamlit_app] MA策略数据验证失败")
                        except Exception:
                            pass
                        # 显示详细验证信息
                        with st.expander("查看数据验证详情", expanded=False):
                            from utils.data_validator import validate_plot_data
                            validation_results = validate_plot_data(chart_data, plot_type="ma")
                            for key, (status, message) in validation_results.items():
                                if status:
                                    st.success(f"✓ {key}: {message}")
                                else:
                                    st.error(f"✗ {key}: {message}")
                    else:
                        try:
                            from utils.logger import logger
                            logger.info("[streamlit_app] 调用 plot_price_ma_signals")
                        except Exception:
                            pass
                        price_fig = plot_price_ma_signals(chart_data, interactive=True, stock_code=code)
                        try:
                            from utils.logger import logger
                            logger.info(f"[streamlit_app] plot_price_ma_signals 返回: {type(price_fig)}, 长度: {len(price_fig) if price_fig else 0}")
                        except Exception:
                            pass
                    
                    if price_fig:
                        st.markdown(f"**价格+均线+买卖点 (MA{short_w}/{long_w})**")
                        st.markdown("*提示：鼠标悬停在买卖点上可查看详细信息（日期、价格、Z分数等），移动鼠标可看到垂直参考线*")
                        display_chart(price_fig, height=900)
                    elif price_fig is None:
                        # 验证失败，不显示图表
                        pass
                    else:
                        st.warning("⚠️ 图表生成失败：函数返回空结果")
                else:
                    # MR策略：展示布林带和Z分数
                    if mr_params:
                        strategy_for_signal = MeanReversionStrategy(**mr_params)
                    else:
                        strategy_for_signal = MeanReversionStrategy()
                    sig_df = strategy_for_signal.generate_signals(data)
                    # 添加window参数到数据属性中（不使用DataFrame列，避免显示在图表上）
                    if mr_params and 'window' in mr_params:
                        sig_df.attrs['window'] = mr_params['window']
                    
                    # 确保图表使用的数据与回测数据一致（使用回测引擎返回的数据，它包含完整的信号信息）
                    chart_data_mr = results['data'].copy()  # 使用回测引擎返回的数据，确保一致性
                    
                    # 确保MR相关列存在（优先使用回测数据中的列，如果缺失则从sig_df复制）
                    required_mr_cols = ['z', 'mr_mean', 'mr_std']
                    missing_cols = [col for col in required_mr_cols if col not in chart_data_mr.columns]
                    
                    if missing_cols:
                        # 如果回测数据中缺少MR列，尝试从sig_df合并
                        if 'date' in chart_data_mr.columns and 'date' in sig_df.columns:
                            # 使用date作为键进行合并（最可靠的方法）
                            merge_cols = ['date'] + [col for col in required_mr_cols if col in sig_df.columns]
                            chart_data_mr = chart_data_mr.merge(
                                sig_df[merge_cols], 
                                on='date', 
                                how='left', 
                                suffixes=('', '_sig')
                            )
                            # 如果合并后有重复列（带_sig后缀），使用sig_df的值覆盖
                            for col in required_mr_cols:
                                if f'{col}_sig' in chart_data_mr.columns:
                                    # 如果原列存在，用原列填充NaN；否则直接使用_sig列
                                    if col in chart_data_mr.columns:
                                        chart_data_mr[col] = chart_data_mr[f'{col}_sig'].fillna(chart_data_mr[col])
                                    else:
                                        chart_data_mr[col] = chart_data_mr[f'{col}_sig']
                                    chart_data_mr.drop(columns=[f'{col}_sig'], inplace=True)
                        elif len(chart_data_mr) == len(sig_df):
                            # 长度相同，直接通过索引赋值
                            for col in missing_cols:
                                if col in sig_df.columns:
                                    chart_data_mr[col] = sig_df[col].values
                        else:
                            # 长度不同且没有date列，使用sig_df作为主要数据源
                            if all(col in sig_df.columns for col in required_mr_cols):
                                # 保留回测结果中的重要列
                                keep_cols = ['positions', 'total', 'cash', 'holdings', 'returns']
                                for keep_col in keep_cols:
                                    if keep_col in chart_data_mr.columns and keep_col not in sig_df.columns:
                                        if len(chart_data_mr) == len(sig_df):
                                            sig_df[keep_col] = chart_data_mr[keep_col].values
                                        else:
                                            # 长度不同，尝试通过索引对齐
                                            sig_df[keep_col] = 0  # 默认值
                                chart_data_mr = sig_df.copy()
                            else:
                                st.warning(f"警告：无法合并MR相关列 {missing_cols}，图表可能无法正常显示")
                    
                    # 保持window属性
                    if hasattr(sig_df, 'attrs') and 'window' in sig_df.attrs:
                        if not hasattr(chart_data_mr, 'attrs'):
                            chart_data_mr.attrs = {}
                        chart_data_mr.attrs['window'] = sig_df.attrs['window']
                    
                    # 验证数据完整性和有效性
                    try:
                        from utils.logger import logger
                        logger.info(f"[streamlit_app] 准备生成MR策略图表: chart_data_mr.shape={chart_data_mr.shape}, columns={list(chart_data_mr.columns)}")
                    except Exception:
                        pass
                    
                    if not validate_data_for_plot(chart_data_mr, plot_type="mr", verbose=False):
                        st.warning("⚠️ 图表数据验证失败，请检查数据完整性")
                        try:
                            from utils.logger import logger
                            logger.warning("[streamlit_app] MR策略数据验证失败")
                        except Exception:
                            pass
                        # 显示详细验证信息
                        with st.expander("查看数据验证详情", expanded=False):
                            from utils.data_validator import validate_plot_data
                            validation_results = validate_plot_data(chart_data_mr, plot_type="mr")
                            for key, (status, message) in validation_results.items():
                                if status:
                                    st.success(f"✓ {key}: {message}")
                                else:
                                    st.error(f"✗ {key}: {message}")
                    else:
                        try:
                            from utils.logger import logger
                            logger.info("[streamlit_app] 调用 plot_mean_reversion_signals")
                        except Exception:
                            pass
                        mr_fig = plot_mean_reversion_signals(
                            chart_data_mr, 
                            entry_z=mr_params['entry_z'] if mr_params else 2.0, 
                            exit_z=mr_params['exit_z'] if mr_params else 0.0,
                            interactive=True
                        )
                        try:
                            from utils.logger import logger
                            logger.info(f"[streamlit_app] plot_mean_reversion_signals 返回: {type(mr_fig)}, 长度: {len(mr_fig) if mr_fig else 0}")
                        except Exception:
                            pass
                        if mr_fig:
                            st.markdown(f"**均值回归策略 - 布林带与Z分数指标**")
                            st.markdown("*提示：鼠标悬停在买卖点上可查看详细信息（日期、价格、Z分数、索引等），移动鼠标可看到垂直参考线联动两个子图*")
                            display_chart(mr_fig, height=1200)
                        else:
                            st.warning("⚠️ 图表生成失败：函数返回空结果")
                            # 显示诊断信息
                            with st.expander("查看诊断信息", expanded=False):
                                st.write("**可能的原因：**")
                                st.write("1. 数据缺少必需列（close, mr_mean, mr_std, z）")
                                st.write("2. 数据全为NaN")
                                st.write("3. Plotly图表生成失败")
                                st.write("4. HTML生成失败")
                                st.write(f"\n**数据形状:** {chart_data_mr.shape}")
                                st.write(f"**数据列:** {list(chart_data_mr.columns)}")
                                # 检查关键列
                                for col in ['close', 'mr_mean', 'mr_std', 'z']:
                                    if col in chart_data_mr.columns:
                                        valid_count = chart_data_mr[col].notna().sum()
                                        st.write(f"- {col}: {valid_count}/{len(chart_data_mr)} 有效值")
                                    else:
                                        st.write(f"- {col}: ❌ 缺失")
            except Exception as e:
                st.error(f"图表生成失败: {str(e)}")
                import traceback
                st.code(traceback.format_exc())


if strat_choice.startswith("MA") and ("参数优化" in actions) and not use_best and run_backtest:
    st.subheader("参数优化 (网格搜索)")
    data = load_data(code, s_date, e_date)
    if data is None or data.empty:
        st.error(f"无法获取股票 {code} 的历史数据，请检查股票代码是否正确或数据源是否可用")
    else:
        with st.spinner("搜索中..."):
            best, table = grid_search_ma(
                data,
                short_choices=[5, 10, 15],
                long_choices=[20, 40, 60, 90],
                initial_capital=BACKTEST_CONFIG['initial_capital'],
                commission=BACKTEST_CONFIG['commission'],
            )
        st.write(f"建议参数：短期 {best.short_window} 长期 {best.long_window} (按总收益率)")


if ("组合回测" in actions) and strat_choice.startswith("MA") and run_backtest:
    st.subheader("组合回测 (等权)")
    if not pf_codes:
        st.warning("请输入组合股票代码")
    else:
        with st.spinner("组合回测中..."):
            pf = run_portfolio_backtest(
                pf_codes, s_date, e_date,
                BACKTEST_CONFIG['initial_capital'],
                BACKTEST_CONFIG['commission'],
                short_w, long_w,
            )
        if pf and pf.get('per_code'):
            st.write(pd.DataFrame(pf['per_code']))
            st.markdown(f"**组合最终资产**: {pf['final_value']:.2f}  |  **组合总收益**: {pf['total_return']:+.2f}%")
        else:
            st.error("组合回测失败，请检查股票代码是否正确或数据源是否可用")
elif ("组合回测" in actions) and strat_choice.startswith("MR") and run_backtest:
    st.warning("当前演示的组合回测仅支持均线策略(MA)。如需 MR 组合回测，可后续扩展。")

# 如果没有点击开始回测按钮，显示提示信息
if not run_backtest and (actions and len(actions) > 0):
    st.info("💡 请配置参数后点击侧边栏的 **🚀 开始回测** 按钮来执行回测")

st.caption("Powered by Streamlit · 均线策略演示")


