def binary_search(arr, target):
    left, right = 0, len(arr) - 1
    while left <= right:
        mid = (left + right) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            left = mid + 1
        else:
            right = mid - 1
    return -1


def two_sum_sorted(arr, target):
    left, right = 0, len(arr) - 1
    while left < right:
        s = arr[left] + arr[right]
        if s == target:
            return left, right
        elif s < target:
            left += 1
        else:
            right -= 1
    return None


def sliding_window_sum(arr, limit):
    left = 0
    total = 0
    for right in range(len(arr)):
        total += arr[right]
        while total > limit:
            total -= arr[left]
            left += 1
    return total


def sort_then_scan(items):
    sorted_items = sorted(items)
    total = 0
    for x in sorted_items:
        total += x
    return total


def dependent_nested_loop(items):
    count = 0
    for i in range(len(items)):
        for j in range(i):
            count += 1
    return count
