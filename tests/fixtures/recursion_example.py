def walk_down(n):
    if n <= 0:
        return 0
    return 1 + walk_down(n - 1)
