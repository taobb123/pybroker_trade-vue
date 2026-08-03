# 财务数据获取功能开发 TODO List

## 项目目标
完成财务数据的获取功能，支持事件驱动策略（财报策略）的实现。

---

## 一、核心模块开发

### ✅ financial_1: 创建FinancialDataFetcher类
**状态**: pending  
**描述**: 创建财务数据获取核心模块  
**文件**: `ma_strategy_project/data/financial_fetcher.py`  
**功能**:
- 继承或独立于DataFetcher
- 支持多种数据源（akshare, tushare等）
- 统一的接口设计
- 错误处理和重试机制

**验收标准**:
- [ ] 类可以成功初始化
- [ ] 支持上下文管理器（with语句）
- [ ] 有完善的日志记录

---

### ✅ financial_2: 实现单只股票财务数据获取方法
**状态**: pending  
**描述**: 支持多种财务指标获取  
**方法**: `get_financial_data(code, period='report')`  
**支持指标**:
- 净利润 (net_profit)
- 营业收入 (revenue)
- ROE (净资产收益率)
- ROA (总资产收益率)
- 每股收益 (EPS)
- 每股净资产 (BPS)
- 总资产
- 总负债
- 现金流
- 资产负债率

**验收标准**:
- [ ] 能获取单只股票的全部财务指标
- [ ] 支持年报、季报数据
- [ ] 支持历史多个报告期数据
- [ ] 返回格式统一（DataFrame或dict）

---

### ✅ financial_3: 实现批量财务数据获取方法
**状态**: pending  
**描述**: 支持股票列表批量获取  
**方法**: `batch_get_financial_data(codes, delay=0.3)`  
**功能**:
- 批量获取多只股票财务数据
- 支持并发/串行控制
- 频率限制处理
- 进度显示
- 失败重试机制

**验收标准**:
- [ ] 能批量获取至少100只股票数据
- [ ] 成功率>80%
- [ ] 有进度提示
- [ ] 失败股票有记录

---

## 二、数据库模块开发

