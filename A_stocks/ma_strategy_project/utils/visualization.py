#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
可视化工具
"""

from __future__ import annotations

import pandas as pd
import sys


def _is_streamlit_env() -> bool:
    """检测是否在 Streamlit 环境中"""
    return 'streamlit' in sys.modules or any('streamlit' in str(arg) for arg in sys.argv)


def _get_tooltip_text(row_idx: int, data: pd.DataFrame, signal_type: str = "", 
                      html_format: bool = False) -> str:
    """
    生成悬浮提示文本
    
    Args:
        row_idx: 数据行索引
        data: 数据DataFrame
        signal_type: 信号类型（"买入"/"卖出"/""）
        html_format: 是否使用HTML格式（用于mpld3）
    
    Returns:
        格式化的提示文本
    """
    if row_idx < 0 or row_idx >= len(data):
        return ""
    
    row = data.iloc[row_idx]
    parts = []
    
    # 日期
    if 'date' in data.columns:
        date_val = row['date']
        if isinstance(date_val, pd.Timestamp):
            date_str = date_val.strftime('%Y-%m-%d')
        else:
            date_str = str(date_val)
        parts.append(f"日期: {date_str}")
    
    # 收盘价
    if 'close' in data.columns:
        parts.append(f"收盘价: {row['close']:.2f}")
    
    # 信号类型（优先使用传入的signal_type，如果为空则从positions推断）
    if signal_type:
        parts.append(f"信号: {signal_type}")
    else:
        # 如果没有传入signal_type，从positions推断
        if 'positions' in data.columns:
            pos_val = row['positions']
            if pd.notna(pos_val):
                if pos_val > 0:
                    parts.append("信号: 买入")
                elif pos_val < 0:
                    parts.append("信号: 卖出")
    
    # MA策略相关信息（如果有）
    if 'ma_short' in data.columns and 'ma_long' in data.columns:
        ma_short = row.get('ma_short')
        ma_long = row.get('ma_long')
        if pd.notna(ma_short) and pd.notna(ma_long) and ma_long > 0:
            ma_diff_pct = ((ma_short - ma_long) / ma_long * 100)
            parts.append(f"短期均线: {ma_short:.2f}")
            parts.append(f"长期均线: {ma_long:.2f}")
            parts.append(f"均线差值: {ma_diff_pct:.2f}%")
    
    # 成交量信息（如果有，优先在MA策略中显示）
    if 'volume' in data.columns:
        volume_val = row.get('volume')
        if pd.notna(volume_val) and volume_val > 0:
            # 格式化成交量：如果大于1万，显示为"X万"，否则显示具体数值
            if volume_val >= 10000:
                volume_str = f"{volume_val / 10000:.2f}万"
            else:
                volume_str = f"{int(volume_val)}"
            parts.append(f"成交量: {volume_str}")
            
            # 计算成交量相对移动平均的比值（用于判断成交量是否放大）
            try:
                # 计算最近5日的成交量移动平均
                volume_ma = data['volume'].rolling(window=5, min_periods=1).mean()
                if row_idx < len(volume_ma) and pd.notna(volume_ma.iloc[row_idx]) and volume_ma.iloc[row_idx] > 0:
                    volume_ratio = volume_val / volume_ma.iloc[row_idx]
                    parts.append(f"成交量比: {volume_ratio:.2f}x")
            except Exception:
                pass  # 如果计算失败，跳过成交量比
    
    # Z分数（如果有）
    if 'z' in data.columns:
        z_val = row['z']
        if pd.notna(z_val):
            parts.append(f"Z分数: {z_val:.3f}")
    
    if html_format:
        return "<br>".join(parts)
    else:
        return "\n".join(parts)


# ========== mpld3 自定义垂直联动线插件 ==========
try:
    import mpld3  # type: ignore
    from mpld3 import plugins, utils  # type: ignore

    def _fix_mpld3_cdn_links(html: str) -> str:
        """
        修复mpld3生成的HTML中的CDN链接，添加备用CDN支持
        
        Args:
            html: mpld3生成的原始HTML
            
        Returns:
            修复后的HTML字符串
        """
        # 替换d3 CDN链接为更可靠的CDN（jsdelivr）
        html = html.replace(
            'https://d3js.org/d3.v5.js',
            'https://cdn.jsdelivr.net/npm/d3@5/dist/d3.min.js'
        )
        html = html.replace(
            'https://d3js.org/d3.v5',
            'https://cdn.jsdelivr.net/npm/d3@5/dist/d3.min'
        )
        # 替换mpld3 CDN链接
        html = html.replace(
            'https://mpld3.github.io/js/mpld3.v0.5.11.js',
            'https://cdn.jsdelivr.net/gh/mpld3/mpld3@v0.5.11/js/mpld3.v0.5.11.js'
        )
        
        # 增强mpld3_load_lib函数，添加备用CDN支持
        cdn_fix_script = (
            "<script>\n"
            "(function(){\n"
            "  // 抑制非关键警告（可选，用于减少控制台噪音）\n"
            "  var originalWarn = console.warn;\n"
            "  var suppressedWarnings = ['mpld3', 'd3', 'deprecated', 'deprecation'];\n"
            "  console.warn = function(){\n"
            "    var message = Array.prototype.join.call(arguments, ' ');\n"
            "    var shouldSuppress = suppressedWarnings.some(function(keyword){\n"
            "      return message.toLowerCase().indexOf(keyword.toLowerCase()) >= 0;\n"
            "    });\n"
            "    if(!shouldSuppress) originalWarn.apply(console, arguments);\n"
            "  };\n"
            "  \n"
            "  // 保存原始的mpld3_load_lib函数\n"
            "  var original_mpld3_load_lib = window.mpld3_load_lib || function(url, callback){\n"
            "    var s = document.createElement('script');\n"
            "    s.src = url;\n"
            "    s.async = true;\n"
            "    s.onreadystatechange = s.onload = callback;\n"
            "    s.onerror = function(){/* 静默处理加载错误，使用备用CDN */};\n"
            "    document.getElementsByTagName('head')[0].appendChild(s);\n"
            "  };\n"
            "  \n"
            "  // CDN备用列表\n"
            "  var cdn_fallbacks = {\n"
            "    'd3.v5.js': [\n"
            "      'https://cdn.jsdelivr.net/npm/d3@5/dist/d3.min.js',\n"
            "      'https://unpkg.com/d3@5/dist/d3.min.js',\n"
            "      'https://d3js.org/d3.v5.js'\n"
            "    ],\n"
            "    'mpld3.v0.5.11.js': [\n"
            "      'https://cdn.jsdelivr.net/gh/mpld3/mpld3@v0.5.11/js/mpld3.v0.5.11.js',\n"
            "      'https://unpkg.com/mpld3@0.5.11/dist/mpld3.min.js',\n"
            "      'https://mpld3.github.io/js/mpld3.v0.5.11.js'\n"
            "    ]\n"
            "  };\n"
            "  \n"
            "  // 增强的加载函数，支持备用CDN\n"
            "  function enhanced_mpld3_load_lib(url, callback, fallbackIndex) {\n"
            "    fallbackIndex = fallbackIndex || 0;\n"
            "    \n"
            "    // 确定备用CDN列表\n"
            "    var fallbacks = [url];\n"
            "    for(var key in cdn_fallbacks) {\n"
            "      if(url.indexOf(key) >= 0) {\n"
            "        fallbacks = cdn_fallbacks[key];\n"
            "        // 如果原始URL不在列表中，添加到开头\n"
            "        if(fallbacks.indexOf(url) < 0) {\n"
            "          fallbacks = [url].concat(fallbacks);\n"
            "        }\n"
            "        break;\n"
            "      }\n"
            "    }\n"
            "    \n"
            "    if(fallbackIndex >= fallbacks.length) {\n"
            "      // 所有CDN都失败时，静默处理（避免过多错误信息）\n"
            "      if(callback) callback();\n"
            "      return;\n"
            "    }\n"
            "    \n"
            "    var currentUrl = fallbacks[fallbackIndex];\n"
            "    var s = document.createElement('script');\n"
            "    s.src = currentUrl;\n"
            "    s.async = true;\n"
            "    \n"
            "    s.onload = s.onreadystatechange = function() {\n"
            "      if(!s.readyState || s.readyState === 'loaded' || s.readyState === 'complete') {\n"
            "        s.onload = s.onreadystatechange = null;\n"
            "        if(callback) callback();\n"
            "      }\n"
            "    };\n"
            "    \n"
            "    s.onerror = function() {\n"
            "      // 静默处理CDN加载失败，自动尝试备用CDN\n"
            "      // 移除失败的script标签\n"
            "      if(s.parentNode) s.parentNode.removeChild(s);\n"
            "      // 尝试下一个备用CDN\n"
            "      enhanced_mpld3_load_lib(url, callback, fallbackIndex + 1);\n"
            "    };\n"
            "    \n"
            "    document.getElementsByTagName('head')[0].appendChild(s);\n"
            "  }\n"
            "  \n"
            "  // 替换全局的mpld3_load_lib函数\n"
            "  window.mpld3_load_lib = enhanced_mpld3_load_lib;\n"
            "  \n"
            "  // 如果已经存在mpld3_load_lib，也替换它\n"
            "  if(typeof mpld3_load_lib !== 'undefined') {\n"
            "    mpld3_load_lib = enhanced_mpld3_load_lib;\n"
            "  }\n"
            "})();\n"
            "</script>\n"
        )
        
        # 在第一个script标签之前插入CDN修复脚本
        script_pos = html.find('<script>')
        if script_pos >= 0:
            html = html[:script_pos] + cdn_fix_script + html[script_pos:]
        
        return html

    class VLinePlugin(plugins.PluginBase):  # type: ignore
        """在一个或多个Axes上显示联动垂直参考线（仅限mpld3交互图）"""

        JAVASCRIPT = r"""
        mpld3.register_plugin("vline_plugin", VLinePlugin);
        VLinePlugin.prototype = Object.create(mpld3.Plugin.prototype);
        VLinePlugin.prototype.constructor = VLinePlugin;
        function VLinePlugin(fig, props){
            mpld3.Plugin.call(this, fig, props);
            this.axes_ids = props.axes_ids;
            this.color = props.color || 'blue';
            this.alpha = (props.alpha !== undefined) ? props.alpha : 0.5;
            this.linewidth = props.linewidth || 1;
        }
        VLinePlugin.prototype.draw = function(){
            var fig = this.fig;
            var axes = [];
            var vlines = [];
            for (var i=0; i<this.axes_ids.length; i++){
                var ax = mpld3.get_element(this.axes_ids[i], fig);
                if(!ax) continue;
                axes.push(ax);
                var line = ax.axes.append("line")
                    .attr("x1", 0).attr("y1", 0)
                    .attr("x2", 0).attr("y2", ax.height)
                    .style("stroke", this.color)
                    .style("stroke-width", this.linewidth)
                    .style("opacity", 0.0);
                vlines.push(line);
            }
            var that = this;
            function updateFromAxis(axIdx, mouseX){
                // 归一化位置（0..1）
                var ratio = mouseX / axes[axIdx].width;
                ratio = Math.max(0, Math.min(1, ratio));
                for (var j=0; j<axes.length; j++){
                    var xpix = ratio * axes[j].width;
                    vlines[j].attr("x1", xpix)
                            .attr("x2", xpix)
                            .attr("y1", 0)
                            .attr("y2", axes[j].height)
                            .style("opacity", that.alpha);
                }
            }
            function hide(){
                for (var j=0; j<vlines.length; j++){
                    vlines[j].style("opacity", 0.0);
                }
            }
            // 为每个axes注册mousemove
            for (let i=0; i<axes.length; i++){
                axes[i].axes.on("mousemove.vline", function(){
                    var m = d3.mouse(this);
                    updateFromAxis(i, m[0]);
                });
                axes[i].axes.on("mouseleave.vline", function(){ hide(); });
            }
        };
        """

        def __init__(self, axes, color: str = 'blue', linewidth: float = 1.0, alpha: float = 0.5):
            if not isinstance(axes, (list, tuple)):
                axes = [axes]
            self.axes = axes
            self.dict_ = {
                "type": "vline_plugin",
                "axes_ids": [utils.get_id(ax) for ax in axes],
                "color": color,
                "linewidth": linewidth,
                "alpha": alpha,
            }
except Exception:
    VLinePlugin = None  # pragma: no cover


def plot_equity_curve(data: pd.DataFrame, outfile: str = "backtest_equity.png") -> str:
    """绘制权益曲线并保存（若未安装 matplotlib 则直接跳过）"""
    if data is None or data.empty or 'total' not in data.columns:
        return ""
    try:
        import matplotlib  # type: ignore
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # type: ignore
        import warnings
        warnings.filterwarnings('ignore')
        
        # 配置中文字体支持
        plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans', 'Arial Unicode MS', 'sans-serif']
        plt.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题
        # 禁用matplotlib的交互式后端输出
        plt.ioff()  # 关闭交互模式
        
    except Exception:
        return ""
    
    fig, ax = plt.subplots(figsize=(10, 4))
    
    # 绘制权益曲线
    if 'date' in data.columns:
        ax.plot(pd.to_datetime(data['date']), data['total'], label='总资产', color='blue', linewidth=1.5)
    else:
        ax.plot(data['total'], label='总资产', color='blue', linewidth=1.5)
    
    # 设置中文标题和标签
    ax.set_title('权益曲线', fontsize=14, fontweight='bold')
    ax.set_xlabel('日期', fontsize=11)
    ax.set_ylabel('资产价值', fontsize=11)
    ax.grid(True, alpha=0.3)
    ax.legend(loc='best', fontsize=10)
    
    # 格式化Y轴：如果有大的数值，使用万为单位
    from matplotlib.ticker import FuncFormatter
    ax.yaxis.set_major_formatter(FuncFormatter(lambda x, p: f'{x/10000:.1f}万' if x >= 10000 else f'{int(x)}'))
    
    # 清理图表，确保没有多余的文本或调试信息
    plt.tight_layout()
    
    # 保存前清理任何可能的文本输出
    fig.canvas.draw()
    
    # 保存图片
    fig.savefig(outfile, dpi=150, bbox_inches='tight', pad_inches=0.1)
    plt.close(fig)
    
    # 清理matplotlib状态
    plt.clf()
    
    return outfile


def plot_price_ma_signals(data: pd.DataFrame, outfile: str = "price_ma.png",
                          short_col: str = 'ma_short', long_col: str = 'ma_long',
                          interactive: bool | None = None,
                          stock_code: str = None) -> str:
    """
    绘制MA策略图表，支持交互式悬浮提示和十字线联动
    
    Args:
        data: 数据DataFrame
        outfile: 输出文件名（非交互模式）或临时文件路径
        short_col: 短期均线列名
        long_col: 长期均线列名
        interactive: 是否使用交互模式（None时自动检测）
        stock_code: 股票代码（可选，用于获取和显示财务指标）
    
    Returns:
        文件路径（PNG）或HTML字符串（交互模式）
    """
    # 调试日志：函数被调用
    try:
        from utils.logger import logger
        logger.info(f"[plot_price_ma_signals] 函数被调用: data.shape={data.shape if data is not None else 'None'}, interactive={interactive}, stock_code={stock_code}")
    except Exception:
        pass
    
    if data is None or data.empty:
        try:
            from utils.logger import logger
            logger.warning("[plot_price_ma_signals] 数据为空或None，返回空字符串")
        except Exception:
            pass
        return ""
    
    # 自动检测交互模式
    if interactive is None:
        interactive = _is_streamlit_env()
    
    try:
        from utils.logger import logger
        logger.info(f"[plot_price_ma_signals] 交互模式: {interactive}")
    except Exception:
        pass
    
    try:
        import matplotlib  # type: ignore
        if not interactive:
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # type: ignore
        import numpy as np  # type: ignore
        try:
            from utils.logger import logger
            logger.info("[plot_price_ma_signals] matplotlib导入成功")
        except Exception:
            pass
    except Exception as e:
        try:
            from utils.logger import logger
            logger.error(f"[plot_price_ma_signals] matplotlib导入失败: {str(e)}")
        except Exception:
            pass
        return ""

    # 调整图表宽度以适应左侧财务指标
    fig_width = 12 if stock_code else 10
    fig, ax = plt.subplots(figsize=(fig_width, 6))
    
    # 调整左侧边距，为财务指标留出空间（与权益曲线图对齐）
    # 权益曲线图使用left=0.06，这里也使用相同值确保对齐
    left_margin = 0.06 if stock_code else 0.06
    try:
        # 调整top和bottom，使图表上下居中对齐
        fig.subplots_adjust(left=left_margin, right=0.98, top=0.92, bottom=0.10)
    except Exception:
        pass
    x = pd.to_datetime(data['date']) if 'date' in data.columns else range(len(data))
    
    # 配置中文字体支持
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans', 'Arial Unicode MS', 'sans-serif']
    plt.rcParams['axes.unicode_minus'] = False
    
    ax.plot(x, data['close'], label='收盘价', color='black', linewidth=1.5)
    if short_col in data.columns:
        ma_short_label = short_col.replace('_', ' ').title() if '_' in short_col else f'MA短期'
        ax.plot(x, data[short_col], label=ma_short_label, color='tab:blue', linewidth=1)
    if long_col in data.columns:
        ma_long_label = long_col.replace('_', ' ').title() if '_' in long_col else f'MA长期'
        ax.plot(x, data[long_col], label=ma_long_label, color='tab:orange', linewidth=1)

    # 买卖点（如果有）
    buy_scatter = None
    sell_scatter = None
    buy_indices = []
    sell_indices = []
    early_buy_scatter = None
    early_sell_scatter = None
    
    if 'positions' in data.columns:
        # 确保 positions 只包含 1（买入）、-1（卖出）或 0（无操作）
        # 避免同时出现买入和卖出标记
        buy_idx = data['positions'] == 1  # 严格等于1，而不是>0
        sell_idx = data['positions'] == -1  # 严格等于-1，而不是<0
        
        # 检查是否有冲突（理论上不应该有）
        conflict_idx = buy_idx & sell_idx
        if conflict_idx.any():
            # 如果发现冲突，优先显示卖出（平仓优先）
            buy_idx = buy_idx & ~conflict_idx
            sell_idx = sell_idx  # 保留所有卖出，包括冲突的
        
        # 区分提前信号和标准信号
        if 'early_signal' in data.columns:
            # 提前信号：signal和early_signal同时为1（买入）或-1（卖出）
            early_buy_mask = buy_idx & (data['early_signal'] == 1)
            early_sell_mask = sell_idx & (data['early_signal'] == -1)
            standard_buy_mask = buy_idx & ~early_buy_mask
            standard_sell_mask = sell_idx & ~early_sell_mask
        else:
            early_buy_mask = pd.Series([False] * len(data), index=data.index)
            early_sell_mask = pd.Series([False] * len(data), index=data.index)
            standard_buy_mask = buy_idx
            standard_sell_mask = sell_idx
        
        # 标准买入信号
        if standard_buy_mask.any():
            buy_x = x[standard_buy_mask]
            buy_y = data['close'][standard_buy_mask]
            buy_indices = data.index[standard_buy_mask].tolist()
            buy_scatter = ax.scatter(buy_x, buy_y, marker='^', color='green', s=100, 
                                    label='买入', zorder=5, picker=True)
        
        # 提前买入信号（用不同颜色和标记）
        if early_buy_mask.any():
            early_buy_x = x[early_buy_mask]
            early_buy_y = data['close'][early_buy_mask]
            early_buy_indices = data.index[early_buy_mask].tolist()
            buy_indices.extend(early_buy_indices)
            early_buy_scatter = ax.scatter(early_buy_x, early_buy_y, marker='^', 
                                          color='lime', s=120, alpha=0.7, edgecolors='green', 
                                          linewidths=2, label='提前买入', zorder=6, picker=True)
        
        # 标准卖出信号
        if standard_sell_mask.any():
            sell_x = x[standard_sell_mask]
            sell_y = data['close'][standard_sell_mask]
            sell_indices = data.index[standard_sell_mask].tolist()
            sell_scatter = ax.scatter(sell_x, sell_y, marker='v', color='red', s=100, 
                                     label='卖出', zorder=5, picker=True)
        
        # 提前卖出信号（用不同颜色和标记）
        if early_sell_mask.any():
            early_sell_x = x[early_sell_mask]
            early_sell_y = data['close'][early_sell_mask]
            early_sell_indices = data.index[early_sell_mask].tolist()
            sell_indices.extend(early_sell_indices)
            early_sell_scatter = ax.scatter(early_sell_x, early_sell_y, marker='v', 
                                           color='orange', s=120, alpha=0.7, edgecolors='red', 
                                           linewidths=2, label='提前卖出', zorder=6, picker=True)
        
        # 兼容旧版本：如果没有early_signal列，使用原来的逻辑
        if 'early_signal' not in data.columns:
            if buy_idx.any():
                buy_x = x[buy_idx]
                buy_y = data['close'][buy_idx]
                buy_indices = data.index[buy_idx].tolist()
                buy_scatter = ax.scatter(buy_x, buy_y, marker='^', color='green', s=100, 
                                        label='买入', zorder=5, picker=True)
            
            if sell_idx.any():
                sell_x = x[sell_idx]
                sell_y = data['close'][sell_idx]
                sell_indices = data.index[sell_idx].tolist()
                sell_scatter = ax.scatter(sell_x, sell_y, marker='v', color='red', s=100, 
                                         label='卖出', zorder=5, picker=True)

    ax.set_title('MA策略 - 价格与买卖信号', fontsize=14, fontweight='bold')
    ax.set_xlabel('日期', fontsize=11)
    ax.set_ylabel('价格', fontsize=11)
    ax.grid(True, alpha=0.3)
    ax.legend(loc='best', fontsize=10)
    
    # 添加财务指标显示（如果提供了股票代码）
    if stock_code:
        try:
            from utils.financial_metrics import get_financial_display_data
            
            # 获取当前价格（使用最新收盘价）
            current_price = data['close'].iloc[-1] if 'close' in data.columns and len(data) > 0 else None
            
            # 获取财务数据（性能优化：快速获取，失败不影响主图表）
            try:
                financial_info = get_financial_display_data(stock_code, current_price=current_price)
            except Exception:
                # 财务数据获取失败不影响主图表显示
                financial_info = None
            
            if financial_info and financial_info.get('data_available'):
                # 在图表左侧竖直排列财务指标
                y_min, y_max = ax.get_ylim()
                y_range = y_max - y_min
                
                # 计算文本位置（从顶部开始，竖直排列）
                y_positions = []
                start_y = y_max - y_range * 0.05  # 从顶部稍微下移
                line_spacing = y_range * 0.08  # 行间距
                
                # 构建要显示的文本列表
                text_lines = []
                
                # 盈利能力指标
                text_lines.append(("盈利能力", 'bold', 'blue'))
                if financial_info.get('net_profit_yi') is not None:
                    text_lines.append((f"净利润: {financial_info['net_profit_yi']:.2f}亿", 'normal', 'black'))
                if financial_info.get('roe') is not None:
                    text_lines.append((f"ROE: {financial_info['roe']:.2f}%", 'normal', 'black'))
                if financial_info.get('profit_margin') is not None:
                    text_lines.append((f"净利润率: {financial_info['profit_margin']:.2f}%", 'normal', 'black'))
                
                # 估值指标
                text_lines.append(("估值分析", 'bold', 'green'))
                if financial_info.get('pe_ratio') is not None:
                    text_lines.append((f"市盈率(PE): {financial_info['pe_ratio']:.2f}", 'normal', 'black'))
                if financial_info.get('pb_ratio') is not None:
                    text_lines.append((f"市净率(PB): {financial_info['pb_ratio']:.2f}", 'normal', 'black'))
                if financial_info.get('comprehensive_score') is not None:
                    text_lines.append((f"综合得分: {financial_info['comprehensive_score']:.2f}", 'bold', 'red'))
                
                # 绘制文本（竖直排列，在Y轴左侧）
                # 使用ax.transAxes确保文本位置相对于坐标轴固定
                x_pos_axes = 0.02  # 距离左边缘2%的位置（为边框预留空间）
                y_start_axes = 0.90  # 从顶部90%的位置开始（为边框预留空间）
                line_height_axes = 0.045  # 每行高度（增加行距，使文字更舒适）
                
                # 先绘制所有文本（增加行距，去除内边框）
                text_objects = []
                current_y_axes = y_start_axes
                for idx, (text, weight, color) in enumerate(text_lines):
                    # 跳过空行（但保留间距）
                    if text == "":
                        current_y_axes -= line_height_axes * 0.6  # 空行间距稍大
                        continue
                    
                    # 字体大小：14px
                    # 使用与MR图表图例相同的样式：透明背景，浅灰色边框
                    # MR图例默认样式：framealpha约0.8，edgecolor='0.8'（浅灰），背景白色但透明
                    if weight == 'bold' and text in ["盈利能力", "估值分析"]:
                        # 标题：透明背景，浅灰色边框（类似MR图例）
                        text_obj = ax.text(x_pos_axes, current_y_axes, text, 
                               transform=ax.transAxes,  # 使用坐标轴坐标系，固定位置
                               fontsize=14,
                               weight=weight,
                               color=color,
                               verticalalignment='top',
                               horizontalalignment='left',
                               bbox=dict(boxstyle='round,pad=0.3', 
                                        facecolor='white',  # 白色背景
                                        alpha=0.0,  # 完全透明背景
                                        edgecolor='0.8',  # 浅灰色边框（与MR图例一致）
                                        linewidth=1.0),  # 边框线宽
                               zorder=100,  # 确保在最上层
                               clip_on=False)  # 不裁剪
                    else:
                        # 数据值：透明背景，浅灰色边框（类似MR图例）
                        text_obj = ax.text(x_pos_axes, current_y_axes, text, 
                               transform=ax.transAxes,
                               fontsize=14,
                               weight=weight,
                               color=color,
                               verticalalignment='top',
                               horizontalalignment='left',
                               bbox=dict(boxstyle='round,pad=0.2', 
                                        facecolor='white',  # 白色背景
                                        alpha=0.0,  # 完全透明背景
                                        edgecolor='0.8',  # 浅灰色边框（与MR图例一致）
                                        linewidth=1.0),  # 边框线宽
                               zorder=100,  # 确保在最上层
                               clip_on=False)  # 不裁剪
                    
                    text_objects.append((current_y_axes, text_obj))
                    current_y_axes -= line_height_axes
                
                # 重新添加边框：基于文字实际宽度计算
                # 首先需要渲染画布以获取文本的实际尺寸
                fig.canvas.draw()
                
                # 计算文本的实际宽度和高度边界
                max_text_width_pixels = 0
                min_y_pixels = float('inf')
                max_y_pixels = float('-inf')
                
                axes_bbox = ax.get_window_extent()
                axes_width_pixels = axes_bbox.width
                axes_height_pixels = axes_bbox.height
                
                for _, text_obj in text_objects:
                    # 获取文本的窗口扩展（像素坐标）
                    text_bbox = text_obj.get_window_extent(renderer=fig.canvas.get_renderer())
                    text_width_pixels = text_bbox.width
                    text_y_top_pixels = text_bbox.y1  # 顶部Y坐标（像素）
                    text_y_bottom_pixels = text_bbox.y0  # 底部Y坐标（像素）
                    
                    max_text_width_pixels = max(max_text_width_pixels, text_width_pixels)
                    max_y_pixels = max(max_y_pixels, text_y_top_pixels)
                    min_y_pixels = min(min_y_pixels, text_y_bottom_pixels)
                
                # 将像素尺寸转换为transAxes坐标系
                # X坐标转换：文本宽度（像素）/ axes宽度（像素）
                max_text_width_axes = max_text_width_pixels / axes_width_pixels
                
                # Y坐标转换：axes的Y坐标从底部开始（y0），顶部是y1
                # text_bbox返回的是figure坐标系，需要转换为axes相对坐标
                # axes的底部在figure中的y坐标是axes_bbox.y0，顶部是axes_bbox.y1
                # 文本的底部y坐标（min_y_pixels）和顶部y坐标（max_y_pixels）都是figure坐标系
                # 转换为transAxes：从axes底部（y0）到文本底部的距离 / axes高度
                text_bottom_axes = (min_y_pixels - axes_bbox.y0) / axes_height_pixels
                text_top_axes = (max_y_pixels - axes_bbox.y0) / axes_height_pixels
                
                # 设置适当的边距
                padding_uniform = 0.007  # 约2个字符宽度，上下左统一
                # 右边距在现有基础上缩小8+6=14个字符宽度（14 * 0.0035 ≈ 0.049）
                padding_right = padding_uniform - 0.049  # 右边距总共缩小14个字符宽度
                
                # 计算边框位置和尺寸
                box_x = x_pos_axes - padding_uniform  # 左边缘：文本左边缘 - 左边距
                box_right = x_pos_axes + max_text_width_axes + padding_right  # 右边缘：文本右边缘 + 缩小后的右边距
                box_width = box_right - box_x  # 边框宽度
                box_y_top = text_top_axes + padding_uniform  # 上边缘：文本顶部 + 上边距
                box_y_bottom = text_bottom_axes - padding_uniform  # 下边缘：文本底部 - 下边距
                box_height = box_y_top - box_y_bottom  # 边框高度
                
                # 确保边框尺寸有效
                if box_width > 0 and box_height > 0:
                    # 绘制边框（灰色边框线，透明背景）
                    from matplotlib.patches import FancyBboxPatch
                    outer_rect = FancyBboxPatch(
                        (box_x, box_y_bottom),
                        box_width, box_height,
                        transform=ax.transAxes,
                        boxstyle='round,pad=0.005',
                        facecolor='white',
                        edgecolor='0.6',  # 灰色边框线
                        linewidth=1.5,  # 边框线宽
                        fill=False,  # 不填充（透明背景）
                        zorder=102,  # 确保在最上层显示
                        clip_on=False
                    )
                    ax.add_patch(outer_rect)
        
        except ImportError:
            # 如果财务指标模块不可用，跳过
            pass
        except Exception:
            # 静默处理错误，不影响主图表显示
            pass
    
    # 添加十字线和交互功能
    if interactive:
        try:
            import mpld3  # type: ignore
            from mpld3 import plugins  # type: ignore
            
            # 为买卖点添加工具提示
            tooltips = []
            
            # 买入点工具提示
            if buy_scatter is not None and len(buy_indices) > 0:
                tooltips_buy = []
                for idx in buy_indices:
                    signal_type = "买入"
                    if 'early_signal' in data.columns and idx < len(data) and data.iloc[idx].get('early_signal', 0) == 1:
                        signal_type = "提前买入"
                    tooltip_text = _get_tooltip_text(idx, data, signal_type, html_format=True)
                    tooltips_buy.append(tooltip_text)
                tooltip_buy = plugins.PointHTMLTooltip(buy_scatter, tooltips_buy, voffset=10, hoffset=10)
                plugins.connect(fig, tooltip_buy)
            
            # 提前买入点工具提示
            if early_buy_scatter is not None:
                early_buy_indices_filtered = [idx for idx in buy_indices if idx < len(data) and data.iloc[idx].get('early_signal', 0) == 1]
                if len(early_buy_indices_filtered) > 0:
                    tooltips_early_buy = []
                    for idx in early_buy_indices_filtered:
                        tooltip_text = _get_tooltip_text(idx, data, "提前买入", html_format=True)
                        tooltips_early_buy.append(tooltip_text)
                    tooltip_early_buy = plugins.PointHTMLTooltip(early_buy_scatter, tooltips_early_buy, voffset=10, hoffset=10)
                    plugins.connect(fig, tooltip_early_buy)
            
            # 卖出点工具提示
            if sell_scatter is not None and len(sell_indices) > 0:
                tooltips_sell = []
                for idx in sell_indices:
                    signal_type = "卖出"
                    if 'early_signal' in data.columns and idx < len(data) and data.iloc[idx].get('early_signal', 0) == -1:
                        signal_type = "提前卖出"
                    tooltip_text = _get_tooltip_text(idx, data, signal_type, html_format=True)
                    tooltips_sell.append(tooltip_text)
                tooltip_sell = plugins.PointHTMLTooltip(sell_scatter, tooltips_sell, voffset=10, hoffset=10)
                plugins.connect(fig, tooltip_sell)
            
            # 提前卖出点工具提示
            if early_sell_scatter is not None:
                early_sell_indices_filtered = [idx for idx in sell_indices if idx < len(data) and data.iloc[idx].get('early_signal', 0) == -1]
                if len(early_sell_indices_filtered) > 0:
                    tooltips_early_sell = []
                    for idx in early_sell_indices_filtered:
                        tooltip_text = _get_tooltip_text(idx, data, "提前卖出", html_format=True)
                        tooltips_early_sell.append(tooltip_text)
                    tooltip_early_sell = plugins.PointHTMLTooltip(early_sell_scatter, tooltips_early_sell, voffset=10, hoffset=10)
                    plugins.connect(fig, tooltip_early_sell)
            
            # 添加垂直联动线（若插件可用）
            try:
                if VLinePlugin is not None:
                    plugins.connect(fig, VLinePlugin(ax, color='blue', linewidth=1, alpha=0.4))
            except Exception:
                # 回退为鼠标坐标显示
                mousepos = plugins.MousePosition(fontsize=10)
                plugins.connect(fig, mousepos)
            
            # 生成HTML，图表左对齐，工具栏位于左侧与Y轴中间对齐
            raw_html = mpld3.fig_to_html(fig)
            wrapper_css = (
                "<style>\n"
                ".mpld3-wrapper{position:relative;text-align:left;}\n"
                ".mpld3-figure{display:block;margin:0;}\n"
                ".mpld3-figure > svg{display:block;margin:0;}\n"
                "/* 工具栏容器样式 - 确保始终可点击 */\n"
                ".mpld3-toolbar{\n"
                "  position:absolute!important;\n"
                "  top:50%!important;\n"
                "  left:0!important;\n"
                "  right:auto!important;\n"
                "  transform:translateY(-50%)!important;\n"
                "  margin:0!important;\n"
                "  padding:8px!important;\n"
                "  z-index:10000!important;\n"
                "  pointer-events:auto!important;\n"
                "  background:rgba(255,255,255,0.9)!important;\n"
                "  border-radius:4px!important;\n"
                "  box-shadow:0 2px 4px rgba(0,0,0,0.1)!important;\n"
                "}\n"
                "/* 工具栏所有交互元素样式 */\n"
                ".mpld3-toolbar button,\n"
                ".mpld3-toolbar a,\n"
                ".mpld3-toolbar .mpld3-toolbar-button,\n"
                ".mpld3-toolbar [class*='toolbar'],\n"
                ".mpld3-toolbar [role='button']{\n"
                "  pointer-events:auto!important;\n"
                "  cursor:pointer!important;\n"
                "  position:relative!important;\n"
                "  z-index:10001!important;\n"
                "  display:inline-block!important;\n"
                "  margin:2px!important;\n"
                "  padding:4px!important;\n"
                "  min-width:24px!important;\n"
                "  min-height:24px!important;\n"
                "}\n"
                "/* 确保工具栏不被SVG遮挡 */\n"
                ".mpld3-figure > svg{\n"
                "  pointer-events:auto!important;\n"
                "}\n"
                "</style>"
            )
            move_js = (
                "<script>\n"
                "(function(){\n"
                "  var initAttempts = 0;\n"
                "  var maxAttempts = 10;\n"
                "  var toolbarMonitorInterval = null;\n"
                "  \n"
                "  // 修复工具栏按钮状态\n"
                "  function fixToolbarButtons(toolbar){\n"
                "    if(!toolbar) return false;\n"
                "    \n"
                "    // 查找所有可能的按钮元素\n"
                "    var selectors = ['button', 'a', '.mpld3-toolbar-button', '[class*=\"toolbar\"]', '[role=\"button\"]'];\n"
                "    var allButtons = [];\n"
                "    selectors.forEach(function(sel){\n"
                "      try{\n"
                "        var elements = toolbar.querySelectorAll(sel);\n"
                "        for(var i=0; i<elements.length; i++){\n"
                "          if(allButtons.indexOf(elements[i]) === -1){\n"
                "            allButtons.push(elements[i]);\n"
                "          }\n"
                "        }\n"
                "      }catch(e){}\n"
                "    });\n"
                "    \n"
                "    // 修复每个按钮\n"
                "    var fixed = false;\n"
                "    for(var i=0; i<allButtons.length; i++){\n"
                "      var btn = allButtons[i];\n"
                "      if(btn.style.pointerEvents !== 'auto' || btn.style.cursor !== 'pointer'){\n"
                "        btn.style.pointerEvents = 'auto';\n"
                "        btn.style.cursor = 'pointer';\n"
                "        btn.style.position = 'relative';\n"
                "        btn.style.zIndex = '10001';\n"
                "        fixed = true;\n"
                "      }\n"
                "      // 确保按钮可点击\n"
                "      if(btn.hasAttribute('disabled')){\n"
                "        btn.removeAttribute('disabled');\n"
                "        fixed = true;\n"
                "      }\n"
                "    }\n"
                "    \n"
                "    // 修复工具栏容器\n"
                "    if(toolbar.style.pointerEvents !== 'auto' || parseInt(toolbar.style.zIndex) < 10000){\n"
                "      toolbar.style.pointerEvents = 'auto';\n"
                "      toolbar.style.zIndex = '10000';\n"
                "      fixed = true;\n"
                "    }\n"
                "    \n"
                "    return fixed;\n"
                "  }\n"
                "  \n"
                "  function initToolbar(){\n"
                "    initAttempts++;\n"
                "    try{\n"
                "      var wrapper = document.currentScript ? document.currentScript.parentElement : null;\n"
                "      if(!wrapper) wrapper = document.querySelector('.mpld3-wrapper:last-child');\n"
                "      if(!wrapper){\n"
                "        if(initAttempts < maxAttempts){\n"
                "          setTimeout(initToolbar, 200);\n"
                "        }\n"
                "        return;\n"
                "      }\n"
                "      \n"
                "      var toolbar = wrapper.querySelector('.mpld3-toolbar');\n"
                "      if(!toolbar){\n"
                "        if(initAttempts < maxAttempts){\n"
                "          setTimeout(initToolbar, 200);\n"
                "        }\n"
                "        return;\n"
                "      }\n"
                "      \n"
                "      // 确保工具栏在正确的父元素中\n"
                "      if(toolbar.parentElement !== wrapper){\n"
                "        wrapper.appendChild(toolbar);\n"
                "      }\n"
                "      \n"
                "      // 修复工具栏按钮状态\n"
                "      fixToolbarButtons(toolbar);\n"
                "      \n"
                "      // 默认激活移动工具（平移工具）\n"
                "      function activatePanTool(){\n"
                "        var toolbarButtons = toolbar.querySelectorAll('.mpld3-toolbar-button, button, a, [class*=\"toolbar\"], [role=\"button\"]');\n"
                "        var panButton = null;\n"
                "        \n"
                "        // 方法1: 通过title属性查找\n"
                "        for(var i=0; i<toolbarButtons.length; i++){\n"
                "          var title = (toolbarButtons[i].getAttribute('title') || '').toLowerCase();\n"
                "          if(title.indexOf('pan') >= 0 || title.indexOf('move') >= 0 || title.indexOf('平移') >= 0){\n"
                "            panButton = toolbarButtons[i];\n"
                "            break;\n"
                "          }\n"
                "        }\n"
                "        \n"
                "        // 方法2: 如果没找到，尝试第二个按钮（通常是平移工具）\n"
                "        if(!panButton && toolbarButtons.length >= 2){\n"
                "          panButton = toolbarButtons[1];\n"
                "        }\n"
                "        \n"
                "        // 激活平移工具\n"
                "        if(panButton){\n"
                "          setTimeout(function(){\n"
                "            try{\n"
                "              if(panButton.click){\n"
                "                panButton.click();\n"
                "              } else if(panButton.dispatchEvent){\n"
                "                var clickEvent = new MouseEvent('click', {bubbles: true, cancelable: true});\n"
                "                panButton.dispatchEvent(clickEvent);\n"
                "              }\n"
                "            }catch(e){console.log('Pan tool activation:', e);}\n"
                "          }, 200);\n"
                "        }\n"
                "      }\n"
                "      \n"
                "      // 只在第一次成功初始化时激活平移工具\n"
                "      if(initAttempts === 1){\n"
                "        activatePanTool();\n"
                "      }\n"
                "      \n"
                "      // 启动工具栏状态监控\n"
                "      if(!toolbarMonitorInterval){\n"
                "        toolbarMonitorInterval = setInterval(function(){\n"
                "          var currentToolbar = wrapper.querySelector('.mpld3-toolbar');\n"
                "          if(currentToolbar){\n"
                "            fixToolbarButtons(currentToolbar);\n"
                "          }\n"
                "        }, 1000);\n"
                "      }\n"
                "      \n"
                "    }catch(e){console.error('Toolbar init error:', e);}\n"
                "  }\n"
                "  \n"
                "  // 多种方式确保执行时机正确\n"
                "  function startInit(){\n"
                "    if(document.readyState === 'complete' || document.readyState === 'interactive'){\n"
                "      setTimeout(initToolbar, 100);\n"
                "    }else{\n"
                "      document.addEventListener('DOMContentLoaded', function(){setTimeout(initToolbar, 100);});\n"
                "      window.addEventListener('load', function(){setTimeout(initToolbar, 200);});\n"
                "    }\n"
                "    // 立即尝试一次\n"
                "    setTimeout(initToolbar, 50);\n"
                "  }\n"
                "  \n"
                "  startInit();\n"
                "})();\n"
                "</script>"
            )
            html_str = f"<div class=\"mpld3-wrapper\">{raw_html}{wrapper_css}{move_js}</div>"
            plt.close(fig)
            try:
                from utils.logger import logger
                logger.info(f"[plot_price_ma_signals] HTML生成成功，长度: {len(html_str)}")
            except Exception:
                pass
            return html_str
            
        except ImportError:
            # 如果mpld3不可用，回退到静态图
            interactive = False
    
    if not interactive:
        # 非交互模式：使用mplcursors添加悬浮提示（如果可用且后端支持交互）
        try:
            import matplotlib  # type: ignore
            backend = matplotlib.get_backend()
            # 只在交互式后端中启用mplcursors
            if backend.lower() not in ['agg', 'svg', 'pdf', 'ps']:
                import mplcursors  # type: ignore
                
                # 为买入点添加光标
                if buy_scatter is not None:
                    cursor_buy = mplcursors.cursor(buy_scatter, hover=True)
                    @cursor_buy.connect("add")
                    def on_add_buy(sel):
                        idx = buy_indices[sel.target.index]
                        sel.annotation.set_text(_get_tooltip_text(idx, data, "买入"))
                
                # 为卖出点添加光标
                if sell_scatter is not None:
                    cursor_sell = mplcursors.cursor(sell_scatter, hover=True)
                    @cursor_sell.connect("add")
                    def on_add_sell(sel):
                        idx = sell_indices[sel.target.index]
                        sel.annotation.set_text(_get_tooltip_text(idx, data, "卖出"))
                
                # 添加垂直线联动（鼠标在图表上移动时显示）
                vline = ax.axvline(x=x[0] if len(x) > 0 else 0, color='blue', linewidth=1, alpha=0.5, visible=False)
                
                def on_mouse_move(event):
                    if event.inaxes == ax:
                        vline.set_xdata([event.xdata, event.xdata])
                        vline.set_visible(True)
                        fig.canvas.draw_idle()
                    else:
                        vline.set_visible(False)
                        fig.canvas.draw_idle()
                
                fig.canvas.mpl_connect('motion_notify_event', on_mouse_move)
        except (ImportError, AttributeError):
            pass  # mplcursors不可用或后端不支持，跳过交互功能
    
    fig.tight_layout()
    
    if not interactive:
        fig.savefig(outfile, dpi=150, bbox_inches='tight')
        plt.close(fig)
        try:
            from utils.logger import logger
            logger.info(f"[plot_price_ma_signals] PNG文件生成成功: {outfile}")
        except Exception:
            pass
        return outfile
    else:
        plt.close(fig)
        try:
            from utils.logger import logger
            logger.warning("[plot_price_ma_signals] 非交互模式但未生成文件，返回空字符串")
        except Exception:
            pass
        return ""


def _plot_mr_with_plotly(data: pd.DataFrame, entry_z: float, exit_z: float, 
                         window_val: str, outfile: str) -> str:
    """
    使用Plotly绘制MR策略图表（阶段1：基础框架和主图）
    
    Args:
        data: 包含 mr_mean, mr_std, z, close, positions 等列的DataFrame
        entry_z: 进场Z阈值
        exit_z: 出场Z阈值
        window_val: 窗口参数值
        outfile: 输出文件名（非交互模式）
    
    Returns:
        HTML字符串（交互模式）或文件路径（非交互模式）
    """
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        import numpy as np
    except ImportError:
        return ""
    
    # 准备日期数据
    if 'date' in data.columns:
        dates = pd.to_datetime(data['date'])
    else:
        dates = pd.date_range(start='2020-01-01', periods=len(data), freq='D')
    
    # 数据验证：确保数据不为空且类型正确
    if len(data) == 0:
        try:
            from utils.logger import logger
            logger.warning("[_plot_mr_with_plotly] 数据为空")
        except Exception:
            pass
        return ""
    
    # 检查关键列是否存在有效数据
    if 'close' not in data.columns or data['close'].isna().all():
        try:
            from utils.logger import logger
            logger.warning("[_plot_mr_with_plotly] close列缺失或全为NaN")
        except Exception:
            pass
        return ""
    
    # 创建子图：2行1列，共享x轴
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.6, 0.4],  # 主图60%，副图40%
        subplot_titles=(
            f'均值回归策略 - 价格与布林带 (窗口={window_val}, 进场Z={entry_z}, 出场Z={exit_z})',
            'Z分数指标'
        )
    )
    
    # ========== 阶段1：主图基础绘制 ==========
    # 1. 价格线（处理NaN：Plotly会自动跳过NaN点，但确保数据有效）
    # 首先统一所有数据的长度，确保索引对齐
    min_len = len(data)
    if len(dates) != min_len:
        min_len = min(len(dates), min_len)
        dates = dates[:min_len]
        data = data.iloc[:min_len].copy()  # 截取data以匹配dates长度
    
    # 确保截取后数据不为空
    if len(data) == 0:
        try:
            from utils.logger import logger
            logger.warning("[_plot_mr_with_plotly] 数据截取后为空")
        except Exception:
            pass
        return ""
    
    close_data = data['close'].copy()
    
    # 确保至少有一些有效数据
    if close_data.isna().all():
        try:
            from utils.logger import logger
            logger.warning("[_plot_mr_with_plotly] close数据全为NaN")
        except Exception:
            pass
        return ""
    
    fig.add_trace(
        go.Scatter(
            x=dates,
            y=close_data,
            mode='lines',
            name='收盘价',
            line=dict(color='black', width=1.5),
            hovertemplate='日期: %{x}<br>收盘价: %{y:.2f}<extra></extra>',
            connectgaps=False  # 不连接NaN点之间的间隙
        ),
        row=1, col=1
    )
    
    # 2. 均值线（如果存在且有效）
    if 'mr_mean' in data.columns:
        mr_mean_data = data['mr_mean'].copy()
        # 数据已经对齐，不需要再次截取
        
        # 即使有NaN值，也尝试绘制（Plotly会自动跳过NaN点）
        if not mr_mean_data.isna().all():
            fig.add_trace(
                go.Scatter(
                    x=dates,
                    y=mr_mean_data,
                    mode='lines',
                    name='均值线',
                    line=dict(color='blue', width=1, dash='dash'),
                    hovertemplate='日期: %{x}<br>均值: %{y:.2f}<extra></extra>',
                    connectgaps=False
                ),
                row=1, col=1
            )
    
    # 3. 布林带（如果存在）
    if 'mr_mean' in data.columns and 'mr_std' in data.columns:
        mr_mean_data = data['mr_mean'].copy()
        mr_std_data = data['mr_std'].copy()
        
        # 数据已经对齐，不需要再次截取
        
        # 计算布林带（处理NaN值：如果mr_std为NaN，则布林带也为NaN，Plotly会自动跳过）
        upper_band = mr_mean_data + entry_z * mr_std_data
        lower_band = mr_mean_data - entry_z * mr_std_data
        exit_band = mr_mean_data + exit_z * mr_std_data
        
        # 确保至少有一些有效数据
        if upper_band.isna().all() and lower_band.isna().all():
            try:
                from utils.logger import logger
                logger.warning("[_plot_mr_with_plotly] 布林带数据全为NaN，跳过绘制")
            except Exception:
                pass
        else:
            # 布林带填充区域（先添加下轨，再添加上轨，这样fill='tonexty'才能正确填充）
            fig.add_trace(
                go.Scatter(
                    x=dates,
                    y=lower_band,
                    mode='lines',
                    name=f'下轨(-{entry_z}σ)',
                    line=dict(color='orange', width=1, dash='dot'),
                    showlegend=True,
                    hovertemplate='日期: %{x}<br>下轨: %{y:.2f}<extra></extra>',
                    connectgaps=False
                ),
                row=1, col=1
            )
            
            fig.add_trace(
                go.Scatter(
                    x=dates,
                    y=upper_band,
                    mode='lines',
                    name=f'上轨(+{entry_z}σ)',
                    line=dict(color='orange', width=1, dash='dot'),
                    fill='tonexty',  # 填充到下一条线（下轨）
                    fillcolor='rgba(128, 128, 128, 0.2)',
                    showlegend=True,
                    hovertemplate='日期: %{x}<br>上轨: %{y:.2f}<extra></extra>',
                    connectgaps=False
                ),
                row=1, col=1
            )
            
            # 出场线（如果exit_z != 0）
            if exit_z != 0:
                fig.add_trace(
                    go.Scatter(
                        x=dates,
                        y=exit_band,
                        mode='lines',
                        name=f'出场线(+{exit_z}σ)',
                        line=dict(color='green', width=1, dash='dashdot'),
                        hovertemplate='日期: %{x}<br>出场线: %{y:.2f}<extra></extra>',
                        connectgaps=False
                    ),
                    row=1, col=1
                )
    
    # 更新主图布局
    fig.update_xaxes(title_text="", row=1, col=1)
    fig.update_yaxes(title_text="价格", row=1, col=1)
    
    # ========== 阶段2：副图（Z分数图）和Z阈值线 ==========
    # 即使z列不存在或全为NaN，也要添加Z阈值线，确保副图有内容
    if 'z' in data.columns and not data['z'].isna().all():
        z_data = data['z'].copy()
        # 数据已经对齐，不需要再次截取
        
        # 1. Z分数线
        fig.add_trace(
            go.Scatter(
                x=dates,
                y=z_data,
                mode='lines',
                name='Z分数',
                line=dict(color='purple', width=1.5),
                hovertemplate='日期: %{x}<br>Z分数: %{y:.2f}<extra></extra>',
                legendgroup='z_score',
                connectgaps=False
            ),
            row=2, col=1
        )
    else:
        # 如果z列不存在或全为NaN，至少添加一条零线作为占位
        try:
            from utils.logger import logger
            logger.warning("[_plot_mr_with_plotly] z列缺失或全为NaN，仅显示阈值线")
        except Exception:
            pass
    
    # 2. Z阈值线（使用add_hline，更简洁）
    # 进场线 (Z = -entry_z)
    fig.add_hline(
        y=-entry_z,
        line_dash="dot",
        line_color="orange",
        annotation_text=f"进场线(Z=-{entry_z})",
        annotation_position="right",
        row=2, col=1
    )
    
    # 超涨线 (Z = +entry_z)
    fig.add_hline(
        y=entry_z,
        line_dash="dot",
        line_color="orange",
        annotation_text=f"超涨线(Z=+{entry_z})",
        annotation_position="right",
        row=2, col=1
    )
    
    # 出场线 (Z = exit_z)
    if exit_z != 0:
        fig.add_hline(
            y=exit_z,
            line_dash="dashdot",
            line_color="green",
            annotation_text=f"出场线(Z={exit_z})",
            annotation_position="right",
            row=2, col=1
        )
    
    # 均值线 (Z = 0)
    fig.add_hline(
        y=0,
        line_dash="dash",
        line_color="blue",
        line_width=0.8,
        opacity=0.5,
        annotation_text="均值线(Z=0)",
        annotation_position="right",
        row=2, col=1
    )
    
    # ========== 阶段3：添加买卖信号点标记（主图和副图） ==========
    buy_indices = []
    sell_indices = []
    
    if 'positions' in data.columns:
        buy_idx = data['positions'] > 0
        sell_idx = data['positions'] < 0
        
        # 主图：买入信号点
        if buy_idx.any():
            buy_x = dates[buy_idx]
            buy_y = data['close'][buy_idx]
            # 使用位置索引而不是标签索引，确保索引正确
            buy_positions = np.where(buy_idx)[0].tolist()
            buy_indices = buy_positions  # 保存位置索引用于工具提示
            
            # 生成工具提示文本（确保文本列表长度与数据点数量一致）
            buy_hovertexts = []
            for i, pos in enumerate(buy_positions):
                if 0 <= pos < len(data) and i < len(buy_x):
                    try:
                        tooltip = _get_tooltip_text(pos, data, "买入", html_format=False)
                        # 清理工具提示文本，移除可能导致Plotly解析错误的字符
                        clean_tooltip = tooltip.replace('\n', '<br>').replace('\r', '').strip()
                        if clean_tooltip:
                            buy_hovertexts.append(clean_tooltip)
                        else:
                            buy_hovertexts.append(f"买入信号<br>日期: {dates[buy_idx].iloc[i] if hasattr(dates[buy_idx], 'iloc') else dates[buy_idx][i]}<br>价格: {buy_y.iloc[i] if hasattr(buy_y, 'iloc') else buy_y[i]:.2f}")
                    except Exception as e:
                        # 如果工具提示生成失败，使用简单文本
                        try:
                            from utils.logger import logger
                            logger.warning(f"[_plot_mr_with_plotly] 工具提示生成失败: {str(e)}")
                        except Exception:
                            pass
                        buy_hovertexts.append(f"买入信号<br>索引: {pos}")
            
            # 确保hovertexts长度与数据点数量一致
            if len(buy_hovertexts) != len(buy_x):
                buy_hovertexts = [f"买入信号<br>价格: {y:.2f}" for y in buy_y]
            
            try:
                fig.add_trace(
                    go.Scatter(
                        x=buy_x,
                        y=buy_y,
                        mode='markers',
                        name='买入信号',
                        marker=dict(
                            symbol='triangle-up',
                            size=12,
                            color='green',
                            line=dict(width=1, color='darkgreen')
                        ),
                        hovertemplate='%{text}<extra></extra>',
                        text=buy_hovertexts if len(buy_hovertexts) == len(buy_x) else None,
                        legendgroup='signals'
                    ),
                    row=1, col=1
                )
            except Exception as e:
                # 如果添加trace失败，尝试不使用text参数
                try:
                    from utils.logger import logger
                    logger.warning(f"[_plot_mr_with_plotly] 添加买入信号trace失败: {str(e)}，尝试不使用text参数")
                    fig.add_trace(
                        go.Scatter(
                            x=buy_x,
                            y=buy_y,
                            mode='markers',
                            name='买入信号',
                            marker=dict(
                                symbol='triangle-up',
                                size=12,
                                color='green',
                                line=dict(width=1, color='darkgreen')
                            ),
                            legendgroup='signals'
                        ),
                        row=1, col=1
                    )
                except Exception as e2:
                    try:
                        from utils.logger import logger
                        logger.error(f"[_plot_mr_with_plotly] 无法添加买入信号trace: {str(e2)}")
                    except Exception:
                        pass
        
        # 主图：卖出信号点
        if sell_idx.any():
            sell_x = dates[sell_idx]
            sell_y = data['close'][sell_idx]
            # 使用位置索引而不是标签索引，确保索引正确
            sell_positions = np.where(sell_idx)[0].tolist()
            sell_indices = sell_positions  # 保存位置索引用于工具提示
            
            # 生成工具提示文本（确保文本列表长度与数据点数量一致）
            sell_hovertexts = []
            for i, pos in enumerate(sell_positions):
                if 0 <= pos < len(data) and i < len(sell_x):
                    try:
                        tooltip = _get_tooltip_text(pos, data, "卖出", html_format=False)
                        # 清理工具提示文本，移除可能导致Plotly解析错误的字符
                        clean_tooltip = tooltip.replace('\n', '<br>').replace('\r', '').strip()
                        if clean_tooltip:
                            sell_hovertexts.append(clean_tooltip)
                        else:
                            sell_hovertexts.append(f"卖出信号<br>日期: {dates[sell_idx].iloc[i] if hasattr(dates[sell_idx], 'iloc') else dates[sell_idx][i]}<br>价格: {sell_y.iloc[i] if hasattr(sell_y, 'iloc') else sell_y[i]:.2f}")
                    except Exception as e:
                        # 如果工具提示生成失败，使用简单文本
                        try:
                            from utils.logger import logger
                            logger.warning(f"[_plot_mr_with_plotly] 工具提示生成失败: {str(e)}")
                        except Exception:
                            pass
                        sell_hovertexts.append(f"卖出信号<br>索引: {pos}")
            
            # 确保hovertexts长度与数据点数量一致
            if len(sell_hovertexts) != len(sell_x):
                sell_hovertexts = [f"卖出信号<br>价格: {y:.2f}" for y in sell_y]
            
            try:
                fig.add_trace(
                    go.Scatter(
                        x=sell_x,
                        y=sell_y,
                        mode='markers',
                        name='卖出信号',
                        marker=dict(
                            symbol='triangle-down',
                            size=12,
                            color='red',
                            line=dict(width=1, color='darkred')
                        ),
                        hovertemplate='%{text}<extra></extra>',
                        text=sell_hovertexts if len(sell_hovertexts) == len(sell_x) else None,
                        legendgroup='signals'
                    ),
                    row=1, col=1
                )
            except Exception as e:
                # 如果添加trace失败，尝试不使用text参数
                try:
                    from utils.logger import logger
                    logger.warning(f"[_plot_mr_with_plotly] 添加卖出信号trace失败: {str(e)}，尝试不使用text参数")
                    fig.add_trace(
                        go.Scatter(
                            x=sell_x,
                            y=sell_y,
                            mode='markers',
                            name='卖出信号',
                            marker=dict(
                                symbol='triangle-down',
                                size=12,
                                color='red',
                                line=dict(width=1, color='darkred')
                            ),
                            legendgroup='signals'
                        ),
                        row=1, col=1
                    )
                except Exception as e2:
                    try:
                        from utils.logger import logger
                        logger.error(f"[_plot_mr_with_plotly] 无法添加卖出信号trace: {str(e2)}")
                    except Exception:
                        pass
        
        # 副图：买入信号点（在Z分数图上）
        if buy_idx.any() and 'z' in data.columns:
            buy_x_z = dates[buy_idx]
            buy_y_z = data['z'][buy_idx]
            
            # 生成工具提示文本（使用之前保存的位置索引，确保长度一致）
            buy_hovertexts_z = []
            for i, pos in enumerate(buy_indices):
                if 0 <= pos < len(data) and i < len(buy_x_z):
                    try:
                        tooltip = _get_tooltip_text(pos, data, "买入", html_format=False)
                        clean_tooltip = tooltip.replace('\n', '<br>').replace('\r', '').strip()
                        if clean_tooltip:
                            buy_hovertexts_z.append(clean_tooltip)
                        else:
                            buy_hovertexts_z.append(f"买入信号<br>Z分数: {buy_y_z.iloc[i] if hasattr(buy_y_z, 'iloc') else buy_y_z[i]:.2f}")
                    except Exception:
                        buy_hovertexts_z.append(f"买入信号<br>索引: {pos}")
            
            if len(buy_hovertexts_z) != len(buy_x_z):
                buy_hovertexts_z = [f"买入信号<br>Z分数: {y:.2f}" for y in buy_y_z]
            
            try:
                fig.add_trace(
                    go.Scatter(
                        x=buy_x_z,
                        y=buy_y_z,
                        mode='markers',
                        name='买入信号',
                        marker=dict(
                            symbol='triangle-up',
                            size=12,
                            color='green',
                            line=dict(width=1, color='darkgreen')
                        ),
                        hovertemplate='%{text}<extra></extra>',
                        text=buy_hovertexts_z if len(buy_hovertexts_z) == len(buy_x_z) else None,
                        legendgroup='signals',
                        showlegend=False  # 副图的信号点不重复显示在图例中
                    ),
                    row=2, col=1
                )
            except Exception as e:
                try:
                    from utils.logger import logger
                    logger.warning(f"[_plot_mr_with_plotly] 添加副图买入信号trace失败: {str(e)}，尝试不使用text参数")
                    fig.add_trace(
                        go.Scatter(
                            x=buy_x_z,
                            y=buy_y_z,
                            mode='markers',
                            name='买入信号',
                            marker=dict(
                                symbol='triangle-up',
                                size=12,
                                color='green',
                                line=dict(width=1, color='darkgreen')
                            ),
                            legendgroup='signals',
                            showlegend=False
                        ),
                        row=2, col=1
                    )
                except Exception:
                    pass
        
        # 副图：卖出信号点（在Z分数图上）
        if sell_idx.any() and 'z' in data.columns:
            sell_x_z = dates[sell_idx]
            sell_y_z = data['z'][sell_idx]
            
            # 生成工具提示文本（使用之前保存的位置索引，确保长度一致）
            sell_hovertexts_z = []
            for i, pos in enumerate(sell_indices):
                if 0 <= pos < len(data) and i < len(sell_x_z):
                    try:
                        tooltip = _get_tooltip_text(pos, data, "卖出", html_format=False)
                        clean_tooltip = tooltip.replace('\n', '<br>').replace('\r', '').strip()
                        if clean_tooltip:
                            sell_hovertexts_z.append(clean_tooltip)
                        else:
                            sell_hovertexts_z.append(f"卖出信号<br>Z分数: {sell_y_z.iloc[i] if hasattr(sell_y_z, 'iloc') else sell_y_z[i]:.2f}")
                    except Exception:
                        sell_hovertexts_z.append(f"卖出信号<br>索引: {pos}")
            
            if len(sell_hovertexts_z) != len(sell_x_z):
                sell_hovertexts_z = [f"卖出信号<br>Z分数: {y:.2f}" for y in sell_y_z]
            
            try:
                fig.add_trace(
                    go.Scatter(
                        x=sell_x_z,
                        y=sell_y_z,
                        mode='markers',
                        name='卖出信号',
                        marker=dict(
                            symbol='triangle-down',
                            size=12,
                            color='red',
                            line=dict(width=1, color='darkred')
                        ),
                        hovertemplate='%{text}<extra></extra>',
                        text=sell_hovertexts_z if len(sell_hovertexts_z) == len(sell_x_z) else None,
                        legendgroup='signals',
                        showlegend=False  # 副图的信号点不重复显示在图例中
                    ),
                    row=2, col=1
                )
            except Exception as e:
                try:
                    from utils.logger import logger
                    logger.warning(f"[_plot_mr_with_plotly] 添加副图卖出信号trace失败: {str(e)}，尝试不使用text参数")
                    fig.add_trace(
                        go.Scatter(
                            x=sell_x_z,
                            y=sell_y_z,
                            mode='markers',
                            name='卖出信号',
                            marker=dict(
                                symbol='triangle-down',
                                size=12,
                                color='red',
                                line=dict(width=1, color='darkred')
                            ),
                            legendgroup='signals',
                            showlegend=False
                        ),
                        row=2, col=1
                    )
                except Exception:
                    pass
    
    # 更新副图布局
    fig.update_xaxes(title_text="日期", row=2, col=1)
    fig.update_yaxes(title_text="Z分数", row=2, col=1)
    
    # ========== 阶段4：优化工具提示和交互功能 ==========
    # Plotly默认支持缩放、平移、联动等功能，这里进行优化配置
    
    # 更新整体布局
    fig.update_layout(
        height=1000,
        showlegend=True,
        legend=dict(
            orientation="v",
            yanchor="top",
            y=1,
            xanchor="left",
            x=1.02,
            bgcolor='rgba(255,255,255,0.8)',
            bordercolor='rgba(0,0,0,0.2)',
            borderwidth=1
        ),
        hovermode='x unified',  # 统一hover模式，实现两个子图的联动
        template='plotly_white',
        # 添加工具栏配置
        modebar=dict(
            orientation='v',
            bgcolor='rgba(255,255,255,0.8)'
        ),
        # 添加标题
        title=dict(
            text=f'均值回归策略图表 (窗口={window_val})',
            x=0.5,
            xanchor='center',
            font=dict(size=16)
        )
    )
    
    # 配置x轴联动（两个子图共享x轴，缩放和平移会同步）
    fig.update_xaxes(
        rangeslider=dict(visible=False),  # 禁用底部范围滑块，保持简洁
        rangeselector=dict(
            buttons=list([
                dict(count=7, label="7天", step="day", stepmode="backward"),
                dict(count=30, label="30天", step="day", stepmode="backward"),
                dict(count=90, label="90天", step="day", stepmode="backward"),
                dict(step="all", label="全部")
            ]),
            bgcolor='rgba(255,255,255,0.8)',
            bordercolor='rgba(0,0,0,0.2)',
            borderwidth=1
        ),
        row=2, col=1  # 只在副图显示范围选择器
    )
    
    # 优化网格线
    fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor='rgba(128,128,128,0.2)', row=1, col=1)
    fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor='rgba(128,128,128,0.2)', row=2, col=1)
    fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor='rgba(128,128,128,0.2)', row=1, col=1)
    fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor='rgba(128,128,128,0.2)', row=2, col=1)
    
    # 返回HTML字符串
    # 使用'cdn'模式，确保Plotly.js从CDN加载（适合Streamlit环境）
    # 设置config确保图表能正确显示，并避免iframe通信错误
    config = {
        'displayModeBar': True,  # 显示工具栏
        'displaylogo': False,     # 隐藏Plotly logo
        'modeBarButtonsToRemove': ['lasso2d', 'select2d'],  # 移除不需要的工具
        'toImageButtonOptions': {
            'format': 'png',
            'filename': 'mr_chart',
            'height': 1000,
            'width': 1200,
            'scale': 1
        },
        # 避免iframe通信错误
        'frameMargins': 0,
        'doubleClick': 'reset',
        'showTips': True,
        'responsive': True,
        'staticPlot': False
    }
    
    # 检查图表是否有任何trace（如果没有，说明数据有问题）
    if len(fig.data) == 0:
        try:
            from utils.logger import logger
            logger.warning("[_plot_mr_with_plotly] 图表没有任何trace，数据可能无效")
        except Exception:
            pass
        return ""
    
    try:
        # 生成HTML，使用CDN模式，并添加错误处理以避免iframe通信问题
        html_str = fig.to_html(
            include_plotlyjs='cdn',  # 使用CDN加载Plotly.js（适合Streamlit环境）
            div_id='mr_chart',
            config=config,
            full_html=True,  # 返回完整HTML文档，确保Plotly.js正确加载
            default_width='100%',  # 设置默认宽度
            default_height='1000'  # 设置默认高度
        )
        
        # 添加错误处理脚本，避免"message channel closed"错误
        # 这个错误通常由浏览器扩展或iframe通信问题引起，不影响图表显示
        error_handler_script = """
