#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
导入委托和持仓数据到数据库
包含两个表：orders_intraday 和 positions_intraday
"""

import pandas as pd
import pymysql
import sys
import re
from datetime import datetime
from db_config import DB_CONFIG


def clean_symbol(symbol):
    """清理证券代码，去掉 =" 等字符"""
    if pd.isna(symbol):
        return None
    # 去掉 =" 和 "
    cleaned = str(symbol).replace('="', '').replace('"', '').strip()
    # 如果还包含 = 符号，去掉它
    if '=' in cleaned:
        cleaned = cleaned.replace('=', '').strip()
    return cleaned if cleaned else None


def parse_percent(value):
    """解析百分比"""
    if pd.isna(value):
        return None
    try:
        value_str = str(value).replace('%', '').replace('+', '')
        return float(value_str)
    except:
        return None


def parse_time(time_str):
    """解析时间，返回今天的时间"""
    if pd.isna(time_str):
        return None
    try:
        # 如果只有时间没有日期，加上今天的日期
        if ':' in str(time_str):
            today = datetime.now().date()
            time_part = str(time_str)
            return f"{today} {time_part}"
        return str(time_str)
    except:
        return None


def create_orders_table(connection):
    """创建委托表"""
    try:
        with connection.cursor() as cursor:
            # 删除旧表
            cursor.execute("DROP TABLE IF EXISTS orders_intraday")
            
            # 创建新表
            sql = """
            CREATE TABLE `orders_intraday` (
              `id` INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
              `order_time` VARCHAR(20) DEFAULT NULL COMMENT '委托时间',
              `symbol` VARCHAR(20) NOT NULL COMMENT '证券代码',
              `name` VARCHAR(50) DEFAULT NULL COMMENT '证券名称',
              `side` VARCHAR(20) DEFAULT NULL COMMENT '委托方向',
              `order_qty` INT DEFAULT NULL COMMENT '委托数量',
              `order_status` VARCHAR(20) DEFAULT NULL COMMENT '委托状态',
              `order_price` DECIMAL(10, 3) DEFAULT NULL COMMENT '委托价格',
              `filled_qty` INT DEFAULT NULL COMMENT '成交数量',
              `filled_amount` DECIMAL(15, 2) DEFAULT NULL COMMENT '成交金额',
              `filled_avg_price` DECIMAL(10, 3) DEFAULT NULL COMMENT '成交均价',
              `market` VARCHAR(20) DEFAULT NULL COMMENT '交易市场',
              `order_id` VARCHAR(50) NOT NULL COMMENT '委托编号',
              `account_id` VARCHAR(50) DEFAULT NULL COMMENT '股东账号',
              `currency` VARCHAR(10) DEFAULT NULL COMMENT '币种',
              `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
              PRIMARY KEY (`id`),
              UNIQUE KEY `idx_order_id` (`order_id`),
              KEY `idx_symbol` (`symbol`),
              KEY `idx_order_time` (`order_time`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='当日委托表';
            """
            cursor.execute(sql)
            connection.commit()
            print("[OK] 委托表创建成功")
            return True
    except Exception as e:
        print(f"[FAIL] 创建委托表失败: {e}")
        return False


def create_positions_table(connection):
    """创建持仓表"""
    try:
        with connection.cursor() as cursor:
            # 删除旧表
            cursor.execute("DROP TABLE IF EXISTS positions_intraday")
            
            # 创建新表
            sql = """
            CREATE TABLE `positions_intraday` (
              `id` INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
              `seq` INT DEFAULT NULL COMMENT '序号',
              `symbol` VARCHAR(20) NOT NULL COMMENT '证券代码',
              `name` VARCHAR(50) DEFAULT NULL COMMENT '证券名称',
              `quantity` INT DEFAULT NULL COMMENT '持仓数量',
              `available_qty` INT DEFAULT NULL COMMENT '可用数量',
              `cost_price` DECIMAL(10, 3) DEFAULT NULL COMMENT '成本价',
              `last_price` DECIMAL(10, 3) DEFAULT NULL COMMENT '最新价',
              `pnl_pct` DECIMAL(10, 2) DEFAULT NULL COMMENT '持仓盈亏比例(%)',
              `pnl` DECIMAL(15, 2) DEFAULT NULL COMMENT '持仓盈亏',
              `today_pnl_pct` DECIMAL(10, 2) DEFAULT NULL COMMENT '当日盈亏比例(%)',
              `today_pnl` DECIMAL(15, 2) DEFAULT NULL COMMENT '当日盈亏',
              `buy_avg_price` DECIMAL(10, 3) DEFAULT NULL COMMENT '买入均价',
              `position_ratio` DECIMAL(10, 2) DEFAULT NULL COMMENT '个股仓位(%)',
              `market_value` DECIMAL(15, 2) DEFAULT NULL COMMENT '最新市值',
              `market` VARCHAR(20) DEFAULT NULL COMMENT '交易市场',
              `account_id` VARCHAR(50) DEFAULT NULL COMMENT '股东账号',
              `currency` VARCHAR(10) DEFAULT NULL COMMENT '币种',
              `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
              PRIMARY KEY (`id`),
              KEY `idx_symbol` (`symbol`),
              KEY `idx_account` (`account_id`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='持仓表';
            """
            cursor.execute(sql)
            connection.commit()
            print("[OK] 持仓表创建成功")
            return True
    except Exception as e:
        print(f"[FAIL] 创建持仓表失败: {e}")
        return False


