#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通过API补充财务数据，统计最赚钱的公司和被低估的公司
"""

import pandas as pd
import time
import sys
import csv
from datetime import datetime
import akshare as ak


class FinancialDataAnalyzer:
    """财务数据分析器"""
    
    def __init__(self, filepath='沪深300.xls'):
        self.filepath = filepath
        self.base_data = None
        self.financial_data = {}
        
    def load_base_data(self):
        """加载基础数据"""
        print(f"\n[1/5] 读取基础数据: {self.filepath}")
        try:
            # 尝试不同编码
            for encoding in ['gbk', 'gb2312', 'utf-8']:
                try:
                    df = pd.read_csv(self.filepath, sep='\t', encoding=encoding)
                    print(f"✓ 读取成功（编码: {encoding}），共 {len(df)} 条记录")
                    self.base_data = df
                    return True
                except Exception:
                    continue
            print("✗ 读取失败：无法识别文件编码")
            return False
        except Exception as e:
            print(f"✗ 读取失败: {e}")
            return False
    
    def normalize_stock_code(self, code):
        """标准化股票代码格式"""
        if pd.isna(code):
            return None
        code = str(code).strip().upper()
        # akshare需要：sz000001, sh600000格式
        if code.startswith('SZ') or code.startswith('SH'):
            return code
        elif code.startswith('0') or code.startswith('3'):
            return f'sz{code}'
        elif code.startswith('6') or code.startswith('9'):
            return f'sh{code}'
        else:
            return code
    
    def get_financial_data(self, code, retry=2):
        """获取单个股票的财务数据（多接口回退）"""
        normalized_code = self.normalize_stock_code(code)
        if not normalized_code:
            return None
        
        # 如果已缓存，直接返回
        if normalized_code in self.financial_data:
            return self.financial_data[normalized_code]
        
        # 从代码中提取纯数字部分用于akshare
        stock_code = code.replace('SZ', '').replace('SH', '').replace('sz', '').replace('sh', '').strip()
        
        # 尝试多个接口
        api_methods = [
            ('stock_financial_abstract', lambda: ak.stock_financial_abstract(symbol=stock_code)),
        ]
        
        for api_name, api_func in api_methods:
            for attempt in range(retry):
                try:
                    df = api_func()
                    
                    if df is None or df.empty:
                        time.sleep(0.3)
                        continue
                    
                    # 检查是否有"指标"列
                    if '指标' not in df.columns:
                        continue
                    
                    # 提取最新一期数据（改进版）
                    latest_col = None
                    
                    # 收集所有可能的日期列
                    date_cols = []
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
                            if any(year in col_str for year in ['2024', '2023', '2022', '2025']):
                                date_cols.append(col_str)
                    
                    # 选择最新的日期列（排除未来日期，优先选择2024、2023的数据）
                    if date_cols:
                        # 过滤掉未来日期（大于当前日期）
                        current_date = datetime.now().strftime('%Y%m%d')
                        valid_dates = []
                        for d in date_cols:
                            if d.isdigit() and len(d) == 8:
                                if d <= current_date:  # 只选择小于等于当前日期的
                                    valid_dates.append(d)
                        
                        if valid_dates:
                            # 优先选择最新的有效日期（通常是2024年的年报或季报）
                            latest_col = sorted(valid_dates, reverse=True)[0]
                        else:
                            # 如果没有有效日期，尝试选择最近的年份列（可能是字符串格式的日期）
                            year_based = sorted([d for d in date_cols if any(y in str(d) for y in ['2024', '2023'])], reverse=True, key=lambda x: str(x))
                            if year_based:
                                latest_col = year_based[0]
                            else:
                                # 最后备选：选择第一个可用的
                                latest_col = date_cols[0] if date_cols else None
                    
                    if latest_col is None:
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
                    
                    # 如果成功获取到数据，缓存并返回
                    if financial_dict:
                        self.financial_data[normalized_code] = financial_dict
                        return financial_dict
                    
                except Exception as e:
                    if attempt < retry - 1:
                        time.sleep(0.5)
                        continue
                    else:
                        # 最后一次尝试也失败，尝试下一个接口
                        break
        
        # 所有接口都失败
        return None
    
    def batch_get_financial_data(self, limit=None, delay=0.3):
        """批量获取财务数据"""
        if self.base_data is None:
            print("✗ 请先加载基础数据")
            return False
        
        print(f"\n[2/5] 批量获取财务数据（延迟: {delay}秒/只）...")
        
        codes = self.base_data['代码'].unique()
        if limit:
            codes = codes[:limit]
        
        total = len(codes)
        success = 0
        failed = 0
        
        for idx, code in enumerate(codes, 1):
            print(f"  [{idx}/{total}] {code}...", end='', flush=True)
            result = self.get_financial_data(code)
            if result and len(result) > 0:
                success += 1
                # 显示获取到的指标数量
                indicator_count = len([k for k, v in result.items() if v is not None])
                print(f" ✓ ({indicator_count}个指标)")
            else:
                failed += 1
                print(" ✗")
            
            # 延迟避免频率限制
            if idx < total:
                time.sleep(delay)
        
        print(f"\n✓ 完成: 成功 {success} 只，失败 {failed} 只")
        return True
    
    def calculate_metrics(self):
        """计算完整指标"""
        print(f"\n[3/5] 计算完整指标...")
        
        if self.base_data is None:
            print("✗ 请先加载基础数据")
            return None
        
        results = []
        
        for _, row in self.base_data.iterrows():
            code = str(row.get('代码', '')).strip()
            name = str(row.get('名称', '')).strip() if pd.notna(row.get('名称')) else ''
            
            # 基础数据
            current_price = pd.to_numeric(row.get('现价'), errors='coerce')
            total_mv = pd.to_numeric(row.get('总市值'), errors='coerce')
            pe_ratio = pd.to_numeric(row.get('市盈(动)'), errors='coerce')
            pb_ratio = pd.to_numeric(row.get('市净率'), errors='coerce')
            change_percent = pd.to_numeric(str(row.get('涨幅', '')).replace('%', '').replace('+', ''), errors='coerce')
            industry = str(row.get('所属行业', '')).strip() if pd.notna(row.get('所属行业')) else ''
            
            # 财务数据
            normalized_code = self.normalize_stock_code(code)
            financial = self.financial_data.get(normalized_code, {})
            
            # 提取关键财务指标（尝试多种可能的指标名称）
            net_profit = financial.get('净利润') or financial.get('净利润(元)') or financial.get('归母净利润')
            revenue = financial.get('营业收入') or financial.get('营业收入(元)')
            roe = financial.get('净资产收益率(ROE)') or financial.get('ROE') or financial.get('净资产收益率')
            eps = financial.get('每股收益') or financial.get('基本每股收益')
            total_shares = financial.get('总股本') or financial.get('总股本(万股)')
            net_assets = financial.get('净资产') or financial.get('净资产(元)')
            
            # 如果净利润缺失，尝试通过总市值和市盈率计算
            if net_profit is None and total_mv is not None and pe_ratio is not None and pe_ratio > 0 and pe_ratio < 1000:
                net_profit = total_mv / pe_ratio  # 净利润 = 总市值 / 市盈率
            
            # 计算衍生指标
            profit_margin = None
            if net_profit is not None and revenue is not None and revenue > 0:
                profit_margin = (net_profit / revenue) * 100
            
            # PEG需要增长率，暂时不计算
            
            result = {
                '代码': code,
                '名称': name,
                '行业': industry,
                '现价': current_price,
                '总市值': total_mv,
                '市盈率': pe_ratio,
                '市净率': pb_ratio,
                '涨幅': change_percent,
                # 财务数据
                '净利润': net_profit,
                '营业收入': revenue,
                'ROE': roe,
                '每股收益': eps,
                '总股本': total_shares,
                '净资产': net_assets,
                # 衍生指标
                '净利润率': profit_margin,
                # 评分指标
                '盈利得分': net_profit if net_profit else 0,
                '估值得分': (1/pe_ratio * 50 + 1/pb_ratio * 50) if (pe_ratio and pb_ratio and pe_ratio > 0 and pb_ratio > 0) else None,
            }
            
            results.append(result)
        
        df_results = pd.DataFrame(results)
        print(f"✓ 计算完成，共 {len(df_results)} 条记录")
        return df_results
    
    def find_most_profitable(self, df, top_n=20):
        """找出最赚钱的公司"""
        print(f"\n[4/5] 统计最赚钱的公司（TOP {top_n}）...")
        
        # 过滤掉净利润为空的，并且要求净利润>0
        df_valid = df[df['净利润'].notna() & (df['净利润'] > 0)].copy()
        
        if df_valid.empty:
            print("✗ 无有效净利润数据")
            print(f"  提示：有净利润数据的记录数: {df['净利润'].notna().sum()}")
            return None
        
        actual_top_n = min(top_n, len(df_valid))
        if actual_top_n < top_n:
            print(f"  注意：仅有 {actual_top_n} 条有效记录，显示TOP {actual_top_n}")
        
        # 按净利润排序
        df_valid = df_valid.sort_values('净利润', ascending=False)
        
        print(f"\n{'='*100}")
        print(f"最赚钱的公司 TOP {top_n}（按净利润排序）")
        print(f"{'='*100}")
        print(f"{'排名':<6} {'代码':<12} {'名称':<20} {'行业':<15} {'净利润(亿)':<15} {'ROE(%)':<10} {'净利润率(%)':<12} {'市盈率':<10}")
        print(f"{'-'*100}")
        
        for idx, (_, row) in enumerate(df_valid.head(actual_top_n).iterrows(), 1):
            profit_yi = row['净利润'] / 1e8 if pd.notna(row['净利润']) else 0
            roe = row['ROE'] if pd.notna(row['ROE']) else 0
            margin = row['净利润率'] if pd.notna(row['净利润率']) else 0
            pe = row['市盈率'] if pd.notna(row['市盈率']) else 0
            
            print(f"{idx:<6} {row['代码']:<12} {row['名称']:<20} {row['行业']:<15} "
                  f"{profit_yi:>12.2f} {roe:>8.2f} {margin:>10.2f} {pe:>8.2f}")
        
        print(f"{'='*100}\n")
        return df_valid.head(actual_top_n)
    
    def find_undervalued(self, df, top_n=20):
        """找出被低估的公司"""
        print(f"\n[5/5] 统计被低估的公司（TOP {top_n}）...")
        
        # 过滤条件：市盈率和市净率都不为空且大于0
        df_valid = df[
            df['市盈率'].notna() & (df['市盈率'] > 0) & (df['市盈率'] < 100) &
            df['市净率'].notna() & (df['市净率'] > 0) & (df['市净率'] < 20)
        ].copy()
        
        if df_valid.empty:
            print("✗ 无有效估值数据")
            return None
        
        # 计算综合低估得分：市盈率越低、市净率越低，得分越高
        # 使用倒数并归一化
        df_valid['PE_score'] = 1 / df_valid['市盈率']
        df_valid['PB_score'] = 1 / df_valid['市净率']
        df_valid['低估得分'] = (df_valid['PE_score'] * 0.6 + df_valid['PB_score'] * 0.4)
        
        # 额外加分：有净利润且ROE较高
        df_valid['盈利加分'] = 0
        mask_profit = df_valid['净利润'].notna() & (df_valid['净利润'] > 0)
        df_valid.loc[mask_profit, '盈利加分'] = 0.2
        
        mask_roe = df_valid['ROE'].notna() & (df_valid['ROE'] > 10)
        df_valid.loc[mask_roe, '盈利加分'] += 0.2
        
        df_valid['综合得分'] = df_valid['低估得分'] + df_valid['盈利加分']
        
        # 按综合得分排序
        df_valid = df_valid.sort_values('综合得分', ascending=False)
        
        print(f"\n{'='*100}")
        print(f"被低估的公司 TOP {top_n}（综合得分：低PE+低PB+盈利能力强）")
        print(f"{'='*100}")
        print(f"{'排名':<6} {'代码':<12} {'名称':<20} {'行业':<15} {'市盈率':<10} {'市净率':<10} "
              f"{'ROE(%)':<10} {'净利润(亿)':<15} {'综合得分':<12}")
        print(f"{'-'*100}")
        
        for idx, (_, row) in enumerate(df_valid.head(top_n).iterrows(), 1):
            pe = row['市盈率'] if pd.notna(row['市盈率']) else 0
            pb = row['市净率'] if pd.notna(row['市净率']) else 0
            roe = row['ROE'] if pd.notna(row['ROE']) else 0
            profit_yi = row['净利润'] / 1e8 if pd.notna(row['净利润']) else 0
            score = row['综合得分'] if pd.notna(row['综合得分']) else 0
            
            print(f"{idx:<6} {row['代码']:<12} {row['名称']:<20} {row['行业']:<15} "
                  f"{pe:>8.2f} {pb:>8.2f} {roe:>8.2f} {profit_yi:>12.2f} {score:>10.4f}")
        
        print(f"{'='*100}\n")
        return df_valid.head(top_n)
    
    def export_results(self, profitable_df, undervalued_df, filename=None):
        """导出结果到CSV"""
        if filename is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'分析结果_{timestamp}.csv'
        
        print(f"\n导出结果到: {filename}")
        
        try:
            with open(filename, 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f)
                
                # 最赚钱的公司
                writer.writerow(['='*50])
                writer.writerow(['最赚钱的公司 TOP 20'])
                writer.writerow(['='*50])
                if profitable_df is not None and not profitable_df.empty:
                    profitable_df.to_csv(f, index=False, mode='a', encoding='utf-8-sig')
                else:
                    writer.writerow(['无数据'])
                
                writer.writerow([])
                writer.writerow([])
                
                # 被低估的公司
                writer.writerow(['='*50])
                writer.writerow(['被低估的公司 TOP 20'])
                writer.writerow(['='*50])
                if undervalued_df is not None and not undervalued_df.empty:
                    undervalued_df.to_csv(f, index=False, mode='a', encoding='utf-8-sig')
                else:
                    writer.writerow(['无数据'])
            
            print(f"✓ 导出成功")
            return True
        except Exception as e:
            print(f"✗ 导出失败: {e}")
            return False


def main():
    """主函数"""
    print("="*100)
    print("财务数据分析：最赚钱的公司 & 被低估的公司")
    print("="*100)
    
    analyzer = FinancialDataAnalyzer('沪深300.xls')
    
    # 1. 加载基础数据
    if not analyzer.load_base_data():
        return
    
    # 2. 询问是否批量获取财务数据
    print("\n提示：批量获取财务数据需要较长时间（约300只股票 × 0.3秒 ≈ 90秒）")
    print("可以选择：")
    print("  1. 完整获取所有股票财务数据（推荐）")
    print("  2. 仅获取前50只股票（快速测试）")
    print("  3. 跳过API获取，仅使用现有数据进行统计")
    
    choice = input("\n请选择 (1/2/3): ").strip()
    
    if choice == '1':
        analyzer.batch_get_financial_data(limit=None, delay=0.3)
    elif choice == '2':
        analyzer.batch_get_financial_data(limit=50, delay=0.3)
    else:
        print("跳过API获取，使用基础数据进行统计...")
    
    # 3. 计算指标
    results_df = analyzer.calculate_metrics()
    if results_df is None:
        return
    
    # 4. 统计最赚钱的公司
    profitable_df = analyzer.find_most_profitable(results_df, top_n=20)
    
    # 5. 统计被低估的公司
    undervalued_df = analyzer.find_undervalued(results_df, top_n=20)
    
    # 6. 导出结果
    export_choice = input("\n是否导出结果到CSV？(y/n): ").strip().lower()
    if export_choice == 'y':
        analyzer.export_results(profitable_df, undervalued_df)
    
    print("\n分析完成！")


if __name__ == '__main__':
    main()

