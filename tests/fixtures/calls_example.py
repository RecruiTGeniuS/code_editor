def helper_linear(items):
    for item in items:
        print(item)


def helper_quadratic(items):
    for a in items:
        for b in items:
            print(a, b)


def main_linear(items):
    helper_linear(items)


def main_quadratic(items):
    helper_quadratic(items)


def main_unknown(items):
    external_func(items)
