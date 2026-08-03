```446:576:c:\Users\111\Desktop\data\manage_stocks.py
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
        print(f\"分析失败: {e}\")
        return None
```