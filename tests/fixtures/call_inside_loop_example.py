def helper_linear(items):
    for item in items:
        print(item)


def helper_quadratic(items):
    for a in items:
        for b in items:
            print(a, b)


def main_direct(items):
    helper_linear(items)


def main_loop_linear(items):
    for item in items:
        helper_linear(items)


def main_loop_quadratic(items):
    for item in items:
        helper_quadratic(items)