<script>
// 捕获并忽略message channel错误（通常由浏览器扩展引起）
window.addEventListener('error', function(e) {
    if (e.message && e.message.includes('message channel')) {
        e.preventDefault();
        console.debug('Ignored message channel error (likely from browser extension)');
        return false;
    }
});

// 处理Promise rejection（避免未捕获的Promise错误）
window.addEventListener('unhandledrejection', function(e) {
    if (e.reason && e.reason.message && e.reason.message.includes('message channel')) {
        e.preventDefault();
        console.debug('Ignored promise rejection (likely from browser extension)');
        return false;
    }
});
</script>
"""
        
        # 在</body>标签前插入错误处理脚本
        body_end = html_str.rfind('</body>')
        if body_end >= 0:
            html_str = html_str[:body_end] + error_handler_script + html_str[body_end:]
        else:
            # 如果没有</body>，在</html>前插入
            html_end = html_str.rfind('</html>')
            if html_end >= 0:
                html_str = html_str[:html_end] + error_handler_script + html_str[html_end:]
            else:
                # 如果都没有，直接追加
                html_str = html_str + error_handler_script
    except Exception as e:
        try:
            from utils.logger import logger
            logger.error(f"[_plot_mr_with_plotly] HTML生成异常: {str(e)}")
        except Exception:
            pass
        return ""
    
    # 验证HTML是否生成成功
    if not html_str or len(html_str.strip()) == 0:
        try:
            from utils.logger import logger
            logger.warning("[_plot_mr_with_plotly] HTML生成失败，返回空字符串")
        except Exception:
            pass
        return ""
    
    # 确保HTML包含必要的Plotly元素（放宽检查条件，只要包含plotly相关字符串即可）
    html_lower = html_str.lower()
    has_plotly = ('plotly' in html_lower or 
                  'plotly.js' in html_lower or 
                  'plotly.min.js' in html_lower or
                  'plotly-latest.min.js' in html_lower or
                  'new plotlygraph' in html_lower or
                  'plotlygraph' in html_lower)
    
    if not has_plotly:
        try:
            from utils.logger import logger
            logger.warning("[_plot_mr_with_plotly] 生成的HTML不包含Plotly元素")
            # 输出前500字符用于调试
            logger.warning(f"[_plot_mr_with_plotly] HTML前500字符: {html_str[:500]}")
        except Exception:
            pass
        return ""
    
    try:
        from utils.logger import logger
        logger.info(f"[_plot_mr_with_plotly] Plotly HTML生成成功，长度: {len(html_str)}")
    except Exception:
        pass
    
    return html_str


def plot_mean_reversion_signals(data: pd.DataFrame, outfile: str = "price_mr.png",
                                 entry_z: float = 2.0, exit_z: float = 0.0,
                                 interactive: bool | None = None) -> str:
    """
    绘制均值回归策略的可视化图表，支持交互式悬浮提示和十字线联动
    
    展示内容：
    1. 主图：价格线、均值线、布林带上下轨、买卖信号
    2. 副图：Z分数线
    
    Args:
        data: 包含 mr_mean, mr_std, z, close, positions 等列的DataFrame
        outfile: 输出文件名（非交互模式）或临时文件路径
        entry_z: 进场Z阈值
        exit_z: 出场Z阈值
        interactive: 是否使用交互模式（None时自动检测）
    
    Returns:
        文件路径（PNG）或HTML字符串（交互模式）
    """
    # 调试日志：函数被调用
    try:
        from utils.logger import logger
        logger.info(f"[plot_mean_reversion_signals] 函数被调用: data.shape={data.shape if data is not None else 'None'}, entry_z={entry_z}, exit_z={exit_z}, interactive={interactive}")
    except Exception:
        pass
    
    if data is None or data.empty:
        try:
            from utils.logger import logger
            logger.warning("[plot_mean_reversion_signals] 数据为空或None，返回空字符串")
        except Exception:
            pass
        return ""
    
    # 自动检测交互模式
    if interactive is None:
        interactive = _is_streamlit_env()
    
    try:
        from utils.logger import logger
        logger.info(f"[plot_mean_reversion_signals] 交互模式: {interactive}")
    except Exception:
        pass
    
    try:
        import matplotlib  # type: ignore
        if not interactive:
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # type: ignore
        import numpy as np  # type: ignore
        import warnings
        warnings.filterwarnings('ignore')
        
        # 配置中文字体支持
        plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans', 'Arial Unicode MS', 'sans-serif']
        plt.rcParams['axes.unicode_minus'] = False
        
        try:
            from utils.logger import logger
            logger.info("[plot_mean_reversion_signals] matplotlib导入成功")
        except Exception:
            pass
        
    except Exception as e:
        try:
            from utils.logger import logger
            logger.error(f"[plot_mean_reversion_signals] matplotlib导入失败: {str(e)}")
        except Exception:
            pass
        return ""

    # 检查必要的列（与MA图表保持一致，允许部分列缺失时继续尝试绘制）
    # 注意：如果Plotly已经失败，这里不要过于严格，让mpld3有机会尝试
    required_cols = ['close', 'mr_mean', 'mr_std', 'z']
    missing_cols = [col for col in required_cols if col not in data.columns]
    if missing_cols:
        # 如果缺少关键列close，直接返回
        if 'close' not in data.columns:
            try:
                import streamlit as st
                st.warning(f"图表生成失败：缺少必需列 close")
            except Exception:
                pass
            return ""
        # 如果只是缺少其他列，记录警告但继续尝试（mpld3可能能够处理部分缺失）
        try:
            from utils.logger import logger
            logger.warning(f"[plot_mean_reversion_signals] 缺少部分列: {missing_cols}，继续尝试绘制")
        except Exception:
            pass
    
    # 检查数据是否为空或全为NaN
    if data.empty:
        try:
            import streamlit as st
            st.warning("图表生成失败：数据为空")
        except Exception:
            pass
        return ""
    
    # 检查关键列是否有有效数据（放宽检查，与MA图表保持一致）
    # 如果close全为NaN，直接返回；但如果只是mr_mean全为NaN，继续尝试（可能能绘制价格线）
    if 'close' in data.columns and data['close'].isna().all():
        try:
            import streamlit as st
            st.warning("图表生成失败：close列全为NaN")
        except Exception:
            pass
        return ""
    # 如果mr_mean全为NaN，记录警告但继续（可能能绘制价格线和Z分数）
    if 'mr_mean' in data.columns and data['mr_mean'].isna().all():
        try:
            from utils.logger import logger
            logger.warning("[plot_mean_reversion_signals] mr_mean全为NaN，但继续尝试绘制其他元素")
        except Exception:
            pass
    # 原来的检查逻辑（已替换为上面的更宽松检查）
    # if data['close'].isna().all() or data['mr_mean'].isna().all():
        try:
            import streamlit as st
            st.warning("图表生成失败：关键数据列全为NaN")
        except Exception:
            pass
        return ""

    # 获取窗口参数
    window_val = "N/A"
    if hasattr(data, 'attrs') and 'window' in data.attrs:
        window_val = data.attrs['window']
    elif 'window' in data.columns:
        window_series = data['window']
        if len(window_series) > 0:
            window_val = window_series.iloc[0] if hasattr(window_series, 'iloc') else window_series[0]

    # 阶段5：尝试使用Plotly（仅MR策略），失败时回退到mpld3
    # 注意：与MA图表不同，MR图表先尝试Plotly，失败后才使用mpld3
    plotly_failed = False
    plotly_failure_reason = None
    
    if interactive:
        try:
            import plotly.graph_objects as go
            from plotly.subplots import make_subplots
            result = _plot_mr_with_plotly(data, entry_z, exit_z, window_val, outfile)
            if result and len(result.strip()) > 0:  # 如果Plotly成功生成HTML，直接返回
                try:
                    from utils.logger import logger
                    logger.info("[plot_mean_reversion_signals] Plotly图表生成成功")
                except Exception:
                    pass
                return result
            else:
                # Plotly返回空结果，记录原因并回退到mpld3
                plotly_failed = True
                plotly_failure_reason = "Plotly返回空结果"
                try:
                    from utils.logger import logger
                    logger.warning("[plot_mean_reversion_signals] Plotly返回空结果，回退到mpld3")
                    # 输出诊断信息
                    logger.warning(f"[plot_mean_reversion_signals] 数据形状: {data.shape}, 列: {list(data.columns)}")
                    logger.warning(f"[plot_mean_reversion_signals] close有效值: {data['close'].notna().sum()}/{len(data)}")
                except Exception:
                    pass
        except ImportError:
            # Plotly未安装，回退到mpld3
            plotly_failed = True
            plotly_failure_reason = "Plotly未安装"
            try:
                from utils.logger import logger
                logger.info("[plot_mean_reversion_signals] Plotly未安装，使用mpld3")
            except Exception:
                pass
        except Exception as e:
            # Plotly生成失败，回退到mpld3
            plotly_failed = True
            plotly_failure_reason = f"Plotly生成失败: {str(e)}"
            try:
                from utils.logger import logger
                logger.warning(f"[plot_mean_reversion_signals] {plotly_failure_reason}，回退到mpld3")
            except Exception:
                pass
    
    # 如果Plotly失败，继续使用mpld3/matplotlib实现（与MA图表保持一致）
    # 注意：此时不要因为Plotly的严格验证而拒绝数据，mpld3可能能够处理

    # 继续使用mpld3/matplotlib实现（原有代码）
    # ========== 数据验证和诊断 ==========
    # 根据matplotlib空白图表排查清单进行检查
    
    # 1. 检查数据是否为空
    if data.empty:
        try:
            from utils.logger import logger
            logger.warning("[plot_mean_reversion_signals] matplotlib回退：数据为空")
        except Exception:
            pass
        return ""
    
    # 2. 检查关键列是否存在
    if 'close' not in data.columns:
        try:
            from utils.logger import logger
            logger.warning("[plot_mean_reversion_signals] matplotlib回退：缺少close列")
        except Exception:
            pass
        return ""
    
    # 3. 检查数据是否全为NaN
    if data['close'].isna().all():
        try:
            from utils.logger import logger
            logger.warning("[plot_mean_reversion_signals] matplotlib回退：close数据全为NaN")
        except Exception:
            pass
        return ""
    
    # 4. 准备x轴数据（datetime转换）
    if 'date' in data.columns:
        try:
            x = pd.to_datetime(data['date'])
        except Exception as e:
            try:
                from utils.logger import logger
                logger.warning(f"[plot_mean_reversion_signals] 日期转换失败: {str(e)}，使用索引")
            except Exception:
                pass
            x = pd.Series(range(len(data)))
    else:
        x = pd.Series(range(len(data)))
    
    # 5. 确保x和y维度一致（关键检查）
    if len(x) != len(data['close']):
        min_len = min(len(x), len(data['close']))
        x = x.iloc[:min_len] if hasattr(x, 'iloc') else x[:min_len]
        data = data.iloc[:min_len].copy()
        try:
            from utils.logger import logger
            logger.warning(f"[plot_mean_reversion_signals] x和y维度不一致（{len(x)} vs {len(data['close'])}），截取到 {min_len} 行")
        except Exception:
            pass
    
    # 6. 再次检查截取后数据是否有效
    if len(data) == 0:
        try:
            from utils.logger import logger
            logger.warning("[plot_mean_reversion_signals] matplotlib回退：截取后数据为空")
        except Exception:
            pass
        return ""
    
    # 7. 诊断信息（仅在调试时输出）
    try:
        from utils.logger import logger
        logger.debug(f"[plot_mean_reversion_signals] matplotlib绘图数据: shape={data.shape}, x_len={len(x)}, close_valid={data['close'].notna().sum()}/{len(data)}")
    except Exception:
        pass
    
    # 创建图表
    fig = plt.figure(figsize=(12, 10))
    
    # 主图：价格和布林带
    ax1 = plt.subplot(2, 1, 1)
    
    # 配置中文字体支持（与MA图线保持一致）
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans', 'Arial Unicode MS', 'sans-serif']
    plt.rcParams['axes.unicode_minus'] = False
    
    # 直接使用原始数据绘制，让matplotlib自然处理NaN（与MA图线保持一致）
    # 绘制价格线（确保有有效数据）
    if not data['close'].isna().all():
        ax1.plot(x, data['close'], label='收盘价', color='black', linewidth=1.5, marker='', linestyle='-')
    else:
        try:
            from utils.logger import logger
            logger.warning("[plot_mean_reversion_signals] 无法绘制价格线：数据全为NaN")
        except Exception:
            pass
    
    # 绘制均值线（如果存在且有效）
    if 'mr_mean' in data.columns and not data['mr_mean'].isna().all():
        # 确保长度一致
        if len(x) == len(data['mr_mean']):
            ax1.plot(x, data['mr_mean'], label='均值线', color='blue', linewidth=1, linestyle='--', marker='')
    
    # 计算并绘制布林带（与MA图线处理方式一致，直接使用原始数据）
    if 'mr_mean' in data.columns and 'mr_std' in data.columns:
        # 确保长度一致
        if len(data['mr_mean']) == len(x) and len(data['mr_std']) == len(x):
            upper_band = data['mr_mean'] + entry_z * data['mr_std']
            lower_band = data['mr_mean'] - entry_z * data['mr_std']
            exit_band = data['mr_mean'] + exit_z * data['mr_std']
            
            # 只在有有效数据时绘制
            if not (upper_band.isna().all() and lower_band.isna().all()):
                ax1.fill_between(x, upper_band, lower_band, alpha=0.2, color='gray', label=f'±{entry_z}σ通道')
                ax1.plot(x, upper_band, color='orange', linewidth=1, linestyle=':', label=f'上轨(+{entry_z}σ)', marker='')
                ax1.plot(x, lower_band, color='orange', linewidth=1, linestyle=':', label=f'下轨(-{entry_z}σ)', marker='')
            
            if exit_z != 0 and not exit_band.isna().all():
                ax1.plot(x, exit_band, color='green', linewidth=1, linestyle='-.', label=f'出场线(+{exit_z}σ)', marker='')
    
    # 绘制买卖信号点（主图）
    buy_scatter1 = None
    sell_scatter1 = None
    buy_scatter2 = None
    sell_scatter2 = None
    buy_indices = []
    sell_indices = []
    
    if 'positions' in data.columns:
        buy_idx = data['positions'] > 0
        sell_idx = data['positions'] < 0
        
        if buy_idx.any():
            buy_x = x[buy_idx] if hasattr(x, 'iloc') else pd.Series(x)[buy_idx]
            buy_y = data['close'][buy_idx]
            buy_indices = data.index[buy_idx].tolist()
            # 确保x和y长度一致
            if len(buy_x) == len(buy_y):
                buy_scatter1 = ax1.scatter(buy_x, buy_y, marker='^', 
                                          color='green', s=100, label='买入信号', zorder=5, picker=True)
        
        if sell_idx.any():
            sell_x = x[sell_idx] if hasattr(x, 'iloc') else pd.Series(x)[sell_idx]
            sell_y = data['close'][sell_idx]
            sell_indices = data.index[sell_idx].tolist()
            # 确保x和y长度一致
            if len(sell_x) == len(sell_y):
                sell_scatter1 = ax1.scatter(sell_x, sell_y, marker='v', 
                                           color='red', s=100, label='卖出信号', zorder=5, picker=True)
    
    ax1.set_title(f'均值回归策略 - 价格与布林带 (窗口={window_val}, 进场Z={entry_z}, 出场Z={exit_z})', 
                  fontsize=14, fontweight='bold')
    ax1.set_ylabel('价格', fontsize=11)
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc='best', fontsize=9)
    
    # 副图：Z分数
    ax2 = plt.subplot(2, 1, 2, sharex=ax1)
    if 'z' in data.columns and not data['z'].isna().all():
        # 确保长度一致
        if len(x) == len(data['z']):
            ax2.plot(x, data['z'], label='Z分数', color='purple', linewidth=1.5, marker='', linestyle='-')
    
    # 绘制Z阈值线
    ax2.axhline(y=-entry_z, color='orange', linestyle=':', linewidth=1, label=f'进场线(Z=-{entry_z})')
    ax2.axhline(y=entry_z, color='orange', linestyle=':', linewidth=1, label=f'超涨线(Z=+{entry_z})')
    ax2.axhline(y=exit_z, color='green', linestyle='-.', linewidth=1, label=f'出场线(Z={exit_z})')
    ax2.axhline(y=0, color='blue', linestyle='--', linewidth=0.8, alpha=0.5, label='均值线(Z=0)')
    
    # 标记买卖信号区域（副图）
    if 'positions' in data.columns:
        buy_idx = data['positions'] > 0
        sell_idx = data['positions'] < 0
        
        if buy_idx.any() and 'z' in data.columns:
            buy_x = x[buy_idx] if hasattr(x, 'iloc') else pd.Series(x)[buy_idx]
            buy_y = data['z'][buy_idx]
            # 确保x和y长度一致
            if len(buy_x) == len(buy_y):
                buy_scatter2 = ax2.scatter(buy_x, buy_y, marker='^', 
                                          color='green', s=100, label='买入信号', zorder=5, picker=True)
        
        if sell_idx.any() and 'z' in data.columns:
            sell_x = x[sell_idx] if hasattr(x, 'iloc') else pd.Series(x)[sell_idx]
            sell_y = data['z'][sell_idx]
            # 确保x和y长度一致
            if len(sell_x) == len(sell_y):
                sell_scatter2 = ax2.scatter(sell_x, sell_y, marker='v', 
                                           color='red', s=100, label='卖出信号', zorder=5, picker=True)
    
    ax2.set_title('Z分数指标', fontsize=12, fontweight='bold')
    ax2.set_xlabel('日期', fontsize=11)
    ax2.set_ylabel('Z分数', fontsize=11)
    ax2.grid(True, alpha=0.3)
    ax2.legend(loc='best', fontsize=9)
    
    # 收紧边距，使左侧轴更贴近页面左侧
    try:
        fig.subplots_adjust(left=0.06, right=0.98, top=0.95, bottom=0.08, hspace=0.25)
    except Exception:
        pass
    
    # 添加十字线和交互功能
    if interactive:
        try:
            import mpld3  # type: ignore
            from mpld3 import plugins  # type: ignore
            
            # 为主图的买卖点添加工具提示（使用原始data，与MA图线保持一致）
            if buy_scatter1 is not None and len(buy_indices) > 0:
                tooltips_buy = [_get_tooltip_text(idx, data, "买入", html_format=True) 
                               for idx in buy_indices]
                tooltip_buy1 = plugins.PointHTMLTooltip(buy_scatter1, tooltips_buy, voffset=10, hoffset=10)
                plugins.connect(fig, tooltip_buy1)
            
            if sell_scatter1 is not None and len(sell_indices) > 0:
                tooltips_sell = [_get_tooltip_text(idx, data, "卖出", html_format=True) 
                                for idx in sell_indices]
                tooltip_sell1 = plugins.PointHTMLTooltip(sell_scatter1, tooltips_sell, voffset=10, hoffset=10)
                plugins.connect(fig, tooltip_sell1)
            
            # 为副图的买卖点添加工具提示
            if buy_scatter2 is not None and len(buy_indices) > 0:
                tooltips_buy = [_get_tooltip_text(idx, data, "买入", html_format=True) 
                               for idx in buy_indices]
                tooltip_buy2 = plugins.PointHTMLTooltip(buy_scatter2, tooltips_buy, voffset=10, hoffset=10)
                plugins.connect(fig, tooltip_buy2)
            
            if sell_scatter2 is not None and len(sell_indices) > 0:
                tooltips_sell = [_get_tooltip_text(idx, data, "卖出", html_format=True) 
                                for idx in sell_indices]
                tooltip_sell2 = plugins.PointHTMLTooltip(sell_scatter2, tooltips_sell, voffset=10, hoffset=10)
                plugins.connect(fig, tooltip_sell2)
            
            # 添加垂直联动线（若插件可用），否则退回鼠标坐标显示
            try:
                if VLinePlugin is not None:
                    plugins.connect(fig, VLinePlugin([ax1, ax2], color='blue', linewidth=1, alpha=0.4))
                else:
                    mousepos = plugins.MousePosition(fontsize=10)
                    plugins.connect(fig, mousepos)
            except Exception:
                mousepos = plugins.MousePosition(fontsize=10)
                plugins.connect(fig, mousepos)
            
            # 生成HTML，图表左对齐，工具栏位于左侧与Y轴中间对齐
            raw_html = mpld3.fig_to_html(fig)
            
            # 验证HTML完整性
            if not raw_html or len(raw_html.strip()) == 0:
                raise ValueError("mpld3.fig_to_html返回空结果")
            
            # 检查是否是完整HTML文档，如果不是则包装成完整文档
            raw_html_lower = raw_html.strip().lower()
            is_complete_html = raw_html_lower.startswith('<!doctype') or raw_html_lower.startswith('<html')
            
            # 修复CDN链接，添加备用CDN支持
            raw_html = _fix_mpld3_cdn_links(raw_html)
            
            wrapper_css = (
                "<style>\n"
                ".mpld3-wrapper{position:relative;text-align:left;}\n"
                ".mpld3-figure{display:block;margin:0;}\n"
                ".mpld3-figure > svg{display:block;margin:0;}\n"
                "/* 工具栏容器样式 - 确保始终可点击 */\n"
                ".mpld3-toolbar{\n"
                "  position:absolute!important;\n"
                "  top:50%!important;\n"
                "  left:0!important;\n"
                "  right:auto!important;\n"
                "  transform:translateY(-50%)!important;\n"
                "  margin:0!important;\n"
                "  padding:8px!important;\n"
                "  z-index:10000!important;\n"
                "  pointer-events:auto!important;\n"
                "  background:rgba(255,255,255,0.9)!important;\n"
                "  border-radius:4px!important;\n"
                "  box-shadow:0 2px 4px rgba(0,0,0,0.1)!important;\n"
                "}\n"
                "/* 工具栏所有交互元素样式 */\n"
                ".mpld3-toolbar button,\n"
                ".mpld3-toolbar a,\n"
                ".mpld3-toolbar .mpld3-toolbar-button,\n"
                ".mpld3-toolbar [class*='toolbar'],\n"
                ".mpld3-toolbar [role='button']{\n"
                "  pointer-events:auto!important;\n"
                "  cursor:pointer!important;\n"
                "  position:relative!important;\n"
                "  z-index:10001!important;\n"
                "  display:inline-block!important;\n"
                "  margin:2px!important;\n"
                "  padding:4px!important;\n"
                "  min-width:24px!important;\n"
                "  min-height:24px!important;\n"
                "}\n"
                "/* 确保工具栏不被SVG遮挡 */\n"
                ".mpld3-figure > svg{\n"
                "  pointer-events:auto!important;\n"
                "}\n"
                "</style>"
            )
            move_js = (
                "<script>\n"
                "(function(){\n"
                "  var initAttempts = 0;\n"
                "  var maxAttempts = 10;\n"
                "  var toolbarMonitorInterval = null;\n"
                "  \n"
                "  // 修复工具栏按钮状态\n"
                "  function fixToolbarButtons(toolbar){\n"
                "    if(!toolbar) return false;\n"
                "    \n"
                "    // 查找所有可能的按钮元素\n"
                "    var selectors = ['button', 'a', '.mpld3-toolbar-button', '[class*=\"toolbar\"]', '[role=\"button\"]'];\n"
                "    var allButtons = [];\n"
                "    selectors.forEach(function(sel){\n"
                "      try{\n"
                "        var elements = toolbar.querySelectorAll(sel);\n"
                "        for(var i=0; i<elements.length; i++){\n"
                "          if(allButtons.indexOf(elements[i]) === -1){\n"
                "            allButtons.push(elements[i]);\n"
                "          }\n"
                "        }\n"
                "      }catch(e){}\n"
                "    });\n"
                "    \n"
                "    // 修复每个按钮\n"
                "    var fixed = false;\n"
                "    for(var i=0; i<allButtons.length; i++){\n"
                "      var btn = allButtons[i];\n"
                "      if(btn.style.pointerEvents !== 'auto' || btn.style.cursor !== 'pointer'){\n"
                "        btn.style.pointerEvents = 'auto';\n"
                "        btn.style.cursor = 'pointer';\n"
                "        btn.style.position = 'relative';\n"
                "        btn.style.zIndex = '10001';\n"
                "        fixed = true;\n"
                "      }\n"
                "      // 确保按钮可点击\n"
                "      if(btn.hasAttribute('disabled')){\n"
                "        btn.removeAttribute('disabled');\n"
                "        fixed = true;\n"
                "      }\n"
                "    }\n"
                "    \n"
                "    // 修复工具栏容器\n"
                "    if(toolbar.style.pointerEvents !== 'auto' || parseInt(toolbar.style.zIndex) < 10000){\n"
                "      toolbar.style.pointerEvents = 'auto';\n"
                "      toolbar.style.zIndex = '10000';\n"
                "      fixed = true;\n"
                "    }\n"
                "    \n"
                "    return fixed;\n"
                "  }\n"
                "  \n"
                "  function initToolbar(){\n"
                "    initAttempts++;\n"
                "    try{\n"
                "      var wrapper = document.currentScript ? document.currentScript.parentElement : null;\n"
                "      if(!wrapper) wrapper = document.querySelector('.mpld3-wrapper:last-child');\n"
                "      if(!wrapper){\n"
                "        if(initAttempts < maxAttempts){\n"
                "          setTimeout(initToolbar, 200);\n"
                "        }\n"
                "        return;\n"
                "      }\n"
                "      \n"
                "      var toolbar = wrapper.querySelector('.mpld3-toolbar');\n"
                "      if(!toolbar){\n"
                "        if(initAttempts < maxAttempts){\n"
                "          setTimeout(initToolbar, 200);\n"
                "        }\n"
                "        return;\n"
                "      }\n"
                "      \n"
                "      // 确保工具栏在正确的父元素中\n"
                "      if(toolbar.parentElement !== wrapper){\n"
                "        wrapper.appendChild(toolbar);\n"
                "      }\n"
                "      \n"
                "      // 修复工具栏按钮状态\n"
                "      fixToolbarButtons(toolbar);\n"
                "      \n"
                "      // 默认激活移动工具（平移工具）\n"
                "      function activatePanTool(){\n"
                "        var toolbarButtons = toolbar.querySelectorAll('.mpld3-toolbar-button, button, a, [class*=\"toolbar\"], [role=\"button\"]');\n"
                "        var panButton = null;\n"
                "        \n"
                "        // 方法1: 通过title属性查找\n"
                "        for(var i=0; i<toolbarButtons.length; i++){\n"
                "          var title = (toolbarButtons[i].getAttribute('title') || '').toLowerCase();\n"
                "          if(title.indexOf('pan') >= 0 || title.indexOf('move') >= 0 || title.indexOf('平移') >= 0){\n"
                "            panButton = toolbarButtons[i];\n"
                "            break;\n"
                "          }\n"
                "        }\n"
                "        \n"
                "        // 方法2: 如果没找到，尝试第二个按钮（通常是平移工具）\n"
                "        if(!panButton && toolbarButtons.length >= 2){\n"
                "          panButton = toolbarButtons[1];\n"
                "        }\n"
                "        \n"
                "        // 激活平移工具\n"
                "        if(panButton){\n"
                "          setTimeout(function(){\n"
                "            try{\n"
                "              if(panButton.click){\n"
                "                panButton.click();\n"
                "              } else if(panButton.dispatchEvent){\n"
                "                var clickEvent = new MouseEvent('click', {bubbles: true, cancelable: true});\n"
                "                panButton.dispatchEvent(clickEvent);\n"
                "              }\n"
                "            }catch(e){console.log('Pan tool activation:', e);}\n"
                "          }, 200);\n"
                "        }\n"
                "      }\n"
                "      \n"
                "      // 只在第一次成功初始化时激活平移工具\n"
                "      if(initAttempts === 1){\n"
                "        activatePanTool();\n"
                "      }\n"
                "      \n"
                "      // 启动工具栏状态监控\n"
                "      if(!toolbarMonitorInterval){\n"
                "        toolbarMonitorInterval = setInterval(function(){\n"
                "          var currentToolbar = wrapper.querySelector('.mpld3-toolbar');\n"
                "          if(currentToolbar){\n"
                "            fixToolbarButtons(currentToolbar);\n"
                "          }\n"
                "        }, 1000);\n"
                "      }\n"
                "      \n"
                "    }catch(e){console.error('Toolbar init error:', e);}\n"
                "  }\n"
                "  \n"
                "  // 多种方式确保执行时机正确\n"
                "  function startInit(){\n"
                "    if(document.readyState === 'complete' || document.readyState === 'interactive'){\n"
                "      setTimeout(initToolbar, 100);\n"
                "    }else{\n"
                "      document.addEventListener('DOMContentLoaded', function(){setTimeout(initToolbar, 100);});\n"
                "      window.addEventListener('load', function(){setTimeout(initToolbar, 200);});\n"
                "    }\n"
                "    // 立即尝试一次\n"
                "    setTimeout(initToolbar, 50);\n"
                "  }\n"
                "  \n"
                "  startInit();\n"
                "})();\n"
                "</script>"
            )
            # 根据HTML类型决定如何包装
            if is_complete_html:
                # 如果是完整HTML文档，在body结束前插入CSS和JS
                # 查找</body>标签位置
                body_end = raw_html.rfind('</body>')
                if body_end >= 0:
                    # 在</body>前插入CSS和JS
                    html_str = raw_html[:body_end] + wrapper_css + move_js + raw_html[body_end:]
                else:
                    # 如果没有</body>，在</html>前插入
                    html_end = raw_html.rfind('</html>')
                    if html_end >= 0:
                        html_str = raw_html[:html_end] + wrapper_css + move_js + raw_html[html_end:]
                    else:
                        # 如果都没有，直接追加
                        html_str = raw_html + wrapper_css + move_js
            else:
                # 如果是HTML片段，包装在div中
                html_str = f"<div class=\"mpld3-wrapper\">{raw_html}{wrapper_css}{move_js}</div>"
            
            plt.close(fig)
            try:
                from utils.logger import logger
                logger.info(f"[plot_mean_reversion_signals] HTML生成成功，长度: {len(html_str)}, 完整HTML: {is_complete_html}")
            except Exception:
                pass
            return html_str
            
        except ImportError as e:
            try:
                from utils.logger import logger
                logger.warning(f"[plot_mean_reversion_signals] mpld3导入失败，回退到非交互模式: {str(e)}")
            except Exception:
                pass
            interactive = False
    
    if not interactive:
        # 非交互模式：使用mplcursors添加悬浮提示（如果可用且后端支持交互）
        try:
            import matplotlib  # type: ignore
            backend = matplotlib.get_backend()
            # 只在交互式后端中启用mplcursors
            if backend.lower() not in ['agg', 'svg', 'pdf', 'ps']:
                import mplcursors  # type: ignore
                
                # 主图买卖点（使用原始data，与MA图线保持一致）
                if buy_scatter1 is not None:
                    cursor_buy1 = mplcursors.cursor(buy_scatter1, hover=True)
                    @cursor_buy1.connect("add")
                    def on_add_buy1(sel):
                        idx = buy_indices[sel.target.index]
                        sel.annotation.set_text(_get_tooltip_text(idx, data, "买入"))
                
                if sell_scatter1 is not None:
                    cursor_sell1 = mplcursors.cursor(sell_scatter1, hover=True)
                    @cursor_sell1.connect("add")
                    def on_add_sell1(sel):
                        idx = sell_indices[sel.target.index]
                        sel.annotation.set_text(_get_tooltip_text(idx, data, "卖出"))
                
                # 副图买卖点
                if buy_scatter2 is not None:
                    cursor_buy2 = mplcursors.cursor(buy_scatter2, hover=True)
                    @cursor_buy2.connect("add")
                    def on_add_buy2(sel):
                        idx = buy_indices[sel.target.index]
                        sel.annotation.set_text(_get_tooltip_text(idx, data, "买入"))
                
                if sell_scatter2 is not None:
                    cursor_sell2 = mplcursors.cursor(sell_scatter2, hover=True)
                    @cursor_sell2.connect("add")
                    def on_add_sell2(sel):
                        idx = sell_indices[sel.target.index]
                        sel.annotation.set_text(_get_tooltip_text(idx, data, "卖出"))
                
                # 添加垂直线联动（两个子图共享x轴）
                vline1 = ax1.axvline(x=x[0] if len(x) > 0 else 0, color='blue', linewidth=1, alpha=0.5, visible=False)
                vline2 = ax2.axvline(x=x[0] if len(x) > 0 else 0, color='blue', linewidth=1, alpha=0.5, visible=False)
                
                def on_mouse_move(event):
                    if event.inaxes in [ax1, ax2]:
                        xdata = event.xdata
                        vline1.set_xdata([xdata, xdata])
                        vline2.set_xdata([xdata, xdata])
                        vline1.set_visible(True)
                        vline2.set_visible(True)
                        fig.canvas.draw_idle()
                    else:
                        vline1.set_visible(False)
                        vline2.set_visible(False)
                        fig.canvas.draw_idle()
                
                fig.canvas.mpl_connect('motion_notify_event', on_mouse_move)
        except (ImportError, AttributeError):
            pass  # mplcursors不可用或后端不支持，跳过交互功能
    
    plt.tight_layout()
    
    if not interactive:
        fig.savefig(outfile, dpi=150, bbox_inches='tight', pad_inches=0.1)
        plt.close(fig)
        try:
            from utils.logger import logger
            logger.info(f"[plot_mean_reversion_signals] PNG文件生成成功: {outfile}")
        except Exception:
            pass
        return outfile
    else:
        plt.close(fig)
        try:
            from utils.logger import logger
            logger.warning("[plot_mean_reversion_signals] 非交互模式但未生成文件，返回空字符串")
        except Exception:
            pass
        return ""


