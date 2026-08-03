#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图表渲染诊断工具
用于检查mpld3图表在Streamlit环境下的渲染问题
"""

import sys
from typing import Dict, Tuple, List


def diagnose_html_rendering(html_str: str) -> Dict[str, Tuple[bool, str]]:
    """
    诊断HTML/JS渲染问题
    
    Args:
        html_str: mpld3生成的HTML字符串
        
    Returns:
        诊断结果字典
    """
    results = {}
    
    # 1. 检查HTML是否为空
    if not html_str or len(html_str.strip()) == 0:
        results['html_not_empty'] = (False, "HTML字符串为空")
        return results
    else:
        results['html_not_empty'] = (True, f"HTML长度: {len(html_str)} 字符")
    
    # 2. 检查是否是完整HTML文档
    html_lower = html_str.strip().lower()
    is_complete_html = html_lower.startswith('<!doctype') or html_lower.startswith('<html')
    results['is_complete_html'] = (is_complete_html, 
                                   "完整HTML文档" if is_complete_html else "HTML片段")
    
    # 3. 检查关键元素
    checks = {
        '包含mpld3': 'mpld3' in html_str.lower(),
        '包含d3.js': 'd3' in html_str.lower() or 'd3js' in html_str.lower(),
        '包含script标签': '<script' in html_str.lower(),
        '包含svg元素': '<svg' in html_str.lower(),
        '包含body标签': '<body' in html_str.lower() or not is_complete_html,
        '包含head标签': '<head' in html_str.lower() or not is_complete_html,
    }
    
    for key, value in checks.items():
        results[key] = (value, "✓" if value else "✗ 缺失")
    
    # 4. 检查CDN链接
    cdn_checks = {
        'd3 CDN': 'd3js.org' in html_str or 'cdn.jsdelivr.net/npm/d3' in html_str,
        'mpld3 CDN': 'mpld3.github.io' in html_str or 'cdn.jsdelivr.net/gh/mpld3' in html_str,
    }
    
    for key, value in cdn_checks.items():
        results[f'CDN_{key}'] = (value, "✓" if value else "✗ 缺失")
    
    # 5. 检查JavaScript代码
    script_count = html_str.lower().count('<script')
    results['script_tags'] = (script_count > 0, f"找到 {script_count} 个script标签")
    
    # 6. 检查是否有mpld3初始化代码
    has_mpld3_init = 'mpld3.draw_figure' in html_str or 'mpld3_load_lib' in html_str
    results['mpld3_init'] = (has_mpld3_init, "✓" if has_mpld3_init else "✗ 缺少mpld3初始化代码")
    
    return results


def diagnose_environment() -> Dict[str, Tuple[bool, str]]:
    """
    诊断环境问题
    
    Returns:
        环境诊断结果
    """
    results = {}
    
    # 1. 检查是否在Streamlit环境
    try:
        import streamlit as st
        results['streamlit_env'] = (True, "✓ 在Streamlit环境中")
    except ImportError:
        results['streamlit_env'] = (False, "✗ 不在Streamlit环境中")
    
    # 2. 检查mpld3是否安装
    try:
        import mpld3
        version = getattr(mpld3, '__version__', '未知')
        results['mpld3_installed'] = (True, f"✓ mpld3已安装 (版本: {version})")
    except ImportError:
        results['mpld3_installed'] = (False, "✗ mpld3未安装")
    
    # 3. 检查matplotlib后端
    try:
        import matplotlib
        backend = matplotlib.get_backend()
        results['matplotlib_backend'] = (True, f"✓ matplotlib后端: {backend}")
    except Exception as e:
        results['matplotlib_backend'] = (False, f"✗ matplotlib检查失败: {str(e)}")
    
    # 4. 检查components.html是否可用
    try:
        import streamlit.components.v1 as components
        results['components_html'] = (True, "✓ streamlit.components.v1可用")
    except Exception as e:
        results['components_html'] = (False, f"✗ components.html不可用: {str(e)}")
    
    return results


def diagnose_renderer_conflict() -> Dict[str, Tuple[bool, str]]:
    """
    诊断渲染器冲突问题
    
    Returns:
        渲染器冲突诊断结果
    """
    results = {}
    
    # 1. 检查是否有多个matplotlib后端设置
    try:
        import matplotlib
        backend = matplotlib.get_backend()
        # 检查是否有其他后端被设置
        results['backend_conflict'] = (backend == 'Agg' or backend.startswith('Tk'), 
                                      f"当前后端: {backend}")
    except Exception:
        results['backend_conflict'] = (False, "无法检查后端")
    
    # 2. 检查是否有其他图表库冲突
    conflicting_libs = ['plotly', 'bokeh', 'altair']
    for lib in conflicting_libs:
        try:
            __import__(lib)
            results[f'conflict_{lib}'] = (True, f"⚠ {lib}已安装，可能冲突")
        except ImportError:
            results[f'conflict_{lib}'] = (False, f"✓ {lib}未安装")
    
    return results


def run_full_diagnostic(html_str: str = None) -> Dict[str, Dict[str, Tuple[bool, str]]]:
    """
    运行完整的诊断
    
    Args:
        html_str: 可选的HTML字符串（如果提供，会进行HTML诊断）
        
    Returns:
        完整的诊断结果
    """
    results = {
        'environment': diagnose_environment(),
        'renderer_conflict': diagnose_renderer_conflict(),
    }
    
    if html_str:
        results['html_rendering'] = diagnose_html_rendering(html_str)
    
    return results


def print_diagnostic_report(results: Dict[str, Dict[str, Tuple[bool, str]]]):
    """
    打印诊断报告
    
    Args:
        results: 诊断结果
    """
    print("=" * 70)
    print("图表渲染诊断报告")
    print("=" * 70)
    
    for category, checks in results.items():
        print(f"\n【{category.upper()}】")
        print("-" * 70)
        
        passed = 0
        total = len(checks)
        
        for key, (status, message) in checks.items():
            status_symbol = "✓" if status else "✗"
            print(f"{status_symbol} {key}: {message}")
            if status:
                passed += 1
        
        print(f"\n通过率: {passed}/{total} ({passed*100//total if total > 0 else 0}%)")
    
    print("\n" + "=" * 70)


if __name__ == "__main__":
    # 测试诊断功能
    print("运行环境诊断...")
    results = run_full_diagnostic()
    print_diagnostic_report(results)

