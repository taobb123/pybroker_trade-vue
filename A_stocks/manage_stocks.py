#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票数据管理系统
提供查询、统计、导出功能，支持沪深300、委托、持仓三张表
"""

import pymysql
import sys
import csv
from datetime import datetime
from db_config import DB_CONFIG
import pandas as pd


class StockManager:
    """股票数据管理器"""
    
    def __init__(self):
        self.connection = None
        self.connect()
    
    def connect(self):
        """连接数据库"""
        try:
            self.connection = pymysql.connect(
                host=DB_CONFIG['host'],
                port=DB_CONFIG['port'],
                user=DB_CONFIG['user'],
                password=DB_CONFIG['password'],
                database=DB_CONFIG['database'],
                charset=DB_CONFIG['charset'],
                cursorclass=pymysql.cursors.DictCursor
            )
            return True
        except Exception as e:
            print(f"✗ 数据库连接失败: {e}")
            return False
    
    def close(self):
        """关闭连接"""
        if self.connection:
            self.connection.close()
    
    # ==================== 沪深300成分股查询 ====================
    
    def query_stock_by_code(self, code):
        """按股票代码查询"""
        try:
            with self.connection.cursor() as cursor:
                cursor.execute("SELECT * FROM csi300_stocks WHERE code = %s", (code,))
                return cursor.fetchall()
        except Exception as e:
            print(f"查询失败: {e}")
            return []
    
    def query_stock_by_name(self, name):
        """按股票名称模糊查询"""
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    "SELECT code, name, current_price, change_percent, industry FROM csi300_stocks WHERE name LIKE %s",
                    (f'%{name}%',)
                )
                return cursor.fetchall()
        except Exception as e:
            print(f"查询失败: {e}")
            return []
    
    def query_stock_by_industry(self, industry):
        """按行业查询"""
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    "SELECT code, name, current_price, change_percent, industry FROM csi300_stocks WHERE industry = %s",
                    (industry,)
                )
                return cursor.fetchall()
        except Exception as e:
            print(f"查询失败: {e}")
            return []
    
    def query_top_gainers(self, n=10):
        """查询涨幅榜（前N名）"""
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """SELECT code, name, change_percent, industry, 
                              change_5days, change_10days, change_20days
                       FROM csi300_stocks 
                       WHERE change_percent IS NOT NULL
                       ORDER BY change_percent DESC 
                       LIMIT %s""",
                    (n,)
                )
                return cursor.fetchall()
        except Exception as e:
            print(f"查询失败: {e}")
            return []
    
    def query_top_losers(self, n=10):
        """查询跌幅榜（前N名）"""
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """SELECT code, name, change_percent, industry, 
                              change_5days, change_10days, change_20days
                       FROM csi300_stocks 
                       WHERE change_percent IS NOT NULL
                       ORDER BY change_percent ASC 
                       LIMIT %s""",
                    (n,)
                )
                return cursor.fetchall()
        except Exception as e:
            print(f"查询失败: {e}")
            return []
    
    def query_by_price_range(self, min_price, max_price):
        """按价格范围查询"""
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """SELECT code, name, current_price, change_percent, industry
                       FROM csi300_stocks 
                       WHERE current_price BETWEEN %s AND %s
                       ORDER BY current_price DESC""",
                    (min_price, max_price)
                )
                return cursor.fetchall()
        except Exception as e:
            print(f"查询失败: {e}")
            return []
    
    def query_all_stocks(self):
        """查询所有记录，按总市值升序排列（从小到大）"""
        try:
            with self.connection.cursor() as cursor:
                cursor.execute("SELECT * FROM csi300_stocks ORDER BY total_market_value ASC")
                return cursor.fetchall()
        except Exception as e:
            print(f"查询失败: {e}")
            return []
    
    def query_with_filters(self, name=None, industry=None, min_price=None, max_price=None):
        """多条件组合查询
        
        Args:
            name: 股票名称（模糊匹配）
            industry: 行业名称（精确匹配）
            min_price: 最低价格
            max_price: 最高价格
        
        Returns:
            查询结果列表
        """
        try:
            conditions = []
            params = []
            
            if name:
                conditions.append("name LIKE %s")
                params.append(f'%{name}%')
            
            if industry:
                conditions.append("industry = %s")
                params.append(industry)
            
            if min_price is not None:
                conditions.append("current_price >= %s")
                params.append(min_price)
            
            if max_price is not None:
                conditions.append("current_price <= %s")
                params.append(max_price)
            
            if not conditions:
                # 如果没有条件，返回所有记录
                return self.query_all_stocks()
            
            # 按总市值升序排列（从小到大，格式化后可以正确显示）
            sql = "SELECT * FROM csi300_stocks WHERE " + " AND ".join(conditions) + " ORDER BY total_market_value ASC"
            
            with self.connection.cursor() as cursor:
                cursor.execute(sql, params)
                return cursor.fetchall()
        except Exception as e:
            print(f"查询失败: {e}")
            return []
    
    # ==================== 沪深300成分股统计 ====================
    
    def get_total_stock_count(self):
        """获取总记录数"""
        try:
            with self.connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) as count FROM csi300_stocks")
                return cursor.fetchone()['count']
        except Exception as e:
            print(f"统计失败: {e}")
            return 0
    
    def get_industry_distribution(self):
        """统计行业分布"""
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """SELECT industry, COUNT(*) as count 
                       FROM csi300_stocks 
                       WHERE industry IS NOT NULL
                       GROUP BY industry 
                       ORDER BY count DESC"""
                )
                return cursor.fetchall()
        except Exception as e:
            print(f"统计失败: {e}")
            return []
    
    def get_change_statistics(self):
        """统计涨跌幅信息"""
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """SELECT 
                           COUNT(*) as total,
                           AVG(change_percent) as avg_change,
                           MAX(change_percent) as max_change,
                           MIN(change_percent) as min_change,
                           SUM(CASE WHEN change_percent > 0 THEN 1 ELSE 0 END) as gainers,
                           SUM(CASE WHEN change_percent < 0 THEN 1 ELSE 0 END) as losers
                       FROM csi300_stocks
                       WHERE change_percent IS NOT NULL"""
                )
                return cursor.fetchone()
        except Exception as e:
            print(f"统计失败: {e}")
            return None
    
    # ==================== 委托表查询 ====================
    
    def query_all_orders(self):
        """查询所有委托记录（按时间排序）"""
        try:
            with self.connection.cursor() as cursor:
                cursor.execute("""
                    SELECT order_time, symbol, name, side, order_qty, order_price, 
                           order_status, filled_qty, filled_amount, filled_avg_price
                    FROM orders_intraday
                    ORDER BY order_time DESC
                """)
                return cursor.fetchall()
        except Exception as e:
            print(f"查询失败: {e}")
            return []
    
    def query_orders_by_symbol(self, symbol):
        """按证券代码查询委托"""
        try:
            with self.connection.cursor() as cursor:
                cursor.execute("""
                    SELECT order_time, symbol, name, side, order_qty, order_price, 
                           order_status, filled_qty, filled_amount, filled_avg_price
                    FROM orders_intraday
                    WHERE symbol = %s
                    ORDER BY order_time DESC
                """, (symbol,))
                return cursor.fetchall()
        except Exception as e:
            print(f"查询失败: {e}")
            return []
    
    def query_orders_by_status(self, status):
        """按委托状态查询"""
        try:
            with self.connection.cursor() as cursor:
                cursor.execute("""
                    SELECT order_time, symbol, name, side, order_qty, order_price, 
                           order_status, filled_qty, filled_amount, filled_avg_price
                    FROM orders_intraday
                    WHERE order_status = %s
                    ORDER BY order_time DESC
                """, (status,))
                return cursor.fetchall()
        except Exception as e:
            print(f"查询失败: {e}")
            return []
    
    # ==================== 委托表统计 ====================
    
    def get_orders_statistics(self):
        """统计委托信息"""
        try:
            with self.connection.cursor() as cursor:
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total,
                        COUNT(CASE WHEN order_status = '已成' THEN 1 END) as filled,
                        COUNT(CASE WHEN order_status = '已撤' THEN 1 END) as cancelled,
                        COUNT(CASE WHEN side = '证券买入' THEN 1 END) as buy,
                        COUNT(CASE WHEN side = '证券卖出' THEN 1 END) as sell,
                        SUM(CASE WHEN order_status = '已成' THEN filled_amount ELSE 0 END) as total_amount
                    FROM orders_intraday
                """)
                return cursor.fetchone()
        except Exception as e:
            print(f"统计失败: {e}")
            return None
    
    # ==================== 持仓表查询 ====================
    
    def query_all_positions(self):
        """查询所有持仓（按盈亏率排序）"""
        try:
            with self.connection.cursor() as cursor:
                cursor.execute("""
                    SELECT symbol, name, quantity, cost_price, last_price, 
                           pnl_pct, pnl, today_pnl_pct, today_pnl, market_value
                    FROM positions_intraday
                    ORDER BY pnl_pct DESC
                """)
                return cursor.fetchall()
        except Exception as e:
            print(f"查询失败: {e}")
            return []
    
    def query_positions_by_symbol(self, symbol):
        """按证券代码查询持仓"""
        try:
            with self.connection.cursor() as cursor:
                cursor.execute("""
                    SELECT symbol, name, quantity, cost_price, last_price, 
                           pnl_pct, pnl, today_pnl_pct, today_pnl, market_value
                    FROM positions_intraday
                    WHERE symbol = %s
                """, (symbol,))
                return cursor.fetchall()
        except Exception as e:
            print(f"查询失败: {e}")
            return []
    
    def query_profitable_positions(self):
        """查询盈利持仓"""
        try:
            with self.connection.cursor() as cursor:
                cursor.execute("""
                    SELECT symbol, name, quantity, cost_price, last_price, 
                           pnl_pct, pnl, today_pnl_pct, today_pnl, market_value
                    FROM positions_intraday
                    WHERE pnl > 0
                    ORDER BY pnl_pct DESC
                """)
                return cursor.fetchall()
        except Exception as e:
            print(f"查询失败: {e}")
            return []
    
    def query_losing_positions(self):
        """查询亏损持仓"""
        try:
            with self.connection.cursor() as cursor:
                cursor.execute("""
                    SELECT symbol, name, quantity, cost_price, last_price, 
                           pnl_pct, pnl, today_pnl_pct, today_pnl, market_value
                    FROM positions_intraday
                    WHERE pnl < 0
                    ORDER BY pnl_pct ASC
                """)
                return cursor.fetchall()
        except Exception as e:
            print(f"查询失败: {e}")
            return []
    
    # ==================== 持仓表统计 ====================
    
    def get_positions_statistics(self):
        """统计持仓信息"""
        try:
            with self.connection.cursor() as cursor:
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total,
                        SUM(pnl) as total_pnl,
                        AVG(pnl_pct) as avg_pnl_pct,
                        SUM(market_value) as total_market_value,
                        SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as profitable,
                        SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losing
                    FROM positions_intraday
                """)
                return cursor.fetchone()
        except Exception as e:
            print(f"统计失败: {e}")
            return None
    
    # ==================== 潜力股和超跌股分析模块 ====================
    
    def get_top_gainers_industries(self, n=3):
        """获取涨幅榜前N名的行业列表（去重）"""
        try:
            with self.connection.cursor() as cursor:
                cursor.execute("""
                    SELECT DISTINCT industry 
                    FROM csi300_stocks 
                    WHERE change_percent IS NOT NULL 
                      AND industry IS NOT NULL
                      AND industry != ''
                    ORDER BY (
                        SELECT MAX(change_percent) 
                        FROM csi300_stocks as t2 
                        WHERE t2.industry = csi300_stocks.industry
                    ) DESC
                    LIMIT %s
                """, (n,))
                industries = [row['industry'] for row in cursor.fetchall()]
                return industries
        except Exception as e:
            print(f"查询失败: {e}")
            return []

    def get_top_losers_industries(self, n=3):
        """获取跌幅榜前N名的行业列表（去重）"""
        try:
            with self.connection.cursor() as cursor:
                cursor.execute("""
                    SELECT DISTINCT industry 
                    FROM csi300_stocks 
                    WHERE change_percent IS NOT NULL 
                      AND industry IS NOT NULL
                      AND industry != ''
                    ORDER BY (
                        SELECT MIN(change_percent) 
                        FROM csi300_stocks as t2 
                        WHERE t2.industry = csi300_stocks.industry
                    ) ASC
                    LIMIT %s
                """, (n,))
                industries = [row['industry'] for row in cursor.fetchall()]
                return industries
        except Exception as e:
            print(f"查询失败: {e}")
            return []
    
    def query_stocks_by_industries_and_filter(self, industries, min_gain=1.0, max_loss=-3.0):
        """按行业查询并筛选个股
        
        Args:
            industries: 行业列表
            min_gain: 潜力股最低涨幅（默认1%）
            max_loss: 超跌股最低跌幅（默认-3%）
            
        Returns:
            dict: {'potential': 潜力股列表, 'oversold': 超跌股列表}
        """
        if not industries:
            return {'potential': [], 'oversold': []}
        
        try:
            # 构建IN子句
            placeholders = ','.join(['%s'] * len(industries))
            
            with self.connection.cursor() as cursor:
                # 查询潜力股（涨幅>=min_gain）
                cursor.execute(f"""
                    SELECT code, name, industry, current_price, change_percent,
                           change_5days, change_10days, change_20days
                    FROM csi300_stocks 
                    WHERE industry IN ({placeholders})
                      AND change_percent >= %s
                      AND change_percent IS NOT NULL
                    ORDER BY change_percent DESC
                    LIMIT 10
                """, industries + [min_gain])
                potential = cursor.fetchall()
                
                # 查询超跌股（跌幅<=max_loss）
                cursor.execute(f"""
                    SELECT code, name, industry, current_price, change_percent,
                           change_5days, change_10days, change_20days
                    FROM csi300_stocks 
                    WHERE industry IN ({placeholders})
                      AND change_percent <= %s
                      AND change_percent IS NOT NULL
                    ORDER BY change_percent ASC
                    LIMIT 10
                """, industries + [max_loss])
                oversold = cursor.fetchall()
                
                return {'potential': potential, 'oversold': oversold}
        except Exception as e:
            print(f"查询失败: {e}")
            return {'potential': [], 'oversold': []}
    
    def get_potential_and_oversold_stocks(self, min_gain=1.0, max_loss=-3.0, reverse_mode=False):
        """统计潜力股和超跌股（优化逻辑）
        
        Args:
            min_gain: 潜力股最低涨幅（默认1%）
            max_loss: 超跌股最低跌幅（默认-3%）
            reverse_mode: 是否使用反向指标（默认False）
                - False（正向）: 选出数量最多的行业（并列全选）
                - True（反向）: 排除数量最多的行业，选择数量少的行业
        
        Returns:
            - 从涨幅榜前3提取行业，统计各行业中涨幅>=min_gain的个股数量
            - 从跌幅榜前3提取行业，统计各行业中跌幅<=max_loss的个股数量
            - 根据reverse_mode参数选择/排除数量最多的行业
            - 各入选行业内，返回前10条记录（潜力股按涨幅降序、超跌股按涨跌幅升序）
            - 返回同时包含跌幅榜前3名数据用于显示
        """
        try:
            # 涨幅榜前三（仅用于行业选择）
            top_gainers = self.query_top_gainers(3)
            gain_industries_raw = [r.get('industry') for r in top_gainers if r.get('industry')]
            gain_industries = []
            for ind in gain_industries_raw:
                if ind not in gain_industries:
                    gain_industries.append(ind)

            # 跌幅榜前三（同时用于展示+行业选择）
            top_losers = self.query_top_losers(3)
            loss_industries_raw = [r.get('industry') for r in top_losers if r.get('industry')]
            loss_industries = []
            for ind in loss_industries_raw:
                if ind not in loss_industries:
                    loss_industries.append(ind)

            # 统计各自行业中满足条件的数量，选出/排除数量最多的行业
            def pick_top_industries_by_condition(industries, condition_sql, condition_param, reverse=False):
                if not industries:
                    return []
                counts = []
                with self.connection.cursor() as cursor:
                    for ind in industries:
                        cursor.execute(
                            f"""
                            SELECT COUNT(*) as c
                            FROM csi300_stocks
                            WHERE industry = %s AND {condition_sql}
                            """,
                            (ind, condition_param),
                        )
                        c = cursor.fetchone()['c']
                        counts.append((ind, c))
                if not counts:
                    return []
                
                max_c = max(c for _, c in counts)
                
                if reverse:
                    # 反向模式：排除数量最多的行业，选择数量少的行业
                    # 如果有多个行业的数量相同且都是最多，则排除所有数量最多的
                    result = [ind for ind, c in counts if c < max_c and c > 0]
                    # 如果排除后没有剩下任何行业，则至少保留一个有数据的行业（选择数量最少的）
                    if not result:
                        min_c = min(c for _, c in counts if c > 0)
                        if min_c > 0:
                            result = [ind for ind, c in counts if c == min_c]
                else:
                    # 正向模式：选择数量最多的行业（并列全选）
                    result = [ind for ind, c in counts if c == max_c and c > 0]
                
                return result

            gain_selected_industries = pick_top_industries_by_condition(
                gain_industries, "change_percent >= %s", min_gain, reverse_mode
            )
            loss_selected_industries = pick_top_industries_by_condition(
                loss_industries, "change_percent <= %s", max_loss, reverse_mode
            )

            # 查询分行业TOP10列表，并计算总数与占比
            def fetch_grouped(industries, condition_sql, condition_param, order_sql, limit=10):
                groups = {}
                total = 0
                with self.connection.cursor() as cursor:
                    for ind in industries:
                        cursor.execute(
                            f"""
                            SELECT code, name, industry, current_price, change_percent,
                                   change_5days, change_10days, change_20days
                            FROM csi300_stocks
                            WHERE industry = %s AND {condition_sql}
                            ORDER BY {order_sql}
                            LIMIT %s
                            """,
                            (ind, condition_param, limit),
                        )
                        rows = cursor.fetchall()
                        groups[ind] = rows
                        total += len(rows)
                # 计算占比（相对本类别总数）
                distribution = []
                for ind, rows in groups.items():
                    cnt = len(rows)
                    pct = (cnt / total * 100) if total > 0 else 0
                    distribution.append({
                        'industry': ind,
                        'count': cnt,
                        'ratio_percent': round(pct, 2),
                    })
                # 排序方便展示
                distribution.sort(key=lambda x: (-x['count'], x['industry']))
                return groups, total, distribution

            potential_groups, potential_total, potential_dist = fetch_grouped(
                gain_selected_industries, "change_percent >= %s", min_gain, "change_percent DESC"
            )
            oversold_groups, oversold_total, oversold_dist = fetch_grouped(
                loss_selected_industries, "change_percent <= %s", max_loss, "change_percent ASC"
            )

            return {
                'top_gainers': top_gainers,  # 用于展示涨幅榜前三
                'top_losers': top_losers,  # 用于展示跌幅榜前三
                'gain_selected_industries': gain_selected_industries,
                'loss_selected_industries': loss_selected_industries,
                'potential_groups': potential_groups,  # dict[industry] = list[stocks]
                'oversold_groups': oversold_groups,    # dict[industry] = list[stocks]
                'potential_total': potential_total,
                'oversold_total': oversold_total,
                'potential_distribution': potential_dist,  # list[{industry,count,ratio_percent}]
                'oversold_distribution': oversold_dist,
            }
        except Exception as e:
            print(f"分析失败: {e}")
            return None
    
    # ==================== 导出模块 ====================
    
    def export_to_csv(self, data, filename=None):
        """导出数据到CSV文件"""
        if not data:
            print("没有数据可导出")
            return False
        
        if filename is None:
            filename = f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        try:
            with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
                if data:
                    fieldnames = data[0].keys()
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(data)
            
            print(f"✓ 数据已导出到: {filename}")
            print(f"✓ 共导出 {len(data)} 条记录")
            return True
        except Exception as e:
            print(f"导出失败: {e}")
            return False


def print_menu():
    """打印主菜单"""
    print("\n" + "=" * 70)
    print("股票数据管理系统")
    print("=" * 70)
    print("【沪深300成分股查询】")
    print("  1. 按股票代码查询")
    print("  2. 按股票名称查询（模糊）")
    print("  3. 按行业查询")
    print("  4. 查询涨幅榜")
    print("  5. 查询跌幅榜")
    print("  6. 按价格范围查询")
    print("  7. 查询所有记录")
    print("\n【沪深300成分股统计】")
    print("  8. 统计总记录数")
    print("  9. 统计行业分布")
    print("  10. 统计涨跌幅信息")
    print("\n【委托查询】")
    print("  11. 查询所有委托记录")
    print("  12. 按证券代码查询委托")
    print("  13. 按委托状态查询")
    print("\n【委托统计】")
    print("  14. 委托统计信息")
    print("\n【持仓查询】")
    print("  15. 查询所有持仓")
    print("  16. 按证券代码查询持仓")
    print("  17. 查询盈利持仓")
    print("  18. 查询亏损持仓")
    print("\n【持仓统计】")
    print("  19. 持仓统计信息")
    print("\n【导入功能】")
    print("  20. 导入委托和持仓数据")
    print("  21. 导入/更新沪深300成分股数据（清空重建）")
    print("\n【潜力股和超跌股分析】")
    print("  22. 分析潜力股和超跌股（正向指标：选择数量最多的行业）")
    print("  23. 分析潜力股和超跌股（反向指标：排除数量最多的行业）")
    print("\n  0. 退出")
    print("=" * 70)


def handle_stock_query(manager, choice):
    """处理沪深300成分股查询"""
    if choice == '1':
        code = input("请输入股票代码（如：SZ300308）: ").strip()
        results = manager.query_stock_by_code(code)
        display_results(results)
        export_prompt(manager, results)
        
    elif choice == '2':
        name = input("请输入股票名称（支持模糊查询）: ").strip()
        results = manager.query_stock_by_name(name)
        display_results(results)
        export_prompt(manager, results)
        
    elif choice == '3':
        industry = input("请输入行业名称: ").strip()
        results = manager.query_stock_by_industry(industry)
        display_results(results)
        export_prompt(manager, results)
        
    elif choice == '4':
        n = input("显示前几名？（默认10）: ").strip()
        n = int(n) if n.isdigit() else 10
        results = manager.query_top_gainers(n)
        print(f"\n涨幅榜 TOP {len(results)}")
        display_results(results)
        export_prompt(manager, results)
        
    elif choice == '5':
        n = input("显示前几名？（默认10）: ").strip()
        n = int(n) if n.isdigit() else 10
        results = manager.query_top_losers(n)
        print(f"\n跌幅榜 TOP {len(results)}")
        display_results(results)
        export_prompt(manager, results)
        
    elif choice == '6':
        try:
            min_price = float(input("最低价格: "))
            max_price = float(input("最高价格: "))
            results = manager.query_by_price_range(min_price, max_price)
            display_results(results)
            export_prompt(manager, results)
        except ValueError:
            print("价格输入错误")
            
    elif choice == '7':
        results = manager.query_all_stocks()
        display_results(results)
        export_prompt(manager, results)


def handle_stock_statistics(manager, choice):
    """处理沪深300成分股统计"""
    if choice == '8':
        count = manager.get_total_stock_count()
        print(f"\n数据库中共有 {count} 条记录")
        
    elif choice == '9':
        results = manager.get_industry_distribution()
        print("\n行业分布统计:")
        print("-" * 70)
        for row in results:
            print(f"{row['industry']:20s}: {row['count']:3d} 只股票")
        print("-" * 70)
        export_prompt(manager, results)
        
    elif choice == '10':
        stats = manager.get_change_statistics()
        if stats:
            print("\n涨跌幅统计:")
            print("-" * 70)
            print(f"总股票数: {stats['total']}")
            print(f"平均涨跌幅: {stats['avg_change']:.2f}%")
            print(f"最大涨幅: {stats['max_change']:.2f}%")
            print(f"最大跌幅: {stats['min_change']:.2f}%")
            print(f"上涨股票数: {stats['gainers']}")
            print(f"下跌股票数: {stats['losers']}")
            print("-" * 70)


def handle_order_query(manager, choice):
    """处理委托查询"""
    if choice == '11':
        results = manager.query_all_orders()
        print("\n所有委托记录（按时间倒序）:")
        display_results(results)
        export_prompt(manager, results)
        
    elif choice == '12':
        symbol = input("请输入证券代码: ").strip()
        results = manager.query_orders_by_symbol(symbol)
        display_results(results)
        export_prompt(manager, results)
        
    elif choice == '13':
        status = input("请输入委托状态（已成/已撤/已报等）: ").strip()
        results = manager.query_orders_by_status(status)
        display_results(results)
        export_prompt(manager, results)


def handle_order_statistics(manager, choice):
    """处理委托统计"""
    if choice == '14':
        stats = manager.get_orders_statistics()
        if stats:
            print("\n委托统计信息:")
            print("-" * 70)
            print(f"总委托数: {stats['total']}")
            print(f"已成交: {stats['filled']}")
            print(f"已撤单: {stats['cancelled']}")
            print(f"买入委托: {stats['buy']}")
            print(f"卖出委托: {stats['sell']}")
            print(f"成交总金额: {stats['total_amount']:,.2f}")
            print("-" * 70)


def handle_position_query(manager, choice):
    """处理持仓查询"""
    if choice == '15':
        results = manager.query_all_positions()
        print("\n所有持仓记录（按盈亏率排序）:")
        display_results(results)
        export_prompt(manager, results)
        
    elif choice == '16':
        symbol = input("请输入证券代码: ").strip()
        results = manager.query_positions_by_symbol(symbol)
        display_results(results)
        export_prompt(manager, results)
        
    elif choice == '17':
        results = manager.query_profitable_positions()
        print("\n盈利持仓:")
        display_results(results)
        export_prompt(manager, results)
        
    elif choice == '18':
        results = manager.query_losing_positions()
        print("\n亏损持仓:")
        display_results(results)
        export_prompt(manager, results)


def handle_position_statistics(manager, choice):
    """处理持仓统计"""
    if choice == '19':
        stats = manager.get_positions_statistics()
        if stats:
            print("\n持仓统计信息:")
            print("-" * 70)
            print(f"持仓总数: {stats['total']}")
            print(f"总盈亏: {stats['total_pnl']:,.2f}")
            print(f"平均盈亏率: {stats['avg_pnl_pct']:.2f}%")
            print(f"总市值: {stats['total_market_value']:,.2f}")
            print(f"盈利持仓: {stats['profitable']}")
            print(f"亏损持仓: {stats['losing']}")
            print("-" * 70)


def handle_import(manager, choice):
    """处理导入操作"""
    if choice == '20':
        print("\n导入委托和持仓数据...")
        print("需要导入的文件:")
        print("  - 当日委托.xls")
        print("  - 资金持仓.xls")
        
        confirm = input("\n确认开始导入？(y/n): ").strip().lower()
        if confirm == 'y':
            try:
                import subprocess
                import locale
                # 使用系统首选编码读取子进程输出，避免在 Windows 上因 UTF-8/GBK 不一致导致解码异常
                preferred_enc = locale.getpreferredencoding(False) or 'utf-8'
                result = subprocess.run(
                    ['python', 'import_orders_positions.py'],
                    capture_output=True,
                    text=True,
                    encoding=preferred_enc,
                    errors='replace',
                )
                print(result.stdout)
                if result.returncode == 0:
                    print("\n✓ 导入完成！")
                else:
                    print("\n✗ 导入失败")
                    print(result.stderr)
            except Exception as e:
                print(f"✗ 导入过程出错: {e}")
        else:
            print("取消导入")

    elif choice == '21':
        print("\n导入/更新沪深300成分股数据（清空重建）...")
        confirm = input("确认从本地文件 ‘沪深300.xls’ 导入并清空重建表吗？(y/n): ").strip().lower()
        if confirm != 'y':
            print("已取消")
            return

        try:
            # 1) 读取文件
            print("\n[1/4] 读取文件...")
            try:
                df = pd.read_csv('沪深300.xls', sep='\t', encoding='gbk')
            except Exception:
                try:
                    df = pd.read_csv('沪深300.xls', sep='\t', encoding='gb2312')
                except Exception:
                    df = pd.read_csv('沪深300.xls', sep='\t', encoding='utf-8')
            print(f"✓ 文件读取成功，共 {len(df)} 条记录")

            # 2) 清洗映射
            print("\n[2/4] 处理数据...")
            def fmt_percent(v):
                if pd.isna(v) or v == '':
                    return None
                # 先转字符串，保留负号
                s = str(v).strip()
                # 移除百分号
                s = s.replace('%', '')
                # 移除正号（保留负号）
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

            print(f"✓ 已处理 {len(records)} 条记录")

            # 3) 清空表并插入
            print("\n[3/4] 更新数据库...")
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
                manager.connection.commit()
            print(f"✓ 成功插入 {affected} 条记录")

            # 4) 验证
            print("\n[4/4] 验证数据...")
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
                cursor.execute("""
                    SELECT code, name, change_percent, current_price, industry 
                    FROM csi300_stocks LIMIT 5
                """)
                samples = cursor.fetchall()

            print("=" * 70)
            print(f"总记录数: {total}")
            print(f"有涨跌幅: {stats['has_change']}")
            print(f"有价格: {stats['has_price']}")
            print(f"有行业: {stats['has_industry']}")
            print("\n前5条示例:")
            for r in samples:
                print(f"  {r['code']} {r['name']} 涨幅:{r['change_percent']}% 价:{r['current_price']} 行业:{r['industry']}")
            print("=" * 70)

            print("\n✓ 导入/更新完成！")
        except Exception as e:
            print(f"✗ 导入失败: {e}")


def display_results(results):
    """显示查询结果"""
    if not results:
        print("\n没有找到相关记录")
        return
    
    print(f"\n找到 {len(results)} 条记录:")
    print("-" * 100)
    
    for idx, row in enumerate(results, 1):
        print(f"\n【记录 {idx}】")
        for key, value in row.items():
            if value is not None:
                if isinstance(value, (int, float)):
                    if 'price' in key or 'value' in key or 'amount' in key:
                        print(f"  {key}: {value:,.2f}")
                    elif 'percent' in key or 'ratio' in key or 'pct' in key:
                        print(f"  {key}: {value:.2f}%")
                    else:
                        print(f"  {key}: {value}")
                else:
                    print(f"  {key}: {value}")
    
    print("-" * 100)


def handle_analysis(manager, choice):
    """处理潜力股和超跌股分析"""
    if choice == '22':
        print("\n" + "=" * 70)
        print("潜力股和超跌股分析（正向指标）")
        print("=" * 70)
        print("分析规则：")
        print("  - 获取涨幅榜前3名与跌幅榜前3名的行业")
        print("  - 潜力股：涨幅 >= 1%")
        print("  - 超跌股：跌幅 <= -3%")
        print("  - 正向指标：选择涨跌幅个股数量最多的行业（并列全选）")
        print("  - 各行业分组显示前10条，并展示行业占比")
        print("=" * 70)
        
        input("\n按回车开始分析...")
        
        result = manager.get_potential_and_oversold_stocks(min_gain=1.0, max_loss=-3.0, reverse_mode=False)
        
    elif choice == '23':
        print("\n" + "=" * 70)
        print("潜力股和超跌股分析（反向指标）")
        print("=" * 70)
        print("分析规则：")
        print("  - 获取涨幅榜前3名与跌幅榜前3名的行业")
        print("  - 潜力股：涨幅 >= 1%")
        print("  - 超跌股：跌幅 <= -3%")
        print("  - 反向指标：排除涨跌幅个股数量最多的行业，选择数量少的行业")
        print("  - 各行业分组显示前10条，并展示行业占比")
        print("=" * 70)
        
        input("\n按回车开始分析...")
        
        result = manager.get_potential_and_oversold_stocks(min_gain=1.0, max_loss=-3.0, reverse_mode=True)
    else:
        return
    
    if result:  # pyright: ignore[reportUnreachable]
        print("\n" + "=" * 70)
            
        # 展示涨幅榜前3名
        top_gainers = result.get('top_gainers', [])
        print("\n【涨幅榜前3名】")
        if top_gainers:
            print("-" * 100)
            for idx, stock in enumerate(top_gainers, 1):
                print(f"{idx}. {stock['name']} ({stock['code']}) - 行业:{stock.get('industry','未知')} "
                      f"涨幅:{stock['change_percent']:.2f}%")
            print("-" * 100)
        else:
            print("暂无涨幅榜数据")
            
        # 展示跌幅榜前3名
        top_losers = result.get('top_losers', [])
        print("\n【跌幅榜前3名】")
        if top_losers:
            print("-" * 100)
            for idx, stock in enumerate(top_losers, 1):
                print(f"{idx}. {stock['name']} ({stock['code']}) - 行业:{stock.get('industry','未知')} "
                      f"跌幅:{stock['change_percent']:.2f}%")
            print("-" * 100)
        else:
            print("暂无跌幅榜数据")

        # 选中的行业
        gain_inds = result.get('gain_selected_industries', [])
        loss_inds = result.get('loss_selected_industries', [])
        print(f"\n潜力股入选行业: {', '.join(gain_inds) if gain_inds else '无'}")
        print(f"超跌股入选行业: {', '.join(loss_inds) if loss_inds else '无'}")

        # 显示潜力股（分行业）
        potential_groups = result.get('potential_groups', {})
        potential_total = result.get('potential_total', 0)
        potential_dist = result.get('potential_distribution', [])
        print(f"\n【潜力股】（涨幅>=1%，总计{potential_total}条，按行业分组显示前10）")
        if potential_total > 0:
            print("-" * 100)
            for ind in gain_inds:
                rows = potential_groups.get(ind, [])
                dist = next((d for d in potential_dist if d['industry'] == ind), None)
                if dist:
                    print(f"行业: {ind} | 数量: {dist['count']} | 占比: {dist['ratio_percent']}%")
                else:
                    print(f"行业: {ind} | 数量: 0 | 占比: 0%")
                for i, stock in enumerate(rows, 1):
                    print(f"  {i}. {stock['name']} ({stock['code']}) 涨幅:{stock['change_percent']:.2f}% 现价:{stock['current_price']:.2f}")
                    if stock.get('change_5days') is not None:
                        print(f"     5日:{stock['change_5days']:.2f}% 10日:{stock['change_10days']:.2f}% 20日:{stock['change_20days']:.2f}%")
            print("-" * 100)
            print("行业分布：")
            for d in potential_dist:
                print(f"  {d['industry']}: {d['count']} ({d['ratio_percent']}%)")
        else:
            print("暂无符合条件的潜力股")

        # 显示超跌股（分行业）
        oversold_groups = result.get('oversold_groups', {})
        oversold_total = result.get('oversold_total', 0)
        oversold_dist = result.get('oversold_distribution', [])
        print(f"\n【超跌股】（跌幅<=-3%，总计{oversold_total}条，按行业分组显示前10）")
        if oversold_total > 0:
            print("-" * 100)
            for ind in loss_inds:
                rows = oversold_groups.get(ind, [])
                dist = next((d for d in oversold_dist if d['industry'] == ind), None)
                if dist:
                    print(f"行业: {ind} | 数量: {dist['count']} | 占比: {dist['ratio_percent']}%")
                else:
                    print(f"行业: {ind} | 数量: 0 | 占比: 0%")
                for i, stock in enumerate(rows, 1):
                    print(f"  {i}. {stock['name']} ({stock['code']}) 跌幅:{stock['change_percent']:.2f}% 现价:{stock['current_price']:.2f}")
                    if stock.get('change_5days') is not None:
                        print(f"     5日:{stock['change_5days']:.2f}% 10日:{stock['change_10days']:.2f}% 20日:{stock['change_20days']:.2f}%")
            print("-" * 100)
            print("行业分布：")
            for d in oversold_dist:
                print(f"  {d['industry']}: {d['count']} ({d['ratio_percent']}%)")
        else:
            print("暂无符合条件的超跌股")
        print("\n" + "=" * 70)

        # 询问是否导出（合并汇总版本）
        do_export = (potential_total > 0) or (oversold_total > 0)
        if do_export:
            export_choice = input("\n是否导出汇总数据？(y/n): ").strip().lower()
            if export_choice == 'y':
                # 合并所有潜力股
                if potential_total > 0:
                    all_potential = []
                    for ind in gain_inds:
                        all_potential.extend(potential_groups.get(ind, []))
                    if all_potential:
                        manager.export_to_csv(all_potential, f"潜力股汇总.csv")
                
                # 合并所有超跌股
                if oversold_total > 0:
                    all_oversold = []
                    for ind in loss_inds:
                        all_oversold.extend(oversold_groups.get(ind, []))
                    if all_oversold:
                        manager.export_to_csv(all_oversold, f"超跌股汇总.csv")
    else:
        print("\n✗ 分析失败")


def export_prompt(manager, data):
    """询问是否导出"""
    if not data:
        return
    
    choice = input("\n是否导出到CSV文件？(y/n): ").strip().lower()
    if choice == 'y':
        filename = input("文件名（回车使用默认名）: ").strip()
        filename = filename if filename else None
        manager.export_to_csv(data, filename)


def main():
    """主函数"""
    manager = StockManager()
    
    if not manager.connection:
        print("无法连接到数据库")
        return
    
    print("✓ 数据库连接成功")
    
    try:
        while True:
            print_menu()
            choice = input("\n请选择操作（输入数字）: ").strip()
            
            if choice == '0':
                print("\n感谢使用！再见！")
                break
            
            elif choice in ['1', '2', '3', '4', '5', '6', '7']:
                handle_stock_query(manager, choice)
                input("\n按回车键继续...")
            
            elif choice in ['8', '9', '10']:
                handle_stock_statistics(manager, choice)
                input("\n按回车键继续...")
            
            elif choice in ['11', '12', '13']:
                handle_order_query(manager, choice)
                input("\n按回车键继续...")
            
            elif choice == '14':
                handle_order_statistics(manager, choice)
                input("\n按回车键继续...")
            
            elif choice in ['15', '16', '17', '18']:
                handle_position_query(manager, choice)
                input("\n按回车键继续...")
            
            elif choice == '19':
                handle_position_statistics(manager, choice)
                input("\n按回车键继续...")
            
            elif choice == '20':
                handle_import(manager, choice)
                input("\n按回车键继续...")
            
            elif choice == '21':
                handle_import(manager, choice)
                input("\n按回车键继续...")
            
            elif choice == '22':
                handle_analysis(manager, choice)
                input("\n按回车键继续...")
            
            elif choice == '23':
                handle_analysis(manager, choice)
                input("\n按回车键继续...")
            
            else:
                print("无效的选择，请重新输入")
                input("\n按回车键继续...")
    
    except KeyboardInterrupt:
        print("\n\n程序被用户中断")
    except Exception as e:
        print(f"\n发生错误: {e}")
    finally:
        manager.close()
        print("\n数据库连接已关闭")


if __name__ == '__main__':
    main()

