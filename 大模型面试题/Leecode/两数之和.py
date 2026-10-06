class Solution:
    def twoSum(self, nums: list[int], target: int) -> list[int]:
        # 哈希表一遍扫描：值 -> 下标。先查 complement 再存当前值，
        # 天然处理重复元素（如 [3,3] target=6）与"不能复用同一元素"
        seen = {}
        for i, num in enumerate(nums):
            if target - num in seen:
                return [seen[target - num], i]
            seen[num] = i
        return []


solution = Solution()
print(solution.twoSum([2, 7, 11, 15], 9))   # [0, 1]
print(solution.twoSum([3, 3], 6))           # [0, 1]  旧解法在此用例返回 None
print(solution.twoSum([3, 2, 4], 6))        # [1, 2]
