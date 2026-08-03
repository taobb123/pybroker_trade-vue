#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试数据库连接
"""

import pymysql
import sys
from db_config import DB_CONFIG


def test_db_connection():
    """测试数据库连接"""
    print("=" * 50)
    print("数据库连接测试")
    print("=" * 50)
    
    print("\n数据库配置信息:")
    print(f"  主机: {DB_CONFIG['host']}")
    print(f"  端口: {DB_CONFIG['port']}")
    print(f"  用户: {DB_CONFIG['user']}")
    print(f"  数据库: {DB_CONFIG['database']}")
    print(f"  字符集: {DB_CONFIG['charset']}")
    
    print("\n正在连接数据库...")
    
    try:
        # 尝试连接数据库
        connection = pymysql.connect(
            host=DB_CONFIG['host'],
            port=DB_CONFIG['port'],
            user=DB_CONFIG['user'],
            password=DB_CONFIG['password'],
            database=DB_CONFIG['database'],
            charset=DB_CONFIG['charset'],
            cursorclass=pymysql.cursors.DictCursor
        )
        
        print("✓ 数据库连接成功！\n")
        
        # 获取数据库版本信息
        with connection.cursor() as cursor:
            cursor.execute("SELECT VERSION() as version")
            result = cursor.fetchone()
            print(f"数据库版本: {result['version']}")
        
        # 尝试获取数据库中的表
        with connection.cursor() as cursor:
            cursor.execute("SHOW TABLES")
            tables = cursor.fetchall()
            
            if tables:
                print(f"\n数据库中共有 {len(tables)} 个表:")
                for table in tables:
                    table_name = list(table.values())[0]
                    print(f"  - {table_name}")
                    
                    # 获取每个表的记录数
                    try:
                        cursor.execute(f"SELECT COUNT(*) as count FROM {table_name}")
                        count_result = cursor.fetchone()
                        print(f"    记录数: {count_result['count']}")
                    except:
                        pass
            else:
                print("\n数据库中没有表")
        
        connection.close()
        print("\n" + "=" * 50)
        print("✓ 测试完成！")
        print("=" * 50)
        return True
        
    except pymysql.OperationalError as e:
        print(f"\n✗ 数据库连接失败: {e}")
        print("\n可能的原因:")
        print("  1. MySQL服务未启动")
        print("  2. 数据库密码错误")
        print("  3. 数据库不存在，请先创建数据库")
        print("  4. 主机地址或端口不正确")
        return False
        
    except Exception as e:
        print(f"\n✗ 发生未知错误: {e}")
        return False


if __name__ == '__main__':
    success = test_db_connection()
    sys.exit(0 if success else 1)

