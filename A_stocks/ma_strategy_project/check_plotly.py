#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检查Plotly安装状态
"""

import sys

def check_plotly():
    """检查Plotly是否已安装"""
    print("=" * 70)
    print("Plotly 安装状态检查")
    print("=" * 70)
    
    try:
        import plotly
        version = getattr(plotly, '__version__', '未知')
        print(f"✓ Plotly 已安装")
        print(f"  版本: {version}")
        
        # 检查关键模块
        try:
            import plotly.graph_objects as go
            print("✓ plotly.graph_objects 可用")
        except ImportError as e:
            print(f"✗ plotly.graph_objects 导入失败: {e}")
            return False
        
        try:
            from plotly.subplots import make_subplots
            print("✓ plotly.subplots 可用")
        except ImportError as e:
            print(f"✗ plotly.subplots 导入失败: {e}")
            return False
        
        # 测试基本功能
        try:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=[1, 2, 3], y=[1, 2, 3]))
            html = fig.to_html(include_plotlyjs='cdn')
            if html and len(html) > 100:
                print("✓ Plotly HTML生成功能正常")
            else:
                print("✗ Plotly HTML生成失败")
                return False
        except Exception as e:
            print(f"✗ Plotly功能测试失败: {e}")
            return False
        
        print("\n" + "=" * 70)
        print("✓ Plotly 安装完整，MR策略图表将使用Plotly渲染")
        print("=" * 70)
        return True
        
    except ImportError:
        print("✗ Plotly 未安装")
        print("\n安装方法：")
        print("  方法1: pip install plotly>=5.0.0")
        print("  方法2: pip install -r requirements.txt")
        print("  方法3: conda install -c conda-forge plotly")
        print("\n注意：")
        print("  - 如果未安装Plotly，MR策略图表将自动回退到mpld3")
        print("  - 其他功能（MA策略、权益曲线等）不受影响")
        print("\n" + "=" * 70)
        return False
    except Exception as e:
        print(f"✗ 检查过程中出错: {e}")
        print("\n" + "=" * 70)
        return False


if __name__ == "__main__":
    success = check_plotly()
    sys.exit(0 if success else 1)

