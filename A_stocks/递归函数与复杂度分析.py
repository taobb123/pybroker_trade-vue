"""
递归函数与复杂度分析教程
===================

本文件包含多个经典的递归函数示例，用于深入理解算法复杂度分析。
每个函数都包含时间复杂度、空间复杂度的详细分析。
"""

import time
import sys
from functools import lru_cache
from typing import List, Dict


# ============================================================================
# 示例1：斐波那契数列（经典递归 vs 优化版本）
# ============================================================================

def fibonacci_naive(n: int) -> int:
    """
    斐波那契数列 - 朴素递归实现
    
    时间复杂度：O(2^n)
    - 递归树：每个节点分裂成2个子节点，深度为n
    - T(n) = T(n-1) + T(n-2) + O(1)
    - 递推关系近似：T(n) ≈ 2T(n-1) ≈ 2^n
    
    空间复杂度：O(n)
    - 递归调用栈的最大深度为n
    - 每次调用需要O(1)的栈空间
    
    问题：存在大量重复计算！
    例如：fib(5) = fib(4) + fib(3)，而fib(4)又需要计算fib(3)
    """
    if n <= 1:
        return n
    return fibonacci_naive(n - 1) + fibonacci_naive(n - 2)


def fibonacci_memoized(n: int, memo: Dict[int, int] = None) -> int:
    """
    斐波那契数列 - 记忆化递归（自顶向下）
    
    时间复杂度：O(n)
    - 每个fibonacci(i)只计算一次，总共n个不同的子问题
    - 一旦计算结果被存储，后续直接查表O(1)
    
    空间复杂度：O(n)
    - memo字典存储n个结果：O(n)
    - 递归调用栈深度：O(n)
    - 总空间：O(n)
    
    优化：通过记忆化避免重复计算
    """
    if memo is None:
        memo = {}
    
    if n <= 1:
        return n
    
    if n in memo:
        return memo[n]
    
    memo[n] = fibonacci_memoized(n - 1, memo) + fibonacci_memoized(n - 2, memo)
    return memo[n]


def fibonacci_iterative(n: int) -> int:
    """
    斐波那契数列 - 迭代实现（自底向上）
    
    时间复杂度：O(n)
    - 单循环，执行n次
    
    空间复杂度：O(1)
    - 只使用固定数量的变量（prev, curr, next_val）
    - 不需要递归栈，不需要存储所有中间结果
    
    最优解：时间O(n)，空间O(1)
    """
    if n <= 1:
        return n
    
    prev, curr = 0, 1
    for i in range(2, n + 1):
        prev, curr = curr, prev + curr
    
    return curr


# ============================================================================
# 示例2：汉诺塔问题
# ============================================================================

def hanoi_tower(n: int, source: str, destination: str, auxiliary: str) -> List[str]:
    """
    汉诺塔问题 - 递归解决
    
    问题：将n个盘子从source柱移动到destination柱，使用auxiliary作为辅助
    
    时间复杂度：O(2^n)
    - 递推关系：T(n) = 2T(n-1) + 1
    - 展开：T(n) = 2(2T(n-2) + 1) + 1 = 4T(n-2) + 3
    -        = 2^k * T(n-k) + (2^k - 1)
    - 当k=n时：T(n) = 2^n * T(0) + (2^n - 1) = 2^n - 1
    - 因此：T(n) = Θ(2^n)
    
    空间复杂度：O(n)
    - 递归调用栈深度为n
    - 每个调用需要O(1)的栈空间
    
    证明：最少移动次数为2^n - 1（用数学归纳法可以证明）
    """
    moves = []
    
    def _hanoi(n_disks: int, src: str, dest: str, aux: str):
        if n_disks == 1:
            moves.append(f"移动盘子 {n_disks} 从 {src} 到 {dest}")
        else:
            # 步骤1：将上面的n-1个盘子从source移到auxiliary
            _hanoi(n_disks - 1, src, aux, dest)
            # 步骤2：将最大的盘子从source移到destination
            moves.append(f"移动盘子 {n_disks} 从 {src} 到 {dest}")
            # 步骤3：将n-1个盘子从auxiliary移到destination
            _hanoi(n_disks - 1, aux, dest, src)
    
    _hanoi(n, source, destination, auxiliary)
    return moves


# ============================================================================
# 示例3：二分查找（递归版本）
# ============================================================================

