#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图表生成依赖健康检查工具
检查所有依赖的类和接口是否正常工作
"""

import sys
import traceback
from typing import Dict, List, Tuple, Any


def check_imports() -> Dict[str, Tuple[bool, str]]:
    """检查所有必需的导入"""
    results = {}
    
    # 基础库
    libraries = {
        'pandas': 'pd',
        'numpy': 'np',
        'matplotlib': None,
        'matplotlib.pyplot': 'plt',
        'streamlit': 'st',
        'streamlit.components.v1': 'components',
        'mpld3': None,
        'mpld3.plugins': None,
    }
    
    for lib_name, alias in libraries.items():
        try:
            if alias:
                exec(f"import {lib_name} as {alias}")
            else:
                exec(f"import {lib_name}")
            results[lib_name] = (True, "✓ 导入成功")
        except ImportError as e:
            results[lib_name] = (False, f"✗ 导入失败: {str(e)}")
        except Exception as e:
            results[lib_name] = (False, f"✗ 未知错误: {str(e)}")
    
    return results


def check_project_modules() -> Dict[str, Tuple[bool, str]]:
    """检查项目内部模块"""
    results = {}
    
    modules = [
        'data.fetcher',
        'strategies.mean_reversion',
        'strategies.moving_average',
        'strategies.base',
        'backtest.engine',
        'backtest.analyzer',
        'utils.visualization',
        'utils.logger',
    ]
    
    for module_name in modules:
        try:
            __import__(module_name)
            results[module_name] = (True, "✓ 模块导入成功")
        except ImportError as e:
            results[module_name] = (False, f"✗ 模块导入失败: {str(e)}")
        except Exception as e:
            results[module_name] = (False, f"✗ 未知错误: {str(e)}")
    
    return results


def check_classes() -> Dict[str, Tuple[bool, str]]:
    """检查关键类是否可用"""
    results = {}
    
    try:
        from strategies.mean_reversion import MeanReversionStrategy
        results['MeanReversionStrategy'] = (True, "✓ 类可用")
        
        # 测试实例化
        try:
            strategy = MeanReversionStrategy()
            results['MeanReversionStrategy.__init__'] = (True, "✓ 实例化成功")
        except Exception as e:
            results['MeanReversionStrategy.__init__'] = (False, f"✗ 实例化失败: {str(e)}")
    except Exception as e:
        results['MeanReversionStrategy'] = (False, f"✗ 类不可用: {str(e)}")
    
    try:
        from backtest.engine import BacktestEngine
        results['BacktestEngine'] = (True, "✓ 类可用")
    except Exception as e:
        results['BacktestEngine'] = (False, f"✗ 类不可用: {str(e)}")
    
    try:
        from utils.visualization import (
            plot_mean_reversion_signals,
            plot_equity_curve,
            plot_price_ma_signals,
            _get_tooltip_text,
            _is_streamlit_env,
        )
        results['plot_mean_reversion_signals'] = (True, "✓ 函数可用")
        results['plot_equity_curve'] = (True, "✓ 函数可用")
        results['plot_price_ma_signals'] = (True, "✓ 函数可用")
        results['_get_tooltip_text'] = (True, "✓ 函数可用")
        results['_is_streamlit_env'] = (True, "✓ 函数可用")
    except Exception as e:
        results['visualization_functions'] = (False, f"✗ 函数导入失败: {str(e)}")
    
    # 检查 VLinePlugin
    try:
        from utils.visualization import VLinePlugin
        if VLinePlugin is not None:
            results['VLinePlugin'] = (True, "✓ 插件可用")
        else:
            results['VLinePlugin'] = (False, "⚠ 插件不可用（mpld3可能未安装）")
    except Exception as e:
        results['VLinePlugin'] = (False, f"✗ 插件检查失败: {str(e)}")
    
    return results


def check_function_signatures() -> Dict[str, Tuple[bool, str]]:
    """检查函数签名是否正确"""
    results = {}
    
    try:
        from utils.visualization import plot_mean_reversion_signals
        import inspect
        
        sig = inspect.signature(plot_mean_reversion_signals)
        params = list(sig.parameters.keys())
        
        required_params = ['data', 'outfile', 'entry_z', 'exit_z', 'interactive']
        missing_params = [p for p in required_params if p not in params]
        
        if missing_params:
            results['plot_mean_reversion_signals_signature'] = (
                False, 
                f"✗ 缺少参数: {missing_params}"
            )
        else:
            results['plot_mean_reversion_signals_signature'] = (
                True, 
                f"✓ 签名完整: {params}"
            )
    except Exception as e:
        results['plot_mean_reversion_signals_signature'] = (
            False, 
            f"✗ 检查失败: {str(e)}"
        )
    
    return results


def check_data_flow() -> Dict[str, Tuple[bool, str]]:
    """检查数据流是否正确"""
    results = {}
    
    try:
        import pandas as pd
        import numpy as np
        from strategies.mean_reversion import MeanReversionStrategy
        
        # 创建测试数据
        dates = pd.date_range('2024-01-01', periods=50, freq='D')
        test_data = pd.DataFrame({
            'date': dates,
            'open': np.random.uniform(10, 20, 50),
            'high': np.random.uniform(15, 25, 50),
            'low': np.random.uniform(8, 15, 50),
            'close': np.random.uniform(10, 20, 50),
            'volume': np.random.uniform(1000000, 5000000, 50),
        })
        
        # 测试策略生成信号
        try:
            strategy = MeanReversionStrategy(window=20, entry_z=2.0, exit_z=0.0)
            sig_df = strategy.generate_signals(test_data)
            
            # 检查必要的列
            required_cols = ['close', 'mr_mean', 'mr_std', 'z', 'signal', 'positions']
            missing_cols = [col for col in required_cols if col not in sig_df.columns]
            
            if missing_cols:
                results['strategy_generate_signals'] = (
                    False, 
                    f"✗ 缺少列: {missing_cols}"
                )
            else:
                results['strategy_generate_signals'] = (
                    True, 
                    f"✓ 信号生成成功，数据形状: {sig_df.shape}"
                )
            
            # 测试图表生成函数（非交互模式）
            try:
                from utils.visualization import plot_mean_reversion_signals
                
                # 检查数据是否有效
                if not sig_df.empty and all(col in sig_df.columns for col in ['close', 'mr_mean', 'mr_std', 'z']):
                    # 尝试生成图表（非交互模式，避免需要mpld3）
                    result = plot_mean_reversion_signals(
                        sig_df, 
                        entry_z=2.0, 
                        exit_z=0.0,
                        interactive=False
                    )
                    
                    if result:
                        results['plot_function_execution'] = (
                            True, 
                            f"✓ 图表生成成功: {result}"
                        )
                    else:
                        results['plot_function_execution'] = (
                            False, 
                            "✗ 图表生成返回空结果"
                        )
                else:
                    results['plot_function_execution'] = (
                        False, 
                        "✗ 数据不完整，无法生成图表"
                    )
            except Exception as e:
                results['plot_function_execution'] = (
                    False, 
                    f"✗ 图表生成失败: {str(e)}\n{traceback.format_exc()}"
                )
                
        except Exception as e:
            results['strategy_generate_signals'] = (
                False, 
                f"✗ 信号生成失败: {str(e)}\n{traceback.format_exc()}"
            )
            
    except Exception as e:
        results['data_flow_test'] = (
            False, 
            f"✗ 数据流测试失败: {str(e)}\n{traceback.format_exc()}"
        )
    
    return results


def check_mpld3_availability() -> Dict[str, Tuple[bool, str]]:
    """检查mpld3是否可用"""
    results = {}
    
    try:
        import mpld3
        from mpld3 import plugins
        
        results['mpld3_import'] = (True, f"✓ mpld3版本: {mpld3.__version__ if hasattr(mpld3, '__version__') else '未知'}")
        
        # 测试基本功能
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            
            fig, ax = plt.subplots()
            ax.plot([1, 2, 3], [1, 2, 3])
            
            html = mpld3.fig_to_html(fig)
            if html and len(html) > 0:
                results['mpld3_html_generation'] = (True, f"✓ HTML生成成功，长度: {len(html)}")
            else:
                results['mpld3_html_generation'] = (False, "✗ HTML生成失败")
            
            plt.close(fig)
        except Exception as e:
            results['mpld3_html_generation'] = (False, f"✗ HTML生成测试失败: {str(e)}")
        
    except ImportError:
        results['mpld3_import'] = (False, "✗ mpld3未安装")
    except Exception as e:
        results['mpld3_import'] = (False, f"✗ mpld3检查失败: {str(e)}")
    
    return results


def run_full_health_check() -> Dict[str, Dict[str, Tuple[bool, str]]]:
    """运行完整的健康检查"""
    print("=" * 70)
    print("图表生成依赖健康检查")
    print("=" * 70)
    
    all_results = {
        'imports': check_imports(),
        'project_modules': check_project_modules(),
        'classes': check_classes(),
        'function_signatures': check_function_signatures(),
        'data_flow': check_data_flow(),
        'mpld3': check_mpld3_availability(),
    }
    
    return all_results


def print_results(results: Dict[str, Dict[str, Tuple[bool, str]]]):
    """打印检查结果"""
    total_checks = 0
    passed_checks = 0
    failed_checks = 0
    
    for category, checks in results.items():
        print(f"\n【{category.upper()}】")
        print("-" * 70)
        
        for name, (status, message) in checks.items():
            total_checks += 1
            if status:
                passed_checks += 1
                status_symbol = "✓"
            else:
                failed_checks += 1
                status_symbol = "✗"
            
            print(f"{status_symbol} {name}: {message}")
    
    print("\n" + "=" * 70)
    print(f"总计: {total_checks} 项检查")
    print(f"通过: {passed_checks} 项")
    print(f"失败: {failed_checks} 项")
    print(f"通过率: {passed_checks/total_checks*100:.1f}%")
    print("=" * 70)
    
    if failed_checks > 0:
        print("\n⚠️  发现问题，请检查上述失败项")
        return False
    else:
        print("\n✓ 所有检查通过！")
        return True


if __name__ == "__main__":
    results = run_full_health_check()
    success = print_results(results)
    sys.exit(0 if success else 1)

