def count_pairs(matrix):
    count = 0
    for row in matrix:
        for cell in row:
            count += cell
    return count
