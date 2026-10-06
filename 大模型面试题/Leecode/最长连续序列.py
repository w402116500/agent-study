class Solution:
    def longestConsecutive(self, nums: list[int]) -> int:
        # 哈希表 O(n)：只从每段连续序列的起点（num-1 不在集合中）向后数
        num_set = set(nums)
        longest = 0
        for num in num_set:
            if num - 1 not in num_set:
                length = 1
                while num + length in num_set:
                    length += 1
                longest = max(longest, length)
        return longest

solution = Solution()
print(solution.longestConsecutive([100, 4, 200, 1, 3, 2]))  # 4
print(solution.longestConsecutive([1, 2, 3, 5, 6]))         # 3  旧解法在此返回 5
print(solution.longestConsecutive([]))                       # 0