### ✅ financial_4: 创建财务数据数据库表结构
**状态**: pending  
**描述**: 设计并创建财务数据存储表  
**表名**: `stock_financial_data`  
**字段设计**:
```sql
CREATE TABLE `stock_financial_data` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `code` VARCHAR(20) NOT NULL COMMENT '股票代码',
  `name` VARCHAR(50) DEFAULT NULL COMMENT '股票名称',
  `report_date` DATE NOT NULL COMMENT '报告期（YYYY-MM-DD）',
  `report_type` VARCHAR(10) DEFAULT NULL COMMENT '报告类型：年报/季报/半年报',
  -- 盈利能力指标
  `net_profit` DECIMAL(20, 2) DEFAULT NULL COMMENT '净利润（元）',
  `revenue` DECIMAL(20, 2) DEFAULT NULL COMMENT '营业收入（元）',
  `roe` DECIMAL(10, 4) DEFAULT NULL COMMENT '净资产收益率(%)',
  `roa` DECIMAL(10, 4) DEFAULT NULL COMMENT '总资产收益率(%)',
  `eps` DECIMAL(10, 4) DEFAULT NULL COMMENT '每股收益（元）',
  `profit_margin` DECIMAL(10, 4) DEFAULT NULL COMMENT '净利润率(%)',
  -- 财务结构指标
  `total_assets` DECIMAL(20, 2) DEFAULT NULL COMMENT '总资产（元）',
  `total_liabilities` DECIMAL(20, 2) DEFAULT NULL COMMENT '总负债（元）',
  `net_assets` DECIMAL(20, 2) DEFAULT NULL COMMENT '净资产（元）',
  `asset_liability_ratio` DECIMAL(10, 4) DEFAULT NULL COMMENT '资产负债率(%)',
  `bps` DECIMAL(10, 4) DEFAULT NULL COMMENT '每股净资产（元）',
  -- 现金流指标
  `operating_cashflow` DECIMAL(20, 2) DEFAULT NULL COMMENT '经营现金流（元）',
  `free_cashflow` DECIMAL(20, 2) DEFAULT NULL COMMENT '自由现金流（元）',
  -- 其他指标
  `total_shares` DECIMAL(20, 2) DEFAULT NULL COMMENT '总股本（万股）',
  `circulating_shares` DECIMAL(20, 2) DEFAULT NULL COMMENT '流通股本（万股）',
  -- 元数据
  `data_source` VARCHAR(50) DEFAULT 'akshare' COMMENT '数据来源',
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_code_date` (`code`, `report_date`),
  KEY `idx_code` (`code`),
  KEY `idx_report_date` (`report_date`),
  KEY `idx_report_type` (`report_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='股票财务数据表';
```

**验收标准**:
- [ ] 表结构设计合理
- [ ] 索引优化到位
- [ ] 支持唯一性约束
- [ ] 字段类型和精度合理

---

### ✅ financial_5: 实现财务数据存储到数据库
**状态**: pending  
**描述**: 支持增量更新和批量插入  
**方法**: `save_to_database(data, update_mode='upsert')`  
**功能**:
- 支持insert和upsert（存在则更新）
- 批量插入优化
- 数据去重
- 事务处理

**验收标准**:
- [ ] 能正确存储财务数据
- [ ] 支持增量更新（不重复插入）
- [ ] 批量插入性能>100条/秒
- [ ] 有数据验证机制

---

## 三、事件驱动支持

### ✅ financial_6: 实现财报发布日期获取
**状态**: pending  
**描述**: 获取财报发布日，用于事件驱动策略  
**方法**: `get_report_release_dates(code, start_date, end_date)`  
**表设计**: `stock_report_releases`
```sql
CREATE TABLE `stock_report_releases` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `code` VARCHAR(20) NOT NULL COMMENT '股票代码',
  `report_date` DATE NOT NULL COMMENT '报告期',
  `release_date` DATE NOT NULL COMMENT '发布日期',
  `report_type` VARCHAR(10) DEFAULT NULL COMMENT '年报/季报',
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_code_report` (`code`, `report_date`),
  KEY `idx_release_date` (`release_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

**验收标准**:
- [ ] 能获取财报发布日期
- [ ] 支持查询指定时间范围内的发布事件
- [ ] 数据准确可靠

---

### ✅ financial_7: 实现财务数据查询接口
**状态**: pending  
**描述**: 支持灵活的财务数据查询  
**方法**: 
- `query_financial_data(code, start_date=None, end_date=None)`
- `query_by_indicator(code, indicator, periods=4)`
- `query_latest_report(code)`

**验收标准**:
- [ ] 支持按日期范围查询
- [ ] 支持按指标查询
- [ ] 支持获取最新报告期数据
- [ ] 查询性能良好

---

## 四、自动化更新

### ✅ financial_8: 实现财务数据更新任务
**状态**: pending  
**描述**: 定期更新最新财报数据  
**文件**: `ma_strategy_project/tasks/financial_updater.py`  
**功能**:
- 定时任务（每天/每周执行）
- 检测新财报发布
- 自动更新数据
- 更新日志记录

**验收标准**:
- [ ] 能自动检测新财报
- [ ] 自动更新到数据库
- [ ] 有完整的更新日志
- [ ] 支持手动触发更新

---

## 五、策略集成

### ✅ financial_9: 创建财报策略基础框架
**状态**: pending  
**描述**: 基于财务数据的事件驱动策略  
**文件**: `ma_strategy_project/strategies/earnings_report_strategy.py`  
**策略思路**:
1. 监听财报发布事件
2. 分析财务指标变化
3. 基于超预期/不及预期触发交易信号
4. 支持多种策略：
   - 业绩超预期策略
   - 业绩反转策略
   - 估值修复策略

**验收标准**:
- [ ] 策略类实现BaseStrategy接口
- [ ] 能基于财务数据生成交易信号
- [ ] 支持回测
- [ ] 有详细的策略文档

---

## 六、系统集成

### ✅ financial_10: 集成到ma_strategy_project/data模块
**状态**: pending  
**描述**: 与现有DataFetcher协调工作  
**集成点**:
- 共享数据库配置
- 统一的日志系统
- 与K线数据协同
- 统一的错误处理

**验收标准**:
- [ ] 与现有系统兼容
- [ ] 不破坏现有功能
- [ ] 代码风格一致

---

## 七、质量保障

### ✅ financial_11: 添加财务数据质量检查
**状态**: pending  
**描述**: 数据验证和异常处理  
**检查项**:
- 数据完整性检查
- 数据合理性验证（如ROE不应>100%）
- 异常值检测
- 数据一致性检查

**验收标准**:
- [ ] 有完善的数据验证规则
- [ ] 能识别异常数据
- [ ] 有数据修复建议

---

### ✅ financial_12: 编写使用文档和示例代码
**状态**: pending  
**描述**: 帮助文档和示例  
**文档内容**:
- API使用说明
- 数据库表结构说明
- 示例代码
- 常见问题解答
- 策略开发指南

**验收标准**:
- [ ] 有完整的API文档
- [ ] 有至少3个示例代码
- [ ] 有FAQ文档

---

## 开发优先级

### 第一阶段（核心功能）
1. ✅ financial_1: 创建FinancialDataFetcher类
2. ✅ financial_2: 单只股票财务数据获取
3. ✅ financial_4: 数据库表结构
4. ✅ financial_5: 数据存储

### 第二阶段（批量功能）
5. ✅ financial_3: 批量获取
6. ✅ financial_7: 查询接口
7. ✅ financial_10: 系统集成

### 第三阶段（事件驱动）
8. ✅ financial_6: 财报发布日期
9. ✅ financial_9: 财报策略框架
10. ✅ financial_8: 自动更新任务

### 第四阶段（完善）
11. ✅ financial_11: 数据质量检查
12. ✅ financial_12: 文档编写

---

## 技术栈

- **语言**: Python 3.x
- **数据库**: MySQL 8.4.6
- **数据源**: akshare (主要), tushare (备选)
- **依赖**: pandas, pymysql, akshare

---

## 注意事项

1. **API频率限制**: akshare可能有频率限制，需要合理控制请求速度
2. **数据准确性**: 财务数据需要验证，不同数据源可能有差异
3. **更新频率**: 财报通常按季度/年度发布，需要考虑更新时机
4. **存储空间**: 历史财务数据会占用较多存储，需要定期清理策略

---

## 预计工作量

- 核心模块开发: 3-5天
- 数据库设计: 1天
- 批量获取优化: 2-3天
- 策略框架: 2-3天
- 文档和测试: 2-3天

**总计**: 约10-15个工作日