def import_orders(connection, filepath='当日委托.xls'):
    """导入委托数据"""
    try:
        print(f"正在读取 {filepath}...")
        df = pd.read_csv(filepath, sep='\t', encoding='gbk')
        print(f"[OK] 读取成功，共 {len(df)} 条记录")
        
        # 准备数据
        values = []
        for _, row in df.iterrows():
            value = (
                parse_time(row['委托时间']),
                clean_symbol(row['证券代码']),
                str(row['证券名称']) if pd.notna(row['证券名称']) else None,
                str(row['委托方向']) if pd.notna(row['委托方向']) else None,
                int(row['委托数量']) if pd.notna(row['委托数量']) else None,
                str(row['委托状态']) if pd.notna(row['委托状态']) else None,
                float(row['委托价格']) if pd.notna(row['委托价格']) else None,
                int(row['成交数量']) if pd.notna(row['成交数量']) else None,
                float(row['成交金额']) if pd.notna(row['成交金额']) else None,
                float(row['成交均价']) if pd.notna(row['成交均价']) else None,
                str(row['交易市场']) if pd.notna(row['交易市场']) else None,
                str(row['委托编号']) if pd.notna(row['委托编号']) else None,
                str(row['股东账号']) if pd.notna(row['股东账号']) else None,
                str(row['币种']) if pd.notna(row['币种']) else None
            )
            values.append(value)
        
        # 插入数据
        sql = """
        INSERT INTO orders_intraday 
        (order_time, symbol, name, side, order_qty, order_status, order_price,
         filled_qty, filled_amount, filled_avg_price, market, order_id, account_id, currency)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
        order_time=VALUES(order_time), filled_qty=VALUES(filled_qty), 
        filled_amount=VALUES(filled_amount), filled_avg_price=VALUES(filled_avg_price)
        """
        
        with connection.cursor() as cursor:
            affected = cursor.executemany(sql, values)
            connection.commit()
            print(f"[OK] 成功插入/更新 {affected} 条委托记录")
            return True
            
    except Exception as e:
        print(f"[FAIL] 导入委托数据失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def import_positions(connection, filepath='资金持仓.xls'):
    """导入持仓数据"""
    try:
        print(f"正在读取 {filepath}...")
        
        # 读取完整文件内容
        with open(filepath, 'r', encoding='gbk') as f:
            lines = f.readlines()
        
        # 查找持仓明细的起始行
        header_idx = -1
        for i, line in enumerate(lines):
            if '序' in line and '证券代码' in line:
                header_idx = i
                break
        
        if header_idx == -1:
            print("[FAIL] 未找到持仓明细表头")
            return False
        
        # 读取持仓数据（跳过表头后的空行）
        data_lines = []
        for i in range(header_idx + 2, len(lines)):
            line = lines[i].strip()
            if line and line.replace('\t', ''):
                data_lines.append(line.split('\t'))
        
        if not data_lines:
            print("[FAIL] 未找到持仓数据")
            return False
        
        print(f"[OK] 找到 {len(data_lines)} 条持仓记录")
        
        # 准备数据
        values = []
        for i, fields in enumerate(data_lines, 1):
            try:
                # 字段映射
                seq = int(fields[0]) if fields[0] else i
                symbol = clean_symbol(fields[1])
                name = fields[2] if len(fields) > 2 else None
                quantity = int(float(fields[3])) if len(fields) > 3 and fields[3] else None
                available_qty = int(float(fields[4])) if len(fields) > 4 and fields[4] else None
                cost_price = float(fields[5]) if len(fields) > 5 and fields[5] else None
                last_price = float(fields[6]) if len(fields) > 6 and fields[6] else None
                pnl_pct = parse_percent(fields[7]) if len(fields) > 7 else None
                pnl = float(fields[8]) if len(fields) > 8 and fields[8] else None
                today_pnl_pct = parse_percent(fields[9]) if len(fields) > 9 else None
                today_pnl = float(fields[10]) if len(fields) > 10 and fields[10] else None
                buy_avg_price = float(fields[11]) if len(fields) > 11 and fields[11] else None
                position_ratio = parse_percent(fields[12]) if len(fields) > 12 else None
                market_value = float(fields[13]) if len(fields) > 13 and fields[13] else None
                market = fields[14] if len(fields) > 14 else None
                account_id = fields[15] if len(fields) > 15 else None
                currency = fields[16] if len(fields) > 16 else None
                
                value = (
                    seq, symbol, name, quantity, available_qty, cost_price, last_price,
                    pnl_pct, pnl, today_pnl_pct, today_pnl, buy_avg_price, position_ratio,
                    market_value, market, account_id, currency
                )
                values.append(value)
            except Exception as e:
                print(f"跳过第 {i} 条记录，错误: {e}")
                continue
        
        # 插入数据
        sql = """
        INSERT INTO positions_intraday 
        (seq, symbol, name, quantity, available_qty, cost_price, last_price,
         pnl_pct, pnl, today_pnl_pct, today_pnl, buy_avg_price, position_ratio,
         market_value, market, account_id, currency)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        with connection.cursor() as cursor:
            affected = cursor.executemany(sql, values)
            connection.commit()
            print(f"[OK] 成功插入 {affected} 条持仓记录")
            return True
            
    except Exception as e:
        print(f"[FAIL] 导入持仓数据失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """主函数"""
    print("=" * 80)
    print("导入委托和持仓数据")
    print("=" * 80)
    
    # 连接数据库
    try:
        connection = pymysql.connect(
            host=DB_CONFIG['host'],
            port=DB_CONFIG['port'],
            user=DB_CONFIG['user'],
            password=DB_CONFIG['password'],
            database=DB_CONFIG['database'],
            charset=DB_CONFIG['charset'],
            cursorclass=pymysql.cursors.DictCursor
        )
        print("[OK] 数据库连接成功\n")
    except Exception as e:
        print(f"[FAIL] 数据库连接失败: {e}")
        return
    
    try:
        # 1. 创建表
        print("\n[1/4] 创建数据库表...")
        if not create_orders_table(connection):
            return
        if not create_positions_table(connection):
            return
        
        # 2. 导入委托数据
        print("\n[2/4] 导入委托数据...")
        if not import_orders(connection):
            return
        
        # 3. 导入持仓数据
        print("\n[3/4] 导入持仓数据...")
        if not import_positions(connection):
            return
        
        # 4. 验证数据
        print("\n[4/4] 验证数据...")
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) as count FROM orders_intraday")
            orders_count = cursor.fetchone()['count']
            
            cursor.execute("SELECT COUNT(*) as count FROM positions_intraday")
            positions_count = cursor.fetchone()['count']
            
            print(f"[OK] 委托表记录数: {orders_count}")
            print(f"[OK] 持仓表记录数: {positions_count}")
            
            # 显示样例
            cursor.execute("SELECT * FROM orders_intraday LIMIT 2")
            print("\n委托样例:")
            for row in cursor.fetchall():
                print(f"  {row['symbol']} {row['name']} {row['order_status']}")
            
            cursor.execute("SELECT * FROM positions_intraday LIMIT 2")
            print("\n持仓样例:")
            for row in cursor.fetchall():
                print(f"  {row['symbol']} {row['name']} 持仓:{row['quantity']} 盈亏:{row['pnl_pct']}%")
        
        print("\n" + "=" * 80)
        print("[OK] 导入完成！")
        print("=" * 80)
        
    except Exception as e:
        print(f"\n[FAIL] 发生错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        connection.close()
        print("\n数据库连接已关闭")


if __name__ == '__main__':
    main()