def binary_search_recursive(arr: List[int], target: int, left: int = 0, right: int = None) -> int:
    """
    二分查找 - 递归实现
    
    时间复杂度：O(log n)
    - 每次递归将搜索范围减半：T(n) = T(n/2) + O(1)
    - 使用主定理：a=1, b=2, f(n)=O(1)
    - 根据主定理：T(n) = Θ(log n)
    - 递归深度：log₂(n)
    
    空间复杂度：O(log n)
    - 递归调用栈深度为log n
    - 每个调用需要O(1)的栈空间
    
    前提：数组必须是有序的
    """
    if right is None:
        right = len(arr) - 1
    
    if left > right:
        return -1  # 未找到
    
    mid = (left + right) // 2
    
    if arr[mid] == target:
        return mid
    elif arr[mid] > target:
        return binary_search_recursive(arr, target, left, mid - 1)
    else:
        return binary_search_recursive(arr, target, mid + 1, right)


# ============================================================================
# 示例4：快速排序
# ============================================================================

def quick_sort(arr: List[int], left: int = 0, right: int = None) -> List[int]:
    """
    快速排序 - 递归实现
    
    时间复杂度：
    - 最好情况：O(n log n) - 每次分割都很均匀
      * T(n) = 2T(n/2) + O(n)，根据主定理：O(n log n)
    - 平均情况：O(n log n) - 平均分割
    - 最坏情况：O(n²) - 每次选择最差的主元（已排序数组）
      * T(n) = T(n-1) + T(0) + O(n) = T(n-1) + O(n)
      * 展开后：O(n²)
    
    空间复杂度：O(log n)
    - 递归调用栈深度：平均log n（最好情况）
    - 最坏情况：O(n)（当数组已排序时）
    
    优化：随机选择主元可以避免最坏情况
    """
    if right is None:
        right = len(arr) - 1
        arr = arr.copy()  # 不修改原数组
    
    if left < right:
        # 分割：将数组分为两部分
        pivot_index = partition(arr, left, right)
        
        # 递归排序两部分
        quick_sort(arr, left, pivot_index - 1)
        quick_sort(arr, pivot_index + 1, right)
    
    return arr


def partition(arr: List[int], left: int, right: int) -> int:
    """分割函数：将数组分为小于和大于主元的两部分"""
    pivot = arr[right]
    i = left - 1
    
    for j in range(left, right):
        if arr[j] <= pivot:
            i += 1
            arr[i], arr[j] = arr[j], arr[i]
    
    arr[i + 1], arr[right] = arr[right], arr[i + 1]
    return i + 1


# ============================================================================
# 示例5：归并排序
# ============================================================================

def merge_sort(arr: List[int]) -> List[int]:
    """
    归并排序 - 递归实现
    
    时间复杂度：O(n log n)（所有情况）
    - 递推关系：T(n) = 2T(n/2) + O(n)
    - 根据主定理：a=2, b=2, f(n)=O(n)
    - 因为f(n) = O(n) = O(n^log₂²) = O(n^1)
    - 所以：T(n) = Θ(n log n)
    
    空间复杂度：O(n)
    - 递归调用栈深度：O(log n)
    - 临时数组存储：O(n)
    - 总空间：O(n)
    
    特点：稳定排序，时间复杂度始终为O(n log n)
    """
    if len(arr) <= 1:
        return arr
    
    # 分割
    mid = len(arr) // 2
    left = merge_sort(arr[:mid])
    right = merge_sort(arr[mid:])
    
    # 合并
    return merge(left, right)


def merge(left: List[int], right: List[int]) -> List[int]:
    """合并两个有序数组"""
    result = []
    i = j = 0
    
    while i < len(left) and j < len(right):
        if left[i] <= right[j]:
            result.append(left[i])
            i += 1
        else:
            result.append(right[j])
            j += 1
    
    result.extend(left[i:])
    result.extend(right[j:])
    return result


# ============================================================================
# 示例6：计算幂（快速幂算法）
# ============================================================================

def power_naive(base: float, exponent: int) -> float:
    """
    计算幂 - 朴素实现
    
    时间复杂度：O(n)
    - 循环n次
    
    空间复杂度：O(1)
    """
    result = 1
    for _ in range(exponent):
        result *= base
    return result


