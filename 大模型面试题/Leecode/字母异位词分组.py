from collections import defaultdict


class Solution:
    def groupAnagrams(self, strs: list[str]) -> list[list[str]]:
        seen = defaultdict(list)
        for s in strs:
            y = "".join(sorted(s)) # eat -> aet  aet为seen的key
            seen[y].append(s)
        return list(seen.values())
    

solution = Solution()
print(solution.groupAnagrams(["eat", "tea", "tan", "ate", "nat", "bat"]))  # [["eat", "tea", "ate"], ["tan", "nat"], ["bat"]]