def power_recursive(base: float, exponent: int) -> float:
    """
    快速幂 - 递归实现
    
    时间复杂度：O(log n)
    - 递推关系：T(n) = T(n/2) + O(1)
    - 每次递归指数减半
    - 递归深度：log₂(n)
    
    空间复杂度：O(log n)
    - 递归调用栈深度：log n
    
    原理：
    - 如果exponent是偶数：base^exponent = (base^(exponent/2))²
    - 如果exponent是奇数：base^exponent = base * (base^((exponent-1)/2))²
    """
    if exponent == 0:
        return 1
    if exponent == 1:
        return base
    
    half = power_recursive(base, exponent // 2)
    
    if exponent % 2 == 0:
        return half * half
    else:
        return base * half * half


# ============================================================================
# 性能测试和复杂度验证
# ============================================================================

def measure_time(func, *args, **kwargs):
    """测量函数执行时间"""
    start = time.perf_counter()
    result = func(*args, **kwargs)
    end = time.perf_counter()
    return result, (end - start) * 1000  # 返回毫秒


def compare_fibonacci_implementations():
    """比较不同斐波那契实现的性能"""
    print("=" * 60)
    print("斐波那契数列 - 性能对比")
    print("=" * 60)
    
    test_values = [10, 20, 30, 35]
    
    for n in test_values:
        print(f"\n计算 fib({n}):")
        
        # 朴素递归（只测试小值，避免等待太久）
        if n <= 30:
            try:
                _, time_naive = measure_time(fibonacci_naive, n)
                print(f"  朴素递归:     {time_naive:.2f} ms")
            except:
                print(f"  朴素递归:     超时或栈溢出")
        else:
            print(f"  朴素递归:     跳过（n={n}太大）")
        
        # 记忆化递归
        _, time_memo = measure_time(fibonacci_memoized, n)
        print(f"  记忆化递归:   {time_memo:.2f} ms")
        
        # 迭代实现
        _, time_iter = measure_time(fibonacci_iterative, n)
        print(f"  迭代实现:     {time_iter:.2f} ms")


def complexity_analysis_summary():
    """复杂度分析总结"""
    print("\n" + "=" * 60)
    print("算法复杂度总结表")
    print("=" * 60)
    
    summary = [
        ["算法", "时间复杂度", "空间复杂度", "说明"],
        ["-" * 50, "-" * 20, "-" * 20, "-" * 50],
        ["斐波那契（朴素递归）", "O(2^n)", "O(n)", "大量重复计算"],
        ["斐波那契（记忆化）", "O(n)", "O(n)", "避免重复计算"],
        ["斐波那契（迭代）", "O(n)", "O(1)", "最优实现"],
        ["汉诺塔", "O(2^n)", "O(n)", "指数级增长"],
        ["二分查找", "O(log n)", "O(log n)", "分治，每次减半"],
        ["快速排序（平均）", "O(n log n)", "O(log n)", "分治，平均分割"],
        ["快速排序（最坏）", "O(n²)", "O(n)", "最差主元选择"],
        ["归并排序", "O(n log n)", "O(n)", "稳定，始终O(n log n)"],
        ["快速幂", "O(log n)", "O(log n)", "分治，指数减半"],
    ]
    
    for row in summary:
        print(f"{row[0]:<30} {row[1]:<20} {row[2]:<20} {row[3]}")


def demonstrate_hanoi():
    """演示汉诺塔问题"""
    print("\n" + "=" * 60)
    print("汉诺塔问题演示")
    print("=" * 60)
    
    for n in [1, 2, 3]:
        moves = hanoi_tower(n, "A", "C", "B")
        print(f"\nn={n}时，最少移动次数：{len(moves)}")
        print(f"理论值：2^{n} - 1 = {2**n - 1}")
        if n <= 3:
            print("移动步骤：")
            for i, move in enumerate(moves, 1):
                print(f"  {i}. {move}")


def demonstrate_binary_search():
    """演示二分查找"""
    print("\n" + "=" * 60)
    print("二分查找演示")
    print("=" * 60)
    
    arr = [1, 3, 5, 7, 9, 11, 13, 15, 17, 19]
    target = 7
    
    print(f"有序数组：{arr}")
    print(f"查找目标：{target}")
    
    index = binary_search_recursive(arr, target)
    print(f"结果：索引 {index}" if index != -1 else "未找到")
    
    print(f"\n复杂度分析：")
    print(f"  数组长度 n = {len(arr)}")
    print(f"  时间复杂度：O(log n) = O(log {len(arr)}) ≈ {len(arr).bit_length()} 次比较")
    print(f"  空间复杂度：O(log n) = O(log {len(arr)}) 递归栈深度")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("递归函数与复杂度分析教程")
    print("=" * 60)
    
    # 性能对比
    compare_fibonacci_implementations()
    
    # 复杂度总结
    complexity_analysis_summary()
    
    # 汉诺塔演示
    demonstrate_hanoi()
    
    # 二分查找演示
    demonstrate_binary_search()
    
    print("\n" + "=" * 60)
    print("教程结束")
    print("=" * 60)
